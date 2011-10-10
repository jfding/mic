#!/usr/bin/python -tt
#
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

import os
import shutil
import urlparse
import rpm

import zypp
if not hasattr(zypp, 'PoolQuery'):
    raise ImportError("python-zypp in host system cannot support PoolQuery interface, please "
                      "update it to enhanced version which can be found in repo.meego.com/tools")

from mic import msger
from mic.kickstart import ksparser
from mic.utils import rpmmisc, fs_related as fs
from mic.utils.proxy import get_proxy_for
from mic.utils.errors import CreatorError
from mic.imager.baseimager import BaseImageCreator

class RepositoryStub:
    def __init__(self):
        self.name = None
        self.baseurl = []
        self.mirrorlist = None
        self.proxy = None
        self.proxy_username = None
        self.proxy_password = None

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
        self.to_deselect = []
        self.localpkgs = {}
        self.repo_manager = None
        self.repo_manager_options = None
        self.Z = None
        self.ts = None
        self.probFilterFlags = []
        self.incpkgs = {}
        self.excpkgs = {}

        self.has_prov_query = True

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

    def whatObsolete(self, pkg):
        query = zypp.PoolQuery()
        query.addKind(zypp.ResKind.package)
        query.addAttribute(zypp.SolvAttr.obsoletes, pkg)
        query.setMatchExact()
        for pi in query.queryResults(self.Z.pool()):
            return pi
        return None

    def selectPackage(self, pkg):
        """ Select a given package or package pattern, can be specified with name.arch or name* or *name """
        if not self.Z:
            self.__initialize_zypp()

        def markPoolItem(obs, pi):
            if obs == None:
                pi.status().setToBeInstalled (zypp.ResStatus.USER)
            else:
                obs.status().setToBeInstalled (zypp.ResStatus.USER)
                
        found = False
        startx = pkg.startswith("*")
        endx = pkg.endswith("*")
        ispattern = startx or endx
        sp = pkg.rsplit(".", 1)

        q = zypp.PoolQuery()
        q.addKind(zypp.ResKind.package)
        if ispattern:
            if startx and not endx:
                pattern = '%s$' % (pkg[1:])
            if endx and not startx:
                pattern = '^%s' % (pkg[0:-1])
            if endx and startx:
                pattern = '%s' % (pkg[1:-1])
            q.setMatchRegex()
            q.addAttribute(zypp.SolvAttr.name,pattern)
        elif len(sp) == 2:
            q.setMatchExact()
            q.addAttribute(zypp.SolvAttr.name,sp[0])
        else:
            q.setMatchExact()
            q.addAttribute(zypp.SolvAttr.name,pkg)

        for item in q.queryResults(self.Z.pool()):
            if item.name() in self.excpkgs.keys() and self.excpkgs[item.name()] == item.repoInfo().name():
                continue
            if item.name() in self.incpkgs.keys() and self.incpkgs[item.name()] != item.repoInfo().name():
                continue
            found = True
            obspkg = self.whatObsolete(item.name())
            if len(sp) == 2:
                if item.arch() == sp[1]:
                    item.status().setToBeInstalled (zypp.ResStatus.USER)
            else:
                markPoolItem(obspkg, item)
            if len(sp) == 1 and not ispattern:
                break
        # Can't match using package name, then search from packge provides infomation
        if found == False and not ispattern:
            q.addAttribute(zypp.SolvAttr.provides, pkg)
            q.addAttribute(zypp.SolvAttr.name,'')
            for item in q.queryResults(self.Z.pool()):
                if item.name() in self.excpkgs.keys() and self.excpkgs[item.name()] == item.repoInfo().name():
                    continue
                if item.name() in self.incpkgs.keys() and self.incpkgs[item.name()] != item.repoInfo().name():
                    continue
                found = True
                obspkg = self.whatObsolete(item.name())
                markPoolItem(obspkg, item)
                break
        if found:
            return None
        else:
            raise CreatorError("Unable to find package: %s" % (pkg,))
    def inDeselectPackages(self, name):
        """check if specified pacakges are in the list of inDeselectPackages"""
        for pkg in self.to_deselect:
            startx = pkg.startswith("*")
            endx = pkg.endswith("*")
            ispattern = startx or endx
            sp = pkg.rsplit(".", 2)
            if not ispattern:
                if len(sp) == 2:
                    arch = "%s" % item.arch()
                    if name == sp[0] and arch == sp[1]:
                        return True;
                else:
                    if name == sp[0]:
                        return True;
            else:
                if startx and name.endswith(sp[0][1:]):
                        return True;
                if endx and name.startswith(sp[0][:-1]):
                        return True;
        return False;

    def deselectPackage(self, pkg):
        """collect packages should not be installed"""
        self.to_deselect.append(pkg)

    def selectGroup(self, grp, include = ksparser.GROUP_DEFAULT):
        if not self.Z:
            self.__initialize_zypp()
        found = False
        q=zypp.PoolQuery()
        q.addKind(zypp.ResKind.pattern)
        for item in q.queryResults(self.Z.pool()):
            summary = "%s" % item.summary()
            name = "%s" % item.name()
            if name == grp or summary == grp:
                found = True
                item.status().setToBeInstalled (zypp.ResStatus.USER)
                break

        if found:
            if include == ksparser.GROUP_REQUIRED:
                map(lambda p: self.deselectPackage(p), grp.default_packages.keys())
            return None
        else:
            raise CreatorError("Unable to find pattern: %s" % (grp,))

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
        if inc:
            for pkg in inc:
                self.incpkgs[pkg] = name
        if exc:
            for pkg in exc:
                self.excpkgs[pkg] = name

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
            repo_info.setAlias(repo.name)
            repo_info.setName(repo.name)
            repo_info.setEnabled(repo.enabled)
            repo_info.setAutorefresh(repo.autorefresh)
            repo_info.setKeepPackages(repo.keeppackages)
            baseurl = zypp.Url(repo.baseurl[0])
            if proxy:
                (scheme, host, path, parm, query, frag) = urlparse.urlparse(proxy)
                proxyinfo = host.split(":")
                baseurl.setQueryParam ("proxy", proxyinfo[0])
                port = "80"
                if len(proxyinfo) > 1:
                    port = proxyinfo[1]
                baseurl.setQueryParam ("proxyport", port)
            repo_info.addBaseUrl(baseurl)
            self.repo_manager.addRepository(repo_info)
            self.__build_repo_cache(name)
        except RuntimeError, e:
            raise CreatorError(str(e))

        msger.verbose('repo: %s was added' % name)
        return repo

    def installHasFile(self, file):
        return False

    def runInstall(self, checksize = 0):
        os.environ["HOME"] = "/"
        self.buildTransaction()

        todo = zypp.GetResolvablesToInsDel(self.Z.pool())
        installed_pkgs = todo._toInstall
        dlpkgs = []
        for item in installed_pkgs:
            if not zypp.isKindPattern(item) and not self.inDeselectPackages(item.name()):
                dlpkgs.append(item)

        # record the total size of installed pkgs
        pkgs_total_size = sum(map(lambda x: int(x.installSize()), dlpkgs))

        # check needed size before actually download and install
        if checksize and pkgs_total_size > checksize:
            raise CreatorError("Size of specified root partition in kickstart file is too small to install all selected packages.")

        if self.__recording_pkgs:
            # record all pkg and the content
            localpkgs = self.localpkgs.keys()
            for pkg in dlpkgs:
                if pkg.name() in localpkgs:
                    hdr = rpmmisc.readRpmHeader(self.ts, self.localpkgs[pkg.name()])
                    pkg_long_name = "%s-%s-%s.%s.rpm" % (hdr['name'], hdr['version'], hdr['release'], hdr['arch'])
                else:
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
        shutil.rmtree(self.creator.cachedir + "/solv", ignore_errors = True)
        shutil.rmtree(self.creator.cachedir + "/raw", ignore_errors = True)

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
        if self.repo_manager.isCached(repo) or not repo.enabled():
            return
        self.repo_manager.buildCache(repo, zypp.RepoManager.BuildIfNeeded)

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
            try:
                arch_map[self.creator.target_arch] = zypp.Arch(self.creator.target_arch)
            except AttributeError:
                msger.error('libzypp/python-zypp in host system cannot support arch %s, please'
                            ' update it to enhanced version which can be found in repo.meego.com/tools'\
                            % self.creator.target_arch)

            zconfig.setSystemArchitecture(arch_map[self.creator.target_arch])

        msger.info("zypp architecture is <%s>" % zconfig.systemArchitecture())

        """ repoPackagesCachePath is corrected by this """
        self.repo_manager = zypp.RepoManager(self.repo_manager_options)
        repos = self.repo_manager.knownRepositories()
        for repo in repos:
            if not repo.enabled():
                continue
            self.repo_manager.loadFromCache(repo)

        self.Z = zypp.ZYppFactory_instance().getZYpp()
        self.Z.initializeTarget(zypp.Pathname(self.creator._instroot))
        self.Z.target().load()


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
        hdr = rpmmisc.readRpmHeader(self.ts, pkg)
        arch = zypp.Arch(hdr['arch'])
        if self.creator.target_arch == None:
            # TODO, get the default_arch from conf or detected from global settings
            sysarch = zypp.Arch('i686')
        else:
            sysarch = zypp.Arch(self.creator.target_arch)
        if arch.compatible_with (sysarch):
            pkgname = hdr['name']
            self.localpkgs[pkgname] = pkg
            self.selectPackage(pkgname)
            msger.info("Marking %s to be installed" % (pkg))
        else:
            msger.warning ("Cannot add package %s to transaction. Not a compatible architecture: %s" % (pkg, hdr['arch']))

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
            index = baseurl.find("?")
            if index > -1:
                baseurl = baseurl[:index]
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
            except CreatorError:
                self.close()
                raise

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
            errors = self.ts.run(cb.callback, '')
            if errors is None:
                pass
            elif len(errors) == 0:
                msger.warning('scriptlet or other non-fatal errors occurred during transaction.')
            else:
                for e in errors:
                    msger.warning(e[0])
                msger.error('Could not run transaction.')
             
            self.ts.closeDB()
            self.ts = None
        else:
            for pkg, need, needflags, sense, key in unresolved_dependencies:
                package = '-'.join(pkg)
                if needflags == rpm.RPMSENSE_LESS:
                    deppkg = ' < '.join(need)
                elif needflags == rpm.RPMSENSE_EQUAL:
                    deppkg = ' = '.join(need)
                elif needflags == rpm.RPMSENSE_GREATER:
                    deppkg = ' > '.join(need)
                else:
                    deppkg = '-'.join(need)

                if sense == rpm.RPMDEP_SENSE_REQUIRES:
                    msger.warning ("[%s] Requires [%s], which is not provided" % (package, deppkg))
                elif sense == rpm.RPMDEP_SENSE_CONFLICTS:
                    msger.warning ("[%s] Conflicts with [%s]" % (package, deppkg))

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
            return get_proxy_for(repourl)
