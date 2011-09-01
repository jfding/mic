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

import os
import shutil
import tempfile

from mic import configmgr, pluginmgr, chroot, msger
from mic.utils import misc, fs_related, errors
import mic.imager.loop as loop

from mic.pluginbase import ImagerPlugin
class LoopPlugin(ImagerPlugin):
    name = 'loop'

    @classmethod
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create loop image

        ${cmd_usage}
        ${cmd_option_list}
        """

        if not args:
            raise errors.Usage("More arguments needed")

        if len(args) == 1:
            ksconf = args[0]
        else:
            raise errors.Usage("Extra arguments given")

        cfgmgr = configmgr.getConfigMgr()
        creatoropts = cfgmgr.create
        cfgmgr.setProperty("ksconf", ksconf)

        # try to find the pkgmgr
        pkgmgr = None
        plgmgr = pluginmgr.PluginMgr()
        for (key, pcls) in plgmgr.get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        if not pkgmgr:
            raise errors.CreatorError("Can't find backend %s" % pkgmgr)

        creator = loop.LoopImageCreator(creatoropts, pkgmgr)
        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.unmount()
            creator.package(creatoropts["outdir"])
        except errors.CreatorError, e:
            raise errors.CreatorError("failed to create image : %s" % e)
        finally:
            creator.cleanup()

        msger.info("Finished.")
        return 0

    @classmethod
    def do_chroot(cls, target):#chroot.py parse opts&args
        img = target
        imgsize = misc.get_file_size(img)
        extmnt = misc.mkdtemp()
        extloop = fs_related.ExtDiskMount(fs_related.SparseLoopbackDisk(img, imgsize),
                                                         extmnt,
                                                         "ext3",
                                                         4096,
                                                         "ext3 label")
        try:
            extloop.mount()

        except errors.MountError, e:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors = True)
            raise errors.CreatorError("Failed to loopback mount '%s' : %s" %(img, e))

        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            raise errors.CreatorError("Failed to chroot to %s." %img)
        finally:
            chroot.cleanup_after_chroot("img", extloop, None, extmnt)

    @classmethod
    def do_unpack(cls, srcimg):
        image = os.path.join(tempfile.mkdtemp(dir = "/var/tmp", prefix = "tmp"), "target.img")
        msger.info("Copying file system ...")
        shutil.copyfile(srcimg, image)
        return image
