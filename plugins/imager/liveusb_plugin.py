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

import os
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

        if len(args) != 1:
            raise errors.Usage("Extra arguments given")

        cfgmgr = configmgr.getConfigMgr()
        creatoropts = cfgmgr.create
        ksconf = args[0]

        if not os.path.exists(ksconf):
            raise errors.CreatorError("Can't find the file: %s" % ksconf)

        if creatoropts['arch'] and creatoropts['arch'].startswith('arm'):
            msger.warning('liveusb cannot support arm images, Quit')
            return

        recording_pkgs = []
        if len(creatoropts['record_pkgs']) > 0:
            recording_pkgs = creatoropts['record_pkgs']
        if creatoropts['release'] is not None:
            if 'name' not in recording_pkgs:
                recording_pkgs.append('name')
            ksconf = misc.save_ksconf_file(ksconf, creatoropts['release'])
            name = os.path.splitext(os.path.basename(ksconf))[0]
            creatoropts['outdir'] = "%s/%s/images/%s/" % (creatoropts['outdir'], creatoropts['release'], name)
        cfgmgr._ksconf = ksconf

        # try to find the pkgmgr
        pkgmgr = None
        for (key, pcls) in pluginmgr.PluginMgr().get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        if not pkgmgr:
            pkgmgrs = pluginmgr.PluginMgr().get_plugins('backend').keys()
            raise errors.CreatorError("Can't find package manager: %s (availables: %s)" % (creatoropts['pkgmgr'], ', '.join(pkgmgrs)))

        creator = liveusb.LiveUSBImageCreator(creatoropts, pkgmgr)

        if len(recording_pkgs) > 0:
            creator._recording_pkgs = recording_pkgs

        destdir = os.path.abspath(os.path.expanduser(creatoropts["outdir"]))
        if creatoropts['release'] is not None:
            imagefile = "%s.img" % os.path.join(destdir, creator.name)
        else:
            imagefile = "%s.usbimg" % os.path.join(destdir, creator.name)

        if not os.path.exists(destdir):
            os.makedirs(destdir)
        elif os.path.exists(imagefile):
            if msger.ask('The target image: %s already exists, need to delete it?' % imagefile):
                os.unlink(imagefile)

        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.unmount()
            creator.package(creatoropts["outdir"])
            if creatoropts['release'] is not None:
                creator.release_output(ksconf, creatoropts['outdir'], creatoropts['release'])
            creator.print_outimage_info()

        except errors.CreatorError:
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

        except errors.MountError:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors = True)
            raise

        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            raise errors.CreatorError("Failed to chroot to %s." %target)
        finally:
            chroot.cleanup_after_chroot("img", extloop, os_image_dir, extmnt)

    @classmethod
    def do_pack(cls, base_on):
        import subprocess

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
        try:
            convertor.mount()
            __mkinitrd(convertor)
            convertor._create_bootconfig()
            __run_post_cleanups(convertor)
            convertor.unmount()
            convertor.package()
            convertor.print_outimage_info()
        finally:
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
        except errors.MountError:
            imgloop.cleanup()
            raise

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
