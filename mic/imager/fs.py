#!/usr/bin/python -tt
#
# Copyright 2011 Intel, Inc.
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

import os, sys

from baseimager import BaseImageCreator
from mic import msger
from mic.utils import runner

class FsImageCreator(BaseImageCreator):
    def __init__(self, cfgmgr = None, pkgmgr = None):
        BaseImageCreator.__init__(self, cfgmgr, pkgmgr)
        self._fstype = None
        self._fsopts = None
        self._include_src = False

    def package(self, destdir = "."):
        fsdir = os.path.join(destdir, self.name)

        if self._recording_pkgs:
            self._save_recording_pkgs(destdir)

        msger.info("Copying %s to %s ..." % (self._instroot, fsdir))
        runner.show(['cp', "-af", self._instroot, fsdir])

        for exclude in ["/dev/fd", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/etc/mtab"]:
            if os.path.exists(fsdir + exclude):
                os.unlink(fsdir + exclude)

        self.outimage.append(fsdir)
