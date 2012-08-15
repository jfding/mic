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
import shutil
import rpm
from mic.utils import errors, runner
from mic.utils.misc import get_package
from mic.utils.rpmmisc import readRpmHeader, RPMInstallCallback

RPMTRANS_FLAGS = [rpm.RPMTRANS_FLAG_ALLFILES,
                  rpm.RPMTRANS_FLAG_NOSCRIPTS,
                  rpm.RPMTRANS_FLAG_NOTRIGGERS,
                  rpm.RPMTRANS_FLAG_NODOCS]

RPMVSF_FLAGS = [rpm._RPMVSF_NOSIGNATURES,
                rpm._RPMVSF_NODIGESTS]

class MiniBackend(object):
    def __init__(self, rootdir, repomd=None):
        self._ts = None
        self.rootdir = os.path.abspath(rootdir)
        self.repomd = repomd
        self.dlpkgs = []
        self.localpkgs = {}

    def __del__(self):
        if not os.path.exists('/etc/fedora-release') and \
           not os.path.exists('/etc/meego-release'):
            for i in range(3, os.sysconf("SC_OPEN_MAX")):
                try:
                    os.close(i)
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
            self.ts = None

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

    def downloadPkgs(self):
        for pkg in self.dlpkgs:
            try:
                localpth = get_package(pkg, self.repomd, None)
                self.localpkgs[pkg] = localpth
            except:
                raise

    def installPkgs(self):
        for pkg in self.localpkgs.keys():
            rpmpath = self.localpkgs[pkg]
            hdr = readRpmHeader(self.ts, rpmpath)

            # save prein and postin scripts

            # mark pkg as install
            self.ts.addInstall(hdr, rpmpath, 'u')

        # run transaction
        self.ts.order()
        cb = RPMInstallCallback(self.ts)
        self.ts.run(cb.callback, '')

class Bootstrap(object):
    def __init__(self, rootdir):
        self.rootdir = rootdir
        self.pkgslist = []
        self.repomd = None

    def __del__(self):
        self.cleanup()

    def get_rootdir(self):
        if os.path.exists(self.rootdir):
            shutil.rmtree(self.rootdir, ignore_errors=True)
        os.makedirs(self.rootdir)
        return self.rootdir

    def create(self, repomd, pkglist):
        try:
            pkgmgr = MiniBackend(self.get_rootdir())
            pkgmgr.repomd = repomd
            map(pkgmgr.selectPackage, pkglist)
            pkgmgr.runInstall()

            # make /tmp path
            tmpdir = os.path.join(self.rootdir, 'tmp')
            if not os.path.exists(tmpdir):
                os.makedirs(tmpdir)
        except:
            raise errors.BootstrapError("Failed to create bootstrap")

    def cleanup(self):
        try:
            # remove rootdir
            shutil.rmtree(self.rootdir, ignore_errors=True)
        except:
            pass
