#
# yum.py : yum utilities
#
# Copyright 2007, Red Hat  Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import glob
import os
import sys
import logging

import yum
import rpmUtils
from mic.kickstart.pykickstart import parser as ksparser

import urlparse
import urllib2 as u2
import tempfile
import shutil
import subprocess

from mic.utils.errors import *
from mic.utils.fs_related import *
from mic.pluginbase.backend_plugin import BackendPlugin
from mic.imager.baseimager import BaseImageCreator as ImageCreator

def getRPMCallback():
    sys.path.append('/usr/share/yum-cli')
    import callback
    import rpm
    class MyRPMInstallCallback(callback.RPMInstallCallback):
        def _makefmt(self, percent, progress = True):
            l = len(str(self.total_actions))
            size = "%s.%s" % (l, l)
            fmt_done = "[%" + size + "s/%" + size + "s]"
            done = fmt_done % (self.total_installed + self.total_removed,
                               self.total_actions)
            marks = self.marks - (2 * l)
            width = "%s.%s" % (marks, marks)
            fmt_bar = "%-" + width + "s"
            if progress:
                bar = fmt_bar % (self.mark * int(marks * (percent / 100.0)), )
                fmt = "\r  %-10.10s: " + bar + " " + done
            else:
                bar = fmt_bar % (self.mark * marks, )
                fmt = "  %-10.10s: "  + bar + " " + done
            return fmt

        def callback(self, what, bytes, total, h, user):
            self.mark = "+"
            if what == rpm.RPMCALLBACK_TRANS_START:
                if bytes == 6:
                    self.total_actions = total

            elif what == rpm.RPMCALLBACK_TRANS_PROGRESS:
                pass

            elif what == rpm.RPMCALLBACK_TRANS_STOP:
                pass

            elif what == rpm.RPMCALLBACK_INST_OPEN_FILE:
                self.lastmsg = None
                hdr = None
                if h is not None:
                    hdr, rpmloc = h
                    handle = self._makeHandle(hdr)
                    fd = os.open(rpmloc, os.O_RDONLY)
                    self.callbackfilehandles[handle]=fd
                    self.total_installed += 1
                    self.installed_pkg_names.append(hdr['name'])
                    return fd
                else:
                    self._localprint("No header - huh?")

            elif what == rpm.RPMCALLBACK_INST_CLOSE_FILE:
                hdr = None
                if h is not None:
                    hdr, rpmloc = h
                    handle = self._makeHandle(hdr)
                    os.close(self.callbackfilehandles[handle])
                    fd = 0

            elif what == rpm.RPMCALLBACK_INST_PROGRESS:
                if h is not None:
                    percent = (self.total_installed*100L)/self.total_actions
                    if self.output and (sys.stdout.isatty() or self.total_installed == self.total_actions):
                        fmt = self._makefmt(percent)
                        msg = fmt % ("Installing")
                        if msg != self.lastmsg:
                            sys.stdout.write(msg)
                            sys.stdout.flush()
                            self.lastmsg = msg
                            if self.total_installed == self.total_actions:
                                 sys.stdout.write("\n")

            elif what == rpm.RPMCALLBACK_UNINST_START:
                pass

            elif what == rpm.RPMCALLBACK_UNINST_PROGRESS:
                pass

            elif what == rpm.RPMCALLBACK_UNINST_STOP:
                self.total_removed += 1

            elif what == rpm.RPMCALLBACK_REPACKAGE_START:
                pass
            elif what == rpm.RPMCALLBACK_REPACKAGE_STOP:
                pass
            elif what == rpm.RPMCALLBACK_REPACKAGE_PROGRESS:
                pass

    cb = MyRPMInstallCallback()
    return cb

class MyYumRepository(yum.yumRepo.YumRepository):
    def __init__(self, repoid):
        yum.yumRepo.YumRepository.__init__(self, repoid)
        self.sslverify = False

    def _setupGrab(self):
        self.sslverify = False
        yum.yumRepo.YumRepository._setupGrab(self)

    def __del__(self):
        pass

class Yum(BackendPlugin, yum.YumBase):
    def __init__(self, creator = None, recording_pkgs=None):
        if not isinstance(creator, ImageCreator):
            raise CreatorError("Invalid argument: creator")
        yum.YumBase.__init__(self)

        self.creator = creator

        if self.creator.target_arch:
            if not rpmUtils.arch.arches.has_key(self.creator.target_arch):
                rpmUtils.arch.arches["armv7hl"] = "noarch"
                rpmUtils.arch.arches["armv7tnhl"] = "armv7nhl"
                rpmUtils.arch.arches["armv7tnhl"] = "armv7thl"
                rpmUtils.arch.arches["armv7thl"] = "armv7hl"
                rpmUtils.arch.arches["armv7nhl"] = "armv7hl"
            self.arch.setup_arch(self.creator.target_arch)

        self.__recording_pkgs = recording_pkgs
        self.__pkgs_content = {}

    def doFileLogSetup(self, uid, logfile):
        # don't do the file log for the livecd as it can lead to open fds
        # being left and an inability to clean up after ourself
        pass

    def close(self):
        try:
            os.unlink(self.conf.installroot + "/yum.conf")
        except:
            pass
        self.closeRpmDB()
        yum.YumBase.close(self)
        self._delRepos()
        self._delSacks()

        if not os.path.exists("/etc/fedora-release") and not os.path.exists("/etc/meego-release"):
            for i in range(3, os.sysconf("SC_OPEN_MAX")):
                try:
                    os.close(i)
                except:
                    pass

    def __del__(self):
        pass

    def _writeConf(self, confpath, installroot):
        conf  = "[main]\n"
        conf += "installroot=%s\n" % installroot
        conf += "cachedir=/var/cache/yum\n"
        conf += "plugins=0\n"
        conf += "reposdir=\n"
        conf += "failovermethod=priority\n"
        conf += "http_caching=packages\n"
        conf += "sslverify=0\n"

        f = file(confpath, "w+")
        f.write(conf)
        f.close()

        os.chmod(confpath, 0644)

    def _cleanupRpmdbLocks(self, installroot):
        # cleans up temporary files left by bdb so that differing
        # versions of rpm don't cause problems
        for f in glob.glob(installroot + "/var/lib/rpm/__db*"):
            os.unlink(f)

    def setup(self, confpath, installroot):
        self._writeConf(confpath, installroot)
        self._cleanupRpmdbLocks(installroot)
        self.doConfigSetup(fn = confpath, root = installroot)
        self.conf.cache = 0
        self.doTsSetup()
        self.doRpmDBSetup()
        self.doRepoSetup()
        self.doSackSetup()

    def selectPackage(self, pkg):
        """Select a given package.  Can be specified with name.arch or name*"""
        try:
            self.install(pattern = pkg)
            return None
        except yum.Errors.InstallError, e:
            return e
        except yum.Errors.RepoError, e:
            raise CreatorError("Unable to download from repo : %s" % (e,))
        except yum.Errors.YumBaseError, e:
            raise CreatorError("Unable to install: %s" % (e,))

    def deselectPackage(self, pkg):
        """Deselect package.  Can be specified as name.arch or name*"""
        sp = pkg.rsplit(".", 2)
        txmbrs = []
        if len(sp) == 2:
            txmbrs = self.tsInfo.matchNaevr(name=sp[0], arch=sp[1])

        if len(txmbrs) == 0:
            exact, match, unmatch = yum.packages.parsePackages(self.pkgSack.returnPackages(), [pkg], casematch=1)
            for p in exact + match:
                txmbrs.append(p)

        if len(txmbrs) > 0:
            for x in txmbrs:
                self.tsInfo.remove(x.pkgtup)
                # we also need to remove from the conditionals
                # dict so that things don't get pulled back in as a result
                # of them.  yes, this is ugly.  conditionals should die.
                for req, pkgs in self.tsInfo.conditionals.iteritems():
                    if x in pkgs:
                        pkgs.remove(x)
                        self.tsInfo.conditionals[req] = pkgs
        else:
            logging.warn("No such package %s to remove" %(pkg,))

    def selectGroup(self, grp, include = ksparser.GROUP_DEFAULT):
        try:
            yum.YumBase.selectGroup(self, grp)
            if include == ksparser.GROUP_REQUIRED:
                map(lambda p: self.deselectPackage(p), grp.default_packages.keys())
            elif include == ksparser.GROUP_ALL:
                map(lambda p: self.selectPackage(p), grp.optional_packages.keys())
            return None
        except (yum.Errors.InstallError, yum.Errors.GroupsError), e:
            return e
        except yum.Errors.RepoError, e:
            raise CreatorError("Unable to download from repo : %s" % (e,))
        except yum.Errors.YumBaseError, e:
            raise CreatorError("Unable to install: %s" % (e,))

    def __checkAndDownloadURL(self, u2opener, url, savepath):
        try:
            if u2opener:
                f = u2opener.open(url)
            else:
                f = u2.urlopen(url)
        except u2.HTTPError, httperror:
            if httperror.code in (404, 503):
                return None
            else:
                raise CreatorError(httperror)
        except OSError, oserr:
            if oserr.errno == 2:
                return None
            else:
                raise CreatorError(oserr)
        except IOError, oserr:
            if hasattr(oserr, "reason") and oserr.reason.errno == 2:
                return None
            else:
                raise CreatorError(oserr)
        except u2.URLError, err:
            raise CreatorError(err)

        # save to file
        licf = open(savepath, "w")
        licf.write(f.read())
        licf.close()
        f.close()

        return savepath

    def __pagerFile(self, savepath):
        if os.path.splitext(savepath)[1].upper() in ('.HTM', '.HTML'):
            pagers = ('w3m', 'links', 'lynx', 'less', 'more')
        else:
            pagers = ('less', 'more')

        file_showed = None
        for pager in pagers:
            try:
                subprocess.call([pager, savepath])
            except OSError:
                continue
            else:
                file_showed = True
                break
        if not file_showed:
            f = open(savepath)
            print f.read()
            f.close()
            raw_input('press <ENTER> to continue...')

    def checkRepositoryEULA(self, name, repo):
        """ This function is to check the LICENSE file if provided. """

        # when proxy needed, make urllib2 follow it
        proxy = repo.proxy
        proxy_username = repo.proxy_username
        proxy_password = repo.proxy_password

        handlers = []
        auth_handler = u2.HTTPBasicAuthHandler(u2.HTTPPasswordMgrWithDefaultRealm())
        u2opener = None
        if proxy:
            if proxy_username:
                proxy_netloc = urlparse.urlsplit(proxy).netloc
                if proxy_password:
                    proxy_url = 'http://%s:%s@%s' % (proxy_username, proxy_password, proxy_netloc)
                else:
                    proxy_url = 'http://%s@%s' % (proxy_username, proxy_netloc)
            else:
                proxy_url = proxy

            proxy_support = u2.ProxyHandler({'http': proxy_url,
                                             'ftp': proxy_url})
            handlers.append(proxy_support)

        # download all remote files to one temp dir
        baseurl = None
        repo_lic_dir = tempfile.mkdtemp(prefix = 'repolic')

        for url in repo.baseurl:
            if not url.endswith('/'):
                url += '/'
            tmphandlers = handlers
            (scheme, host, path, parm, query, frag) = urlparse.urlparse(url)
            if scheme not in ("http", "https", "ftp", "ftps", "file"):
                raise CreatorError("Error: invalid url %s" % url)
            if '@' in host:
                try:
                    user_pass, host = host.split('@', 1)
                    if ':' in user_pass:
                        user, password = user_pass.split(':', 1)
                except ValueError, e:
                    raise CreatorError('Bad URL: %s' % url)
                print "adding HTTP auth: %s, %s" %(user, password)
                auth_handler.add_password(None, host, user, password)
                tmphandlers.append(auth_handler)
                url = scheme + "://" + host + path + parm + query + frag
            if len(tmphandlers) != 0:
                u2opener = u2.build_opener(*tmphandlers)
            # try to download
            repo_eula_url = urlparse.urljoin(url, "LICENSE.txt")
            repo_eula_path = self.__checkAndDownloadURL(
                                    u2opener,
                                    repo_eula_url,
                                    os.path.join(repo_lic_dir, repo.id + '_LICENSE.txt'))
            if repo_eula_path:
                # found
                baseurl = url
                break

        if not baseurl:
            return True

        # show the license file
        print 'For the software packages in this yum repo:'
        print '    %s: %s' % (name, baseurl)
        print 'There is an "End User License Agreement" file that need to be checked.'
        print 'Please read the terms and conditions outlined in it and answer the followed qustions.'
        raw_input('press <ENTER> to continue...')

        self.__pagerFile(repo_eula_path)

        # Asking for the "Accept/Decline"
        accept = True
        while accept:
            input_accept = raw_input('Would you agree to the terms and conditions outlined in the above End User License Agreement? (Yes/No): ')
            if input_accept.upper() in ('YES', 'Y'):
                break
            elif input_accept.upper() in ('NO', 'N'):
                accept = None
                print 'Will not install pkgs from this repo.'

        if not accept:
            #cleanup
            shutil.rmtree(repo_lic_dir)
            return None

        # try to find support_info.html for extra infomation
        repo_info_url = urlparse.urljoin(baseurl, "support_info.html")
        repo_info_path = self.__checkAndDownloadURL(
                                u2opener,
                                repo_info_url,
                                os.path.join(repo_lic_dir, repo.id + '_support_info.html'))
        if repo_info_path:
            print 'There is one more file in the repo for additional support information, please read it'
            raw_input('press <ENTER> to continue...')
            self.__pagerFile(repo_info_path)

        #cleanup
        shutil.rmtree(repo_lic_dir)
        return True

    def addRepository(self, name, url = None, mirrorlist = None, proxy = None, proxy_username = None, proxy_password = None, inc = None, exc = None):
        def _varSubstitute(option):
            # takes a variable and substitutes like yum configs do
            option = option.replace("$basearch", rpmUtils.arch.getBaseArch())
            option = option.replace("$arch", rpmUtils.arch.getCanonArch())
            return option

        repo = MyYumRepository(name)
        repo.sslverify = False

        """Set proxy"""
        repo.proxy = proxy
        repo.proxy_username = proxy_username
        repo.proxy_password = proxy_password

        if url:
            repo.baseurl.append(_varSubstitute(url))

        # check LICENSE files
        if not self.checkRepositoryEULA(name, repo):
            return None

        if mirrorlist:
            repo.mirrorlist = _varSubstitute(mirrorlist)
        conf = yum.config.RepoConf()
        for k, v in conf.iteritems():
            if v or not hasattr(repo, k):
                repo.setAttribute(k, v)
        repo.basecachedir = self.conf.cachedir
        repo.failovermethod = "priority"
        repo.metadata_expire = 0
        # Enable gpg check for verifying corrupt packages
        repo.gpgcheck = 1
        repo.enable()
        repo.setup(0)
        repo.setCallback(TextProgress())
        self.repos.add(repo)
        return repo

    def installHasFile(self, file):
        provides_pkg = self.whatProvides(file, None, None)
        dlpkgs = map(lambda x: x.po, filter(lambda txmbr: txmbr.ts_state in ("i", "u"), self.tsInfo.getMembers()))
        for p in dlpkgs:
            for q in provides_pkg:
                if (p == q):
                    return True
        return False

    def runInstall(self, checksize = 0):
        os.environ["HOME"] = "/"
        try:
            (res, resmsg) = self.buildTransaction()
        except yum.Errors.RepoError, e:
            raise CreatorError("Unable to download from repo : %s" %(e,))
        if res != 2:
            raise CreatorError("Failed to build transaction : %s" % str.join("\n", resmsg))

        dlpkgs = map(lambda x: x.po, filter(lambda txmbr: txmbr.ts_state in ("i", "u"), self.tsInfo.getMembers()))

        # record the total size of installed pkgs
        pkgs_total_size = sum(map(lambda x: int(x.size), dlpkgs))

        # check needed size before actually download and install
        if checksize and pkgs_total_size > checksize:
            raise CreatorError("Size of specified root partition in kickstart file is too small to install all selected packages.")

        if self.__recording_pkgs:
            # record all pkg and the content
            for pkg in dlpkgs:
                pkg_long_name = "%s-%s.%s.rpm" % (pkg.name, pkg.printVer(), pkg.arch)
                self.__pkgs_content[pkg_long_name] = pkg.files

        total_count = len(dlpkgs)
        cached_count = 0
        print "Checking packages cache and packages integrity..."
        for po in dlpkgs:
            local = po.localPkg()
            if not os.path.exists(local):
                continue
            if not self.verifyPkg(local, po, False):
                print "Package %s is damaged: %s" % (os.path.basename(local), local)
            else:
                cached_count +=1
        print "%d packages to be installed, %d packages gotten from cache, %d packages to be downloaded" % (total_count, cached_count, total_count - cached_count)
        try:
            self.downloadPkgs(dlpkgs)
            # FIXME: sigcheck?

            self.initActionTs()
            self.populateTs(keepold=0)
            deps = self.ts.check()
            if len(deps) != 0:
                """ This isn't fatal, Ubuntu has this issue but it is ok. """
                print deps
                logging.warn("Dependency check failed!")
            rc = self.ts.order()
            if rc != 0:
                raise CreatorError("ordering packages for installation failed!")

            # FIXME: callback should be refactored a little in yum
            cb = getRPMCallback()
            cb.tsInfo = self.tsInfo
            cb.filelog = False
            ret = self.runTransaction(cb)
            print ""
            self._cleanupRpmdbLocks(self.conf.installroot)
            return ret
        except yum.Errors.RepoError, e:
            raise CreatorError("Unable to download from repo : %s" % (e,))
        except yum.Errors.YumBaseError, e:
            raise CreatorError("Unable to install: %s" % (e,))

    def getAllContent(self):
        return self.__pkgs_content

mic_plugin = ["yum", Yum]
