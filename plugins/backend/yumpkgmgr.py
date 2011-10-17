#!/usr/bin/python -tt
#
# Copyright (c) 2007 Red Hat  Inc.
# Copyright (c) 2010, 2011 Intel, Inc.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; version 2 of the License
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 59
# Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os, sys, re

import rpmUtils
import yum

from mic import msger
from mic.kickstart import ksparser
from mic.utils import rpmmisc, fs_related as fs
from mic.utils.errors import CreatorError
from mic.imager.baseimager import BaseImageCreator

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
                fmt = "\r  %-10.10s: %-20.20s " + bar + " " + done
            else:
                bar = fmt_bar % (self.mark * marks, )
                fmt = "  %-10.10s: %-20.20s "  + bar + " " + done
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
                    if total > 0:
                        hdr, rpmloc = h
                        m = re.match("(.*)-(\d+.*)-(\d+\.\d+)\.(.+)\.rpm", os.path.basename(rpmloc))
                        if m:
                            pkgname = m.group(1)
                        else:
                            pkgname = os.path.basename(rpmloc)
                    if self.output and (sys.stdout.isatty() or self.total_installed == self.total_actions):
                        fmt = self._makefmt(percent)
                        msg = fmt % ("Installing", pkgname)
                        if msg != self.lastmsg:
                            msger.info(msg)
                            self.lastmsg = msg
                            if self.total_installed == self.total_actions:
                                msger.raw()

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

from mic.pluginbase import BackendPlugin
class Yum(BackendPlugin, yum.YumBase):
    name = 'yum'

    def __init__(self, creator = None, recording_pkgs=None):
        if not isinstance(creator, BaseImageCreator):
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
        self.__pkgs_license = {}
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
        conf += "persistdir=/var/lib/yum\n"
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
        import glob
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
        except yum.Errors.InstallError:
            return "No package(s) available to install"
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
            msger.warning("No such package %s to remove" %(pkg,))

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
        if not rpmmisc.checkRepositoryEULA(name, repo):
            msger.warning('skip repo:%s for failed EULA confirmation' % name)
            return None

        if mirrorlist:
            repo.mirrorlist = _varSubstitute(mirrorlist)

        conf = yum.config.RepoConf()
        for k, v in conf.iteritems():
            if v or not hasattr(repo, k):
                repo.setAttribute(k, v)

        repo.basecachedir = self.conf.cachedir
        repo.base_persistdir = self.conf.persistdir
        repo.failovermethod = "priority"
        repo.metadata_expire = 0
        # Enable gpg check for verifying corrupt packages
        repo.gpgcheck = 1
        repo.enable()
        repo.setup(0)
        self.repos.add(repo)

        msger.verbose('repo: %s was added' % name)
        return repo

    def installLocal(self, pkg, po=None, updateonly=False):
        ts = rpmUtils.transaction.initReadOnlyTransaction()
        try:
            hdr = rpmUtils.miscutils.hdrFromPackage(ts, pkg)
        except RpmUtilsError, e:
            raise Errors.MiscError, 'Could not open local rpm file: %s: %s' % (pkg, e)
        self.deselectPackage(hdr['name'])
        yum.YumBase.installLocal(self, pkg, po, updateonly)

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
                license = pkg.license
                if license in self.__pkgs_license.keys():
                    self.__pkgs_license[license].append(pkg_long_name)
                else:
                    self.__pkgs_license[license] = [pkg_long_name]

        total_count = len(dlpkgs)
        cached_count = 0
        msger.info("\nChecking packages cache and packages integrity ...")
        for po in dlpkgs:
            local = po.localPkg()
            if not os.path.exists(local):
                continue
            if not self.verifyPkg(local, po, False):
                msger.warning("Package %s is damaged: %s" % (os.path.basename(local), local))
            else:
                cached_count +=1

        msger.info("%d packages to be installed, %d packages gotten from cache, %d packages to be downloaded" % (total_count, cached_count, total_count - cached_count))
        try:
            repos = self.repos.listEnabled()
            for repo in repos:
                repo.setCallback(fs.TextProgress(total_count - cached_count))
            self.downloadPkgs(dlpkgs)
            # FIXME: sigcheck?

            self.initActionTs()
            self.populateTs(keepold=0)
            deps = self.ts.check()
            if len(deps) != 0:
                """ This isn't fatal, Ubuntu has this issue but it is ok. """
                msger.debug(deps)
                msger.warning("Dependency check failed!")

            rc = self.ts.order()
            if rc != 0:
                raise CreatorError("ordering packages for installation failed!")

            # FIXME: callback should be refactored a little in yum
            cb = getRPMCallback()
            cb.tsInfo = self.tsInfo
            cb.filelog = False

            msger.warning('\nCaution, do NOT interrupt the installation, else mic cannot finish the cleanup.')
            installlogfile = "%s/__catched_stderr.buf" % (self.creator._instroot)
            msger.enable_logstderr(installlogfile)
            ret = self.runTransaction(cb)
            self._cleanupRpmdbLocks(self.conf.installroot)
            msger.disable_logstderr()
            return ret
        except rpmUtils.RpmUtilsError, e:
            raise CreatorError("%s, notice: mic doesn't support delta rpm, please check whether all the packages have .rpm available" % e)
        except yum.Errors.RepoError, e:
            raise CreatorError("Unable to download from repo : %s" % (e,))
        except yum.Errors.YumBaseError, e:
            raise CreatorError("Unable to install: %s" % (e,))

    def getAllContent(self):
        return self.__pkgs_content

    def getPkgsLicense(self):
        return self.__pkgs_license
