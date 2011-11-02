#!/usr/bin/python -tt
#
# Copyright (c) 2011 Intel, Inc.
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
        if not os.path.exists(destdir):
            os.makedirs(destdir)
        fsdir = os.path.join(destdir, self.name)

        if self._recording_pkgs:
            self._save_recording_pkgs(destdir)

        msger.info("Copying %s to %s ..." % (self._instroot, fsdir))
        runner.show(['cp', "-af", self._instroot, fsdir])

        for exclude in ["/dev/fd", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/etc/mtab"]:
            if os.path.exists(fsdir + exclude):
                os.unlink(fsdir + exclude)

        self.outimage.append(fsdir)
