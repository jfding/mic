#!/usr/bin/python -tt
#
# Copyright (c) 2009, 2010, 2011 Intel, Inc.
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

from __future__ import with_statement
import os, sys
import pickle
import shutil
import subprocess
import rpm

from mic import msger
from mic import chroot
from mic.plugin import pluginmgr
from mic.utils import proxy
from mic.utils import misc
from mic.utils import errors

minibase_grps = [ "tizen-bootstrap" ]
minibase_pkgs = [ ]
required_pkgs = [ "syslinux", "syslinux-extlinux", "satsolver-tools",
                  "libzypp", "python-zypp", "qemu-arm-static", "mic" ]


def query_package_rpmdb(root='/', tag='name', pattern=None):
    name = pattern
    version = None
    ts = rpm.TransactionSet(root)
    mi = ts.dbMatch(tag, pattern)
    for hdr in mi:
        version = hdr['version']
    return (name, version)

def query_package_metadat(root='/', tag='name', pattern=None):
    name = pattern
    version = None
    try:
        with open(root + '/.metadata', 'r') as f:
            metadata = pickle.load(f)
        f.close()
    except:
        raise errors.BootstrapError("Load %s/.metadata error" % root)
    else:
        for pkg in metadata.keys():
            m = misc.RPM_RE.match(pkg)
            if m:
                (n, a, v, r) = m.groups()
            else:
                raise errors.BootstrapError("Wrong Format .metadata in %s"
                                            % root)
            if n == pattern:
                version = v
    return (name, version)

class Bootstrap(object):
    def __init__(self, homedir='/var/mic/bootstrap', **kwargs):
        self._pkgmgr = None
        self._rootdir = None
        self._bootstraps = []
        self.homedir = homedir

        if not os.path.exists(self.homedir):
            os.makedirs(self.homedir)

        self.__dict__.update(**kwargs)

    def _setRootdir(self, name):
        self._rootdir = os.path.join(self.homedir, name)

    def _getRootdir(self):
        if not os.path.exists(self._rootdir):
            raise errors.BootstrapError("dir: %s not exist" % self._rootdir)
        return self._rootdir

    rootdir = property(fget = lambda self: self._getRootdir(),
                       fset = lambda self, name: self._setRootdir(name),
                       doc = 'root directory')

    def _setPkgmgr(self, name):
        backend_plugins = pluginmgr.get_plugins('backend')
        for (key, cls) in backend_plugins.iteritems():
            if key == name:
                self._pkgmgr = cls
        if not self._pkgmgr:
            raise errors.BootstrapError("Backend: %s can't be loaded correctly"\
                                        % name)

    pkgmgr = property(fget = lambda self: self._pkgmgr,
                      fset = lambda self, name: self._setPkgmgr(name),
                      doc = 'package manager')

    @property
    def bootstraps(self):
        if self._bootstraps:
            return self._bootstraps
        for dir in os.listdir(self.homedir):
            metadata_fp = os.path.join(self.homedir, dir, '.metadata')
            if os.path.exists(metadata_fp) \
                and 0 != os.path.getsize(metadata_fp):
                self._bootstraps.append(dir)
        return self._bootstraps

    def run(self, name, cmd, chdir='/', bindmounts=None):
        self.rootdir = name
        def mychroot():
            os.chroot(self.rootdir)
            os.chdir(chdir)

        if isinstance(cmd, list):
            cmd = ' '.join(cmd)

        lvl = msger.get_loglevel()
        msger.set_loglevel('quiet')
        globalmounts = chroot.setup_chrootenv(self.rootdir, bindmounts)
        try:
            proxy.set_proxy_environ()
            subprocess.call(cmd, preexec_fn=mychroot, shell=True)
            proxy.unset_proxy_environ()
        except:
            raise errors.BootstrapError("Run in bootstrap fail")
        finally:
            chroot.cleanup_chrootenv(self.rootdir, bindmounts, globalmounts)

        msger.set_loglevel(lvl)

    def list(self, **kwargs):
        bslist = []
        for binst in self.bootstraps:
            (mver, kver, rver) = self.status(binst)
            bsinfo = {'name':binst, 'meego':mver, 'kernel':kver, 'rpm': rver}
            bslist.append(bsinfo)

        return bslist

    def status(self, name):
        self.rootdir = name
        if os.path.exists(self.rootdir + '/.metadata'):
            query_package = query_package_metadat
        else:
            query_package = query_package_rpmdb

        name, mver = query_package(self.rootdir, 'name', 'meego-release')
        msger.debug("MeeGo Release: %s" % mver)

        name, kver = query_package(self.rootdir, 'name', 'kernel')
        msger.debug("Kernel Version: %s" % kver)

        name, rver = query_package(self.rootdir, 'name', 'rpm')
        msger.debug("RPM Version: %s" % rver)

        return (mver, kver, rver)

    def create(self, name, repolist, **kwargs):
        self.name = name
        self.pkgmgr = 'zypp'
        self.arch = 'i686'
        self.rootdir = name
        self.cachedir = '/var/tmp/mic/cache' # TBD from conf, do NOT hardcode

        if 'arch' in kwargs:
            self.arch = kwargs['arch']
        if 'cachedir' in kwargs:
            self.cachedir = kwargs['cachedir']

        if os.path.exists(self._rootdir):
            metadata_fp = os.path.join(self._rootdir, '.metadata')
            if os.path.exists(metadata_fp) and \
               0 != os.path.getsize(metadata_fp):
                msger.warning("bootstrap already exists") # TBD more details
                return
            else:
                shutil.rmtree(self._rootdir)

        if not os.path.exists(self._rootdir):
            os.makedirs(self._rootdir)

        pkg_manager = self.pkgmgr(self.arch, self.rootdir, self.cachedir)
        pkg_manager.setup()

        for repo in repolist:
            if 'proxy' in repo:
                pkg_manager.addRepository(repo['name'], repo['baseurl'],
                                          proxy=repo['proxy'])
            else:
                pkg_manager.addRepository(repo['name'], repo['baseurl'])

        rpm.addMacro("_dbpath", "/var/lib/rpm")
        rpm.addMacro("__file_context_path", "%{nil}")

        for grp in minibase_grps:
            pkg_manager.selectGroup(grp)
        for pkg in minibase_pkgs:
            pkg_manager.selectPackage(pkg)
        for pkg in required_pkgs:
            pkg_manager.selectPackage(pkg)

        try:
            pkg_manager.runInstall(512 * 1024L * 1024L)
        except:
            raise errors.BootstrapError("Create bootstrap fail")
        else:
            metadata = pkg_manager.getAllContent()
            metadata_fp = os.path.join(self.rootdir, '.metadata')
            with open(metadata_fp, 'w') as f:
                pickle.dump(metadata, f)
            f.close()
        finally:
            pkg_manager.closeRpmDB()
            pkg_manager.close()

        # Copy bootstrap repo files
        srcdir = "%s/etc/zypp/repos.d/" % self.cachedir
        destdir= "%s/etc/zypp/repos.d/" % os.path.abspath(self.rootdir)
        shutil.rmtree(destdir, ignore_errors = True)
        shutil.copytree(srcdir, destdir)
        # create '/tmp' in chroot
        _tmpdir = os.path.join(os.path.abspath(self.rootdir), "tmp")
        if not os.path.exists(_tmpdir):
            os.makedirs(_tmpdir)

        msger.info("Bootstrap created.")

    def rebuild(self):
        pass

    def update(self, name):
        self.rootdir = name
        chrootdir = self.rootdir

        def mychroot():
            os.chroot(chrootdir)

        shutil.copyfile("/etc/resolv.conf", chrootdir + "/etc/resolv.conf")
        try:
            subprocess.call("zypper -n --no-gpg-checks update",
                            preexec_fn=mychroot, shell=True)
        except OSError, err:
            raise errors.BootstrapError("Bootstrap: %s update failed" %\
                                        chrootdir)

    def cleanup(self, name):
        self.rootdir = name
        try:
            chroot.cleanup_mounts(self.rootdir)
            shutil.rmtree(self.rootdir, ignore_errors=True)
        except:
            raise errors.BootstrapError("Bootstrap: %s clean up failed" %\
                                        self.rootdir)
