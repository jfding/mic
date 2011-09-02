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
import subprocess
import shutil
import tempfile

from mic import configmgr, pluginmgr, chroot, msger
from mic.utils import misc, fs_related, errors
from mic.utils.partitionedfs import PartitionedMount

import mic.imager.liveusb as liveusb

from mic.pluginbase import ImagerPlugin
class LiveUSBPlugin(ImagerPlugin):
    name = 'liveusb'

    @classmethod
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create liveusb image

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
        cfgmgr.setProperty("ksconf", args[0])

        if creatoropts['arch'].startswith('arm'):
            msger.warning('liveusb cannot support arm images, Quit')
            return

        # try to find the pkgmgr
        pkgmgr = None
        plgmgr = pluginmgr.PluginMgr()
        for (key, pcls) in plgmgr.get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        creator = liveusb.LiveUSBImageCreator(creatoropts, pkgmgr)
        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.unmount()
            creator.package(creatoropts["outdir"])
            outimage = creator.outimage
            creator.print_outimage_info()
            outimage = creator.outimage

        except errors.CreatorError, e:
            raise
        finally:
            creator.cleanup()

        msger.info("Finished.")
        return 0

    @classmethod
    def do_chroot(cls, target):
        os_image = cls.do_unpack(target)
        os_image_dir = os.path.dirname(os_image)

        #unpack image to target dir
        imgsize = misc.get_file_size(os_image) * 1024L * 1024L
        extmnt = misc.mkdtemp()
        tfstype = "ext3"
        tlabel = "ext3 label"

        MyDiskMount = fs_related.ExtDiskMount
        extloop = MyDiskMount(fs_related.SparseLoopbackDisk(os_image, imgsize),
                              extmnt,
                              tfstype,
                              4096,
                              tlabel)
        try:
            extloop.mount()

        except errors.MountError, e:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors = True)
            raise errors.CreatorError("Failed to loopback mount '%s' : %s" %(os_image, e))

        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            raise errors.CreatorError("Failed to chroot to %s." %target)
        finally:
            chroot.cleanup_after_chroot("img", extloop, os_image_dir, extmnt)

    @classmethod
    def do_pack(cls, base_on):
        def __mkinitrd(instance):
            kernelver = instance._get_kernel_versions().values()[0][0]
            args = [ "/usr/libexec/mkliveinitrd", "/boot/initrd-%s.img" % kernelver, "%s" % kernelver ]
            try:
                subprocess.call(args, preexec_fn = instance._chroot)

            except OSError, (err, msg):
               raise errors.CreatorError("Failed to execute /usr/libexec/mkliveinitrd: %s" % msg)

        def __run_post_cleanups(instance):
            kernelver = instance._get_kernel_versions().values()[0][0]
            args = ["rm", "-f", "/boot/initrd-%s.img" % kernelver]

            try:
                subprocess.call(args, preexec_fn = instance._chroot)
            except OSError, (err, msg):
               raise errors.CreatorError("Failed to run post cleanups: %s" % msg)

        convertor = liveusb.LiveUSBImageCreator()
        srcimgsize = (misc.get_file_size(base_on)) * 1024L * 1024L
        convertor._set_fstype("ext3")
        convertor._set_image_size(srcimgsize)
        base_on_dir = os.path.dirname(base_on)
        convertor._LoopImageCreator__imgdir = base_on_dir
        convertor.mount()
        __mkinitrd(convertor)
        convertor._create_bootconfig()
        __run_post_cleanups(convertor)
        convertor.unmount()
        convertor.package()
        convertor.print_outimage_info()
        shutil.rmtree(base_on_dir, ignore_errors = True)

    @classmethod
    def do_unpack(cls, srcimg):
        img = srcimg
        imgsize = misc.get_file_size(img) * 1024L * 1024L
        imgmnt = misc.mkdtemp()
        disk = fs_related.SparseLoopbackDisk(img, imgsize)
        imgloop = PartitionedMount({'/dev/sdb':disk}, imgmnt, skipformat = True)
        imgloop.add_partition(imgsize/1024/1024, "/dev/sdb", "/", "vfat", boot=False)
        try:
            imgloop.mount()
        except errors.MountError, e:
            imgloop.cleanup()
            raise errors.CreatorError("Failed to loopback mount '%s' : %s" %(img, e))

        # legacy LiveOS filesystem layout support, remove for F9 or F10
        if os.path.exists(imgmnt + "/squashfs.img"):
            squashimg = imgmnt + "/squashfs.img"
        else:
            squashimg = imgmnt + "/LiveOS/squashfs.img"

        tmpoutdir = misc.mkdtemp()
        # unsquashfs requires outdir mustn't exist
        shutil.rmtree(tmpoutdir, ignore_errors = True)
        misc.uncompress_squashfs(squashimg, tmpoutdir)

        try:
            # legacy LiveOS filesystem layout support, remove for F9 or F10
            if os.path.exists(tmpoutdir + "/os.img"):
                os_image = tmpoutdir + "/os.img"
            else:
                os_image = tmpoutdir + "/LiveOS/ext3fs.img"

            if not os.path.exists(os_image):
                raise errors.CreatorError("'%s' is not a valid live CD ISO : neither "
                                          "LiveOS/ext3fs.img nor os.img exist" %img)
            rtimage = os.path.join(tempfile.mkdtemp(dir = "/var/tmp", prefix = "tmp"), "target.img")
            shutil.copyfile(os_image, rtimage)

        finally:
            imgloop.cleanup()
            shutil.rmtree(tmpoutdir, ignore_errors = True)
            shutil.rmtree(imgmnt, ignore_errors = True)

        return rtimage
