#
# creator.py : ImageCreator and LoopImageCreator base classes
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

import os
import os.path
import stat
import sys
import tempfile
import shutil
import logging
import subprocess
import re
import tarfile
import glob

import rpm

from mic.utils.errors import *
from mic.utils.fs_related import *
from mic.utils.rpmmisc import *
from mic.utils.misc import *
from mic import kickstart
from baseimager import BaseImageCreator


class FsImageCreator(BaseImageCreator):
    def __init__(self, cfgmgr = None, pkgmgr = None):
        BaseImageCreator.__init__(self, cfgmgr, pkgmgr)
        self._fstype = None
        self._fsopts = None

    def _stage_final_image(self):
        """ nothing to do"""
        pass

    def package(self, destdir = "."):
        self._stage_final_image()

        if not os.path.exists(destdir):
            makedirs(destdir)
        destdir = os.path.abspath(os.path.expanduser(destdir))
        if self._recording_pkgs:
            self._save_recording_pkgs(destdir)

        logging.info("Copying %s to %s, please be patient to wait" % (self._instroot, destdir + "/" + self.name))

        copycmd = find_binary_path("cp")
        args = [ copycmd, "-af", self._instroot, destdir + "/" + self.name ]
        subprocess.call(args)

        ignores = ["/dev/fd", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/etc/mtab"]
        for exclude in ignores:
            if os.path.exists(destdir + "/" + self.name + exclude):
                os.unlink(destdir + "/" + self.name + exclude)

        self.outimage.append(destdir + "/" + self.name)
