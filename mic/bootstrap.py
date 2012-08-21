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
import os
import sys
import tempfile
import shutil
import subprocess
import rpm
from mic import msger
from mic.utils import errors, proxy, misc
from mic.utils.rpmmisc import readRpmHeader, RPMInstallCallback
from mic.chroot import cleanup_mounts, setup_chrootenv, cleanup_chrootenv

RPMTRANS_FLAGS = [
                   rpm.RPMTRANS_FLAG_ALLFILES,
                   rpm.RPMTRANS_FLAG_NOSCRIPTS,
                   rpm.RPMTRANS_FLAG_NOTRIGGERS,
                 ]

RPMVSF_FLAGS = [
                 rpm._RPMVSF_NOSIGNATURES,
                 rpm._RPMVSF_NODIGESTS
               ]

class MiniBackend(object):
    def __init__(self, rootdir, arch=None, repomd=None):
        self._ts = None
        self.rootdir = os.path.abspath(rootdir)
        self.arch = arch
        self.repomd = repomd
        self.dlpkgs = []
        self.localpkgs = {}
        self.preins = {}
        self.postins = {}

    def __del__(self):
        try:
            del self.ts
        except:
            pass

    def get_ts(self):
        if not self._ts:
            self._ts = rpm.TransactionSet(self.rootdir)
            self._ts.setFlags(reduce(lambda x, y: x|y, RPMTRANS_FLAGS))
            self._ts.setVSFlags(reduce(lambda x, y: x|y, RPMVSF_FLAGS))
        return self._ts

    def del_ts(self):
        if self._ts:
            self._ts.closeDB()
            self._ts = None

    ts = property(fget = lambda self: self.get_ts(),
                  fdel = lambda self: self.del_ts(),
                  doc="TransactionSet object")

    def selectPackage(self, pkg):
        if not pkg in self.dlpkgs:
            self.dlpkgs.append(pkg)

    def runInstall(self):
        # FIXME: check space
        self.downloadPkgs()
        self.installPkgs()

        for pkg in self.preins.keys():
            prog, script = self.preins[pkg]
            self.run_pkg_script(pkg, prog, script, '0')
        for pkg in self.postins.keys():
            prog, script = self.postins[pkg]
            self.run_pkg_script(pkg, prog, script, '1')

    def downloadPkgs(self):
        nonexist = []
        for pkg in self.dlpkgs:
            try:
                localpth = misc.get_package(pkg, self.repomd, self.arch)
                if not localpth:
                    # skip non-existent rpm
                    nonexist.append(pkg)
                    continue
                self.localpkgs[pkg] = localpth
            except:
                raise

        if nonexist:
            msger.warning("\ncan't get rpm binary: %s" % ','.join(nonexist))

    def installPkgs(self):
        for pkg in self.localpkgs.keys():
            rpmpath = self.localpkgs[pkg]

            hdr = readRpmHeader(self.ts, rpmpath)

            # save prein and postin scripts
            self.preins[pkg] = (hdr['PREINPROG'], hdr['PREIN'])
            self.postins[pkg] = (hdr['POSTINPROG'], hdr['POSTIN'])

            # mark pkg as install
            self.ts.addInstall(hdr, rpmpath, 'u')

        # run transaction
        self.ts.order()
        cb = RPMInstallCallback(self.ts)
        self.ts.run(cb.callback, '')

    def run_pkg_script(self, pkg, prog, script, arg):
        mychroot = lambda: os.chroot(self.rootdir)

        if not script:
            return

        if prog == "<lua>":
             prog = "/usr/bin/lua"

        tmpdir = os.path.join(self.rootdir, "tmp")
        if not os.path.exists(tmpdir):
            os.makedirs(tmpdir)
        tmpfd, tmpfp = tempfile.mkstemp(dir=tmpdir, prefix="%s.pre-" % pkg)
        script = script.replace('\r', '')
        os.write(tmpfd, script)
        os.close(tmpfd)
        os.chmod(tmpfp, 0700)

        try:
            script_fp = os.path.join('/tmp', os.path.basename(tmpfp))
            subprocess.call([prog, script_fp, arg], preexec_fn=mychroot)
        except (OSError, IOError), err:
            msger.warning(str(err))
        finally:
            os.unlink(tmpfp)

class Bootstrap(object):
    def __init__(self, rootdir, distro, arch=None):
        self.rootdir = rootdir
        self.distro = distro
        self.arch = arch
        self.pkgslist = []
        self.repomd = None

    def __del__(self):
        self.cleanup()

    def get_rootdir(self):
        if os.path.exists(self.rootdir):
            shutil.rmtree(self.rootdir, ignore_errors=True)
        os.makedirs(self.rootdir)
        return self.rootdir

    def _path(self, pth):
        return os.path.join(self.rootdir, pth.lstrip('/'))

    def create(self, repomd, pkglist):
        try:
            pkgmgr = MiniBackend(self.get_rootdir())
            pkgmgr.arch = self.arch
            pkgmgr.repomd = repomd
            map(pkgmgr.selectPackage, pkglist)
            pkgmgr.runInstall()

            # make /tmp path
            tmpdir = self._path('/tmp')
            if not os.path.exists(tmpdir):
                os.makedirs(tmpdir)

            # touch distro file
            tzdist = self._path('/etc/%s-release' % self.distro)
            if not os.path.exists(tzdist):
                with open(tzdist, 'w') as wf:
                    wf.write("bootstrap")

        except (OSError, IOError, errors.CreatorError), err:
            raise errors.BootstrapError("%s" % err)

    def run(self, cmd, chdir, bindmounts=None):
        def mychroot():
            os.chroot(self.rootdir)
            os.chdir(chdir)

        if isinstance(cmd, list):
            shell = False
        else:
            shell = True

        gloablmounts = None
        try:
            proxy.set_proxy_environ()
            gloablmounts = setup_chrootenv(self.rootdir, bindmounts)
            subprocess.call(cmd, preexec_fn = mychroot, shell=shell)
        except (OSError, IOError), err:
            raise RuntimeError(err)
        finally:
            cleanup_chrootenv(self.rootdir, bindmounts, gloablmounts)
            proxy.unset_proxy_environ()

    def cleanup(self):
        try:
            # clean mounts
            cleanup_mounts(self.rootdir)
            # remove rootdir
            shutil.rmtree(self.rootdir, ignore_errors=True)
        except:
            pass
