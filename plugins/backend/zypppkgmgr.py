#!/usr/bin/python -tt
#
# Copyright 2010, 2011 Intel, Inc.
#
# This copyrighted material is made available to anyone wishing to use, modify,
# copy, or redistribute it subject to the terms and conditions of the GNU
# General Public License v.2.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat
# trademarks that are incorporated in the source code or documentation are not
# subject to the GNU General Public License and may only be used or replicated
# with the express permission of Red Hat, Inc.
#

import os
import zypp
import rpm
import shutil

from pykickstart import parser as ksparser

from mic import msger
from mic.imager.baseimager import BaseImageCreator
from mic.utils import misc, rpmmisc, fs_related as fs
from mic.utils.errors import CreatorError

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

from mic.pluginbase import BackendPlugin
class Zypp(BackendPlugin):
    name = 'zypp'

    def __init__(self, creator = None, recording_pkgs=None):
        if not isinstance(creator, BaseImageCreator):
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
        self.incpkgs = []
        self.excpkgs = []

    def doFileLogSetup(self, uid, logfile):
        # don't do the file log for the livecd as it can lead to open fds
        # being left and an inability to clean up after ourself
        pass

    def closeRpmDB(self):
        pass

    def close(self):
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

    def _cleanupRpmdbLocks(self, installroot):
        # cleans up temporary files left by bdb so that differing
        # versions of rpm don't cause problems
        import glob
        for f in glob.glob(installroot + "/var/lib/rpm/__db*"):
            os.unlink(f)

    def setup(self, confpath, installroot):
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

    def selectGroup(self, grp, include = ksparser.GROUP_DEFAULT):
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
            if include == ksparser.GROUP_REQUIRED:
                map(lambda p: self.deselectPackage(p), grp.default_packages.keys())
            return None
        else:
            e = CreatorError("Unable to find pattern: %s" % (grp,))
            return e

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
        if not rpmmisc.checkRepositoryEULA(name, repo):
            msger.warning('skip repo:%s for failed EULA confirmation' % name)
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
            raise CreatorError(str(e))

        msger.verbose('repo: %s was added' % name)
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
        msger.info("Checking packages cache and packages integrity ...")
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
        msger.info("%d packages to be installed, %d packages gotten from cache, %d packages to be downloaded" % (total_count, cached_count, download_count))
        try:
            if download_count > 0:
                msger.info("Downloading packages ...")
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
        shutil.rmtree(self.creator.cachedir + "/etc", ignore_errors = True)

        zypp.KeyRing.setDefaultAccept( zypp.KeyRing.ACCEPT_UNSIGNED_FILE
                                     | zypp.KeyRing.ACCEPT_VERIFICATION_FAILED
                                     | zypp.KeyRing.ACCEPT_UNKNOWNKEY
                                     | zypp.KeyRing.TRUST_KEY_TEMPORARILY
                                     )
        self.repo_manager_options = zypp.RepoManagerOptions(zypp.Pathname(self.creator._instroot))
        self.repo_manager_options.knownReposPath = zypp.Pathname(self.creator.cachedir + "/etc/zypp/repos.d")
        self.repo_manager_options.repoCachePath = zypp.Pathname(self.creator.cachedir)
        self.repo_manager_options.repoRawCachePath = zypp.Pathname(self.creator.cachedir + "/raw")
        self.repo_manager_options.repoSolvCachePath = zypp.Pathname(self.creator.cachedir + "/solv")
        self.repo_manager_options.repoPackagesCachePath = zypp.Pathname(self.creator.cachedir + "/packages")

        self.repo_manager = zypp.RepoManager(self.repo_manager_options)

    def __build_repo_cache(self, name):
        repo = self.repo_manager.getRepositoryInfo(name)
        if self.repo_manager.isCached( repo ) or not repo.enabled():
            return
        self.repo_manager.buildCache( repo, zypp.RepoManager.BuildIfNeeded )

    def __initialize_zypp(self):
        if self.Z:
            return

        zconfig = zypp.ZConfig_instance()

        """ Set system architecture """
        if self.creator.target_arch and self.creator.target_arch.startswith("arm"):
            arches = ["armv7l", "armv7nhl", "armv7hl", "armv5tel"]
            if self.creator.target_arch not in arches:
                raise CreatorError("Invalid architecture: %s" % self.creator.target_arch)
            arch_map = {}
            if self.creator.target_arch == "armv7l":
                arch_map["armv7l"] = zypp.Arch_armv7l()
            elif self.creator.target_arch == "armv7nhl":
                arch_map["armv7nhl"] = zypp.Arch_armv7nhl()
            elif self.creator.target_arch == "armv7hl":
                arch_map["armv7hl"] = zypp.Arch_armv7hl()
            elif self.creator.target_arch == "armv5tel":
                arch_map["armv5tel"] = zypp.Arch_armv5tel()
            zconfig.setSystemArchitecture(arch_map[self.creator.target_arch])

        msger.info("zypp architecture is <%s>" % zconfig.systemArchitecture())

        """ repoPackagesCachePath is corrected by this """
        self.repo_manager = zypp.RepoManager(self.repo_manager_options)
        repos = self.repo_manager.knownRepositories()
        for repo in repos:
            if not repo.enabled():
                continue
            self.repo_manager.loadFromCache( repo );

        self.Z = zypp.ZYppFactory_instance().getZYpp()
        self.Z.initializeTarget( zypp.Pathname(self.creator._instroot) )
        self.Z.target().load();


    def buildTransaction(self):
        if not self.Z.resolver().resolvePool():
            msger.warning("Problem count: %d" % len(self.Z.resolver().problems()))
            for problem in self.Z.resolver().problems():
                msger.warning("Problem: %s, %s" % (problem.description().decode("utf-8"), problem.details().decode("utf-8")))

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
        h = rpmmisc.readRpmHeader(self.ts, pkgpath)
        return h["name"]

    def downloadPkgs(self, package_objects, count):
        localpkgs = self.localpkgs.keys()
        progress_obj = fs.TextProgress(count)
        for po in package_objects:
            if po.name() in localpkgs:
                continue
            filename = self.getLocalPkgPath(po)
            if os.path.exists(filename):
                if self.checkPkg(filename) == 0:
                    continue
            dirn = os.path.dirname(filename)
            if not os.path.exists(dirn):
                os.makedirs(dirn)
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
                filename = fs.myurlgrab(url, filename, proxies, progress_obj)
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
            h = rpmmisc.readRpmHeader(self.ts, rpmpath)
            self.ts.addInstall(h, rpmpath, 'u')

        unresolved_dependencies = self.ts.check()
        if not unresolved_dependencies:
            self.ts.order()
            cb = rpmmisc.RPMInstallCallback(self.ts)
            self.ts.run(cb.callback, '')
            self.ts.closeDB()
            self.ts = None
        else:
            msger.warning(unresolved_dependencies)
            raise RepoError("Unresolved dependencies, transaction failed.")

    def __initialize_transaction(self):
        if not self.ts:
            self.ts = rpm.TransactionSet(self.creator._instroot)
            # Set to not verify DSA signatures.
            self.ts.setVSFlags(rpm._RPMVSF_NOSIGNATURES|rpm._RPMVSF_NODIGESTS)

    def checkPkg(self, pkg):
        ret = 1
        if not os.path.exists(pkg):
            return ret
        ret = rpmmisc.checkRpmIntegrity('rpm', pkg)
        if ret != 0:
            msger.warning("package %s is damaged: %s" % (os.path.basename(pkg), pkg))

        return ret

    def zypp_install(self):
        policy = zypp.ZYppCommitPolicy()
        policy.downloadMode(zypp.DownloadInAdvance)
        policy.dryRun( False )
        policy.syncPoolAfterCommit( False )
        result = self.Z.commit( policy )
        msger.info(result)

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
            return misc.get_proxy(repourl)
