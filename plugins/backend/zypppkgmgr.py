#!/usr/bin/python

import os
import sys
import glob
import re
import zypp
import rpm
import shutil
import tempfile
import urlparse
import urllib2 as u2
import pykickstart.parser
from mic.utils.errors import *
from mic.imager.baseimager import BaseImageCreator as ImageCreator
from mic.utils.fs_related import *
from mic.utils.misc import *
from mic.utils.rpmmisc import *
from mic.pluginbase.backend_plugin import BackendPlugin

class RepositoryStub:
    def __init__(self):
        self.name = None
        self.baseurl = []
        self.mirrorlist = None
        self.proxy = None
        self.proxy_username = None
        self.proxy_password = None
        self.includepkgs = None
        self.includepkgs = None
        self.exclude = None

        self.enabled = True
        self.autorefresh = True
        self.keeppackages = True

class RepoError(CreatorError):
    pass

class RpmError(CreatorError):
    pass

class Zypp(BackendPlugin):
    def __init__(self, creator = None, recording_pkgs=None):
        if not isinstance(creator, ImageCreator):
            raise CreatorError("Invalid argument: creator")

        self.__recording_pkgs = recording_pkgs
        self.__pkgs_content = {}
        self.creator = creator
        self.repos = []
        self.packages = []
        self.patterns = []
        self.localpkgs = {}
        self.repo_manager = None
        self.repo_manager_options = None
        self.Z = None
        self.ts = None
        self.probFilterFlags = []
        self.bin_rpm = find_binary_path("rpm")
        self.incpkgs = []
        self.excpkgs = []

    def doFileLogSetup(self, uid, logfile):
        # don't do the file log for the livecd as it can lead to open fds
        # being left and an inability to clean up after ourself
        pass

    def closeRpmDB(self):
        pass

    def close(self):
        try:
            os.unlink(self.installroot + "/yum.conf")
        except:
            pass
        self.closeRpmDB()
        if not os.path.exists("/etc/fedora-release") and not os.path.exists("/etc/meego-release"):
            for i in range(3, os.sysconf("SC_OPEN_MAX")):
                try:
                    os.close(i)
                except:
                    pass
        if self.ts:
            self.ts.closeDB()
            self.ts = None

    def __del__(self):
        self.close()

    def _writeConf(self, confpath, installroot):
        conf  = "[main]\n"
        conf += "installroot=%s\n" % installroot
        conf += "cachedir=/var/cache/yum\n"
        conf += "plugins=0\n"
        conf += "reposdir=\n"
        conf += "failovermethod=priority\n"
        conf += "http_caching=packages\n"

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
        self.installroot = installroot

    def selectPackage(self, pkg):
        """ Select a given package or package pattern, can be specified with name.arch or name* or *name """
        if not self.Z:
            self.__initialize_zypp()

        found = False
        startx = pkg.startswith("*")
        endx = pkg.endswith("*")
        ispattern = startx or endx
        sp = pkg.rsplit(".", 2)
        for item in self.Z.pool():
            kind = "%s" % item.kind()
            if kind == "package":
                name = "%s" % item.name()
                if not ispattern:
                    if name in self.incpkgs or self.excpkgs:
                        found = True
                        break
                    if len(sp) == 2:
                        arch = "%s" % item.arch()
                        if name == sp[0] and arch == sp[1]:
                            found = True
                            if name not in self.packages:
                                self.packages.append(name)
                                item.status().setToBeInstalled (zypp.ResStatus.USER)
                            break
                    else:
                        if name == sp[0]:
                            found = True
                            if name not in self.packages:
                                self.packages.append(name)
                                item.status().setToBeInstalled (zypp.ResStatus.USER)
                            break
                else:
                    if name in self.incpkgs or self.excpkgs:
                        found =  True
                        continue
                    if startx and name.endswith(sp[0][1:]):
                        found = True
                        if name not in self.packages:
                            self.packages.append(name)
                            item.status().setToBeInstalled (zypp.ResStatus.USER)

                    if endx and name.startswith(sp[0][:-1]):
                        found = True
                        if name not in self.packages:
                            self.packages.append(name)
                            item.status().setToBeInstalled (zypp.ResStatus.USER)
        if found:
            return None
        else:
            e = CreatorError("Unable to find package: %s" % (pkg,))
            return e

    def deselectPackage(self, pkg):
        """Deselect package.  Can be specified as name.arch or name*"""

        if not self.Z:
            self.__initialize_zypp()

        startx = pkg.startswith("*")
        endx = pkg.endswith("*")
        ispattern = startx or endx
        sp = pkg.rsplit(".", 2)
        for item in self.Z.pool():
            kind = "%s" % item.kind()
            if kind == "package":
                name = "%s" % item.name()
                if not ispattern:
                    if len(sp) == 2:
                        arch = "%s" % item.arch()
                        if name == sp[0] and arch == sp[1]:
                            if item.status().isToBeInstalled():
                                item.status().resetTransact(zypp.ResStatus.USER)
                            if name in self.packages:
                                self.packages.remove(name)
                            break
                    else:
                        if name == sp[0]:
                            if item.status().isToBeInstalled():
                                item.status().resetTransact(zypp.ResStatus.USER)
                            if name in self.packages:
                                self.packages.remove(name)
                            break
                else:
                    if startx and name.endswith(sp[0][1:]):
                        if item.status().isToBeInstalled():
                            item.status().resetTransact(zypp.ResStatus.USER)
                        if name in self.packages:
                            self.packages.remove(name)

                    if endx and name.startswith(sp[0][:-1]):
                        if item.status().isToBeInstalled():
                            item.status().resetTransact(zypp.ResStatus.USER)
                        if name in self.packages:
                            self.packages.remove(name)

    def __selectIncpkgs(self):
        found = False
        for pkg in self.incpkgs:
            for item in self.Z.pool():
                kind = "%s" % item.kind()
                if kind == "package":
                    name = "%s" % item.name()
                    repoalias = "%s" % item.repoInfo().alias()
                    if name == pkg and repoalias.endswith("include"):
                        found = True
                        if name not in self.packages:
                            self.packages.append(name)
                            item.status().setToBeInstalled (zypp.ResStatus.USER)
                        break
        if not found:
            raise CreatorError("Unable to find package: %s" % (pkg,))

    def __selectExcpkgs(self):
        found = False
        for pkg in self.excpkgs:
            for item in self.Z.pool():
                kind = "%s" % item.kind()
                if kind == "package":
                    name = "%s" % item.name()
                    repoalias = "%s" % item.repoInfo().alias()
                    if name == pkg and not repoalias.endswith("exclude"):
                        found = True
                        if name not in self.packages:
                            self.packages.append(name)
                            item.status().setToBeInstalled (zypp.ResStatus.USER)
                        break
        if not found:
            raise CreatorError("Unable to find package: %s" % (pkg,))

    def selectGroup(self, grp, include = pykickstart.parser.GROUP_DEFAULT):
        if not self.Z:
            self.__initialize_zypp()
        found = False
        for item in self.Z.pool():
            kind = "%s" % item.kind()
            if kind == "pattern":
                summary = "%s" % item.summary()
                name = "%s" % item.name()
                if name == grp or summary == grp:
                    found = True
                    if name not in self.patterns:
                        self.patterns.append(name)
                        item.status().setToBeInstalled (zypp.ResStatus.USER)
                    break

        if found:
            if include == pykickstart.parser.GROUP_REQUIRED:
                map(lambda p: self.deselectPackage(p), grp.default_packages.keys())
            elif include == pykickstart.parser.GROUP_ALL:
                map(lambda p: self.selectPackage(p), grp.optional_packages.keys())
            return None
        else:
            e = CreatorError("Unable to find pattern: %s" % (grp,))
            return e

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
        if not self.repo_manager:
            self.__initialize_repo_manager()

        repo = RepositoryStub()
        repo.name = name
        repo.id = name
        repo.proxy = proxy
        repo.proxy_username = proxy_username
        repo.proxy_password = proxy_password
        repo.baseurl.append(url)
        repo_alias = repo.id
        if inc:
            repo_alias = name + "include"
            self.incpkgs = inc
        if exc:
            repo_alias = name + "exclude"
            self.excpkgs = exc

        # check LICENSE files
        if not self.checkRepositoryEULA(name, repo):
            return None

        if mirrorlist:
            repo.mirrorlist = mirrorlist

        # Enable gpg check for verifying corrupt packages
        repo.gpgcheck = 1
        self.repos.append(repo)


        try:
            repo_info = zypp.RepoInfo()
            repo_info.setAlias(repo_alias)
            repo_info.setName(repo.name)
            repo_info.setEnabled(repo.enabled)
            repo_info.setAutorefresh(repo.autorefresh)
            repo_info.setKeepPackages(repo.keeppackages)
            repo_info.addBaseUrl(zypp.Url(repo.baseurl[0]))
            self.repo_manager.addRepository(repo_info)
            self.__build_repo_cache(name)
        except RuntimeError, e:
            raise CreatorError("%s" % (e,))

        return repo

    def installHasFile(self, file):
        return False

    def runInstall(self, checksize = 0):
        if self.incpkgs:
            self.__selectIncpkgs()
        if self.excpkgs:
            self.__selectExcpkgs()

        os.environ["HOME"] = "/"
        self.buildTransaction()

        todo = zypp.GetResolvablesToInsDel(self.Z.pool())
        installed_pkgs = todo._toInstall
        dlpkgs = []
        for item in installed_pkgs:
            if not zypp.isKindPattern(item):
                dlpkgs.append(item)

        # record the total size of installed pkgs
        pkgs_total_size = sum(map(lambda x: int(x.installSize()), dlpkgs))

        # check needed size before actually download and install
        if checksize and pkgs_total_size > checksize:
            raise CreatorError("Size of specified root partition in kickstart file is too small to install all selected packages.")

        if self.__recording_pkgs:
            # record all pkg and the content
            for pkg in dlpkgs:
                pkg_long_name = "%s-%s.%s.rpm" % (pkg.name(), pkg.edition(), pkg.arch())
                self.__pkgs_content[pkg_long_name] = {} #TBD: to get file list

        total_count = len(dlpkgs)
        cached_count = 0
        localpkgs = self.localpkgs.keys()
        print "Checking packages cache and packages integrity..."
        for po in dlpkgs:
            """ Check if it is cached locally """
            if po.name() in localpkgs:
                cached_count += 1
            else:
                local = self.getLocalPkgPath(po)
                if os.path.exists(local):
                    if self.checkPkg(local) != 0:
                        os.unlink(local)
                    else:
                        cached_count += 1
        download_count =  total_count - cached_count
        print "%d packages to be installed, %d packages gotten from cache, %d packages to be downloaded" % (total_count, cached_count, download_count)
        try:
            if download_count > 0:
                print "downloading packages..."
            self.downloadPkgs(dlpkgs, download_count)
            self.installPkgs(dlpkgs)

        except RepoError, e:
            raise CreatorError("Unable to download from repo : %s" % (e,))
        except RpmError, e:
            raise CreatorError("Unable to install: %s" % (e,))

    def getAllContent(self):
        return self.__pkgs_content

    def __initialize_repo_manager(self):
        if self.repo_manager:
            return

        """ Clean up repo metadata """
        shutil.rmtree(self.creator.cachedir + "/var", ignore_errors = True)
        shutil.rmtree(self.creator.cachedir + "/etc", ignore_errors = True)
        shutil.rmtree(self.creator.cachedir + "/raw", ignore_errors = True)
        shutil.rmtree(self.creator.cachedir + "/solv", ignore_errors = True)

        zypp.KeyRing.setDefaultAccept( zypp.KeyRing.ACCEPT_UNSIGNED_FILE
                                       | zypp.KeyRing.ACCEPT_VERIFICATION_FAILED
                                       | zypp.KeyRing.ACCEPT_UNKNOWNKEY
                                       | zypp.KeyRing.TRUST_KEY_TEMPORARILY
                                     )
        self.repo_manager_options = zypp.RepoManagerOptions(zypp.Pathname(self.creator._instroot))
        self.repo_manager_options.knownReposPath = zypp.Pathname(self.creator.cachedir + "/etc/zypp/repos.d")
        self.repo_manager_options.repoCachePath = zypp.Pathname(self.creator.cachedir + "/var/cache/zypp")
        self.repo_manager_options.repoRawCachePath = zypp.Pathname(self.creator.cachedir + "/raw")
        self.repo_manager_options.repoSolvCachePath = zypp.Pathname(self.creator.cachedir + "/solv")
        self.repo_manager_options.repoPackagesCachePath = zypp.Pathname(self.creator.cachedir + "/packages")

        self.repo_manager = zypp.RepoManager(self.repo_manager_options)


    def __build_repo_cache(self, name):
        repos = self.repo_manager.knownRepositories()
        for repo in repos:
            if not repo.enabled():
                continue
            reponame = "%s" % repo.name()
            if reponame != name:
                continue
            if self.repo_manager.isCached( repo ):
                return
            #print "Retrieving repo metadata from %s ..." % repo.url()
            self.repo_manager.buildCache( repo, zypp.RepoManager.BuildIfNeeded )


    def __initialize_zypp(self):
        if self.Z:
            return

        zconfig = zypp.ZConfig_instance()

        """ Set system architecture """
        if self.creator.target_arch and self.creator.target_arch.startswith("arm"):
            arches = ["armv7l", "armv7nhl", "armv7hl"]
            if self.creator.target_arch not in arches:
                raise CreatorError("Invalid architecture: %s" % self.creator.target_arch)
            arch_map = {}
            if self.creator.target_arch == "armv7l":
                arch_map["armv7l"] = zypp.Arch_armv7l()
            elif self.creator.target_arch == "armv7nhl":
                arch_map["armv7nhl"] = zypp.Arch_armv7nhl()
            elif self.creator.target_arch == "armv7hl":
                arch_map["armv7hl"] = zypp.Arch_armv7hl()
            zconfig.setSystemArchitecture(arch_map[self.creator.target_arch])

        print "zypp architecture: %s" % zconfig.systemArchitecture()

        """ repoPackagesCachePath is corrected by this """
        self.repo_manager = zypp.RepoManager(self.repo_manager_options)
        repos = self.repo_manager.knownRepositories()
        for repo in repos:
            if not repo.enabled():
                continue
            if not self.repo_manager.isCached( repo ):
                print "Retrieving repo metadata from %s ..." % repo.url()
                self.repo_manager.buildCache( repo, zypp.RepoManager.BuildIfNeeded )
            else:
                self.repo_manager.refreshMetadata(repo, zypp.RepoManager.BuildIfNeeded)
            self.repo_manager.loadFromCache( repo );

        self.Z = zypp.ZYppFactory_instance().getZYpp()
        self.Z.initializeTarget( zypp.Pathname(self.creator._instroot) )
        self.Z.target().load();


    def buildTransaction(self):
        if not self.Z.resolver().resolvePool():
            print "Problem count: %d" % len(self.Z.resolver().problems())
            for problem in self.Z.resolver().problems():
                print "Problem: %s, %s" % (problem.description().decode("utf-8"), problem.details().decode("utf-8"))

    def getLocalPkgPath(self, po):
        repoinfo = po.repoInfo()
        name = po.name()
        cacheroot = repoinfo.packagesPath()
        arch =  po.arch()
        edition = po.edition()
        version = "%s-%s" % (edition.version(), edition.release())
        pkgpath = "%s/%s/%s-%s.%s.rpm" % (cacheroot, arch, name, version, arch)
        return pkgpath

    def installLocal(self, pkg, po=None, updateonly=False):
        if not self.ts:
            self.__initialize_transaction()
        pkgname = self.__get_pkg_name(pkg)
        self.localpkgs[pkgname] = pkg
        self.selectPackage(pkgname)

    def __get_pkg_name(self, pkgpath):
        h = readRpmHeader(self.ts, pkgpath)
        return h["name"]

    def downloadPkgs(self, package_objects, count):
        localpkgs = self.localpkgs.keys()
        progress_obj = TextProgress(count)
        for po in package_objects:
            if po.name() in localpkgs:
                continue
            filename = self.getLocalPkgPath(po)
            if os.path.exists(filename):
                if self.checkPkg(filename) == 0:
                    continue
            dir = os.path.dirname(filename)
            if not os.path.exists(dir):
                makedirs(dir)
            baseurl = po.repoInfo().baseUrls()[0].__str__()
            proxy = self.get_proxy(po.repoInfo())
            proxies = {}
            if proxy:
                proxies = {str(proxy.split(":")[0]):str(proxy)}

            location = zypp.asKindPackage(po).location()
            location = location.filename().__str__()
            if location.startswith("./"):
                location = location[2:]
            url = baseurl + "/%s" % location
            try:
                filename = myurlgrab(url, filename, proxies, progress_obj)
            except CreatorError, e:
                self.close()
                raise CreatorError("%s" % e)

    def installPkgs(self, package_objects):
        if not self.ts:
            self.__initialize_transaction()

        """ Set filters """
        probfilter = 0
        for flag in self.probFilterFlags:
            probfilter |= flag
        self.ts.setProbFilter(probfilter)

        localpkgs = self.localpkgs.keys()
        for po in package_objects:
            pkgname = po.name()
            if pkgname in localpkgs:
                rpmpath = self.localpkgs[pkgname]
            else:
                rpmpath = self.getLocalPkgPath(po)
            if not os.path.exists(rpmpath):
                """ Maybe it is a local repo """
                baseurl = po.repoInfo().baseUrls()[0].__str__()
                baseurl = baseurl.strip()
                if baseurl.startswith("file:/"):
                    rpmpath = baseurl[5:] + "/%s/%s" % (po.arch(), os.path.basename(rpmpath))
            if not os.path.exists(rpmpath):
                raise RpmError("Error: %s doesn't exist" % rpmpath)
            h = readRpmHeader(self.ts, rpmpath)
            self.ts.addInstall(h, rpmpath, 'u')

        unresolved_dependencies = self.ts.check()
        if not unresolved_dependencies:
            self.ts.order()
            cb = RPMInstallCallback(self.ts)
            self.ts.run(cb.callback, '')
            self.ts.closeDB()
            self.ts = None
        else:
            print unresolved_dependencies
            raise RepoError("Error: Unresolved dependencies, transaction failed.")

    def __initialize_transaction(self):
        if not self.ts:
            self.ts = rpm.TransactionSet(self.creator._instroot)
            # Set to not verify DSA signatures.
            self.ts.setVSFlags(rpm._RPMVSF_NOSIGNATURES|rpm._RPMVSF_NODIGESTS)

    def checkPkg(self, pkg):
        ret = 1
        if not os.path.exists(pkg):
            return ret
        ret = checkRpmIntegrity(self.bin_rpm, pkg)
        if ret != 0:
            print "Package %s is damaged: %s" % (os.path.basename(pkg), pkg)
        return ret

    def zypp_install(self):
        policy = zypp.ZYppCommitPolicy()
        policy.downloadMode(zypp.DownloadInAdvance)
        policy.dryRun( False )
        policy.syncPoolAfterCommit( False )
        result = self.Z.commit( policy )
        print result

    def _add_prob_flags(self, *flags):
        for flag in flags:
           if flag not in self.probFilterFlags:
               self.probFilterFlags.append(flag)

    def get_proxy(self, repoinfo):
        proxy = None
        reponame = "%s" % repoinfo.name()
        for repo in self.repos:
            if repo.name == reponame:
                proxy = repo.proxy
                break
        if proxy:
            return proxy
        else:
            repourl = repoinfo.baseUrls()[0].__str__()
            return get_proxy(repourl)

mic_plugin = ["zypp", Zypp]

