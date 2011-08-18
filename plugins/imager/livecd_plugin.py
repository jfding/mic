#!/usr/bin/python
import os.path
import sys
import subprocess
import logging
import shutil
import tempfile

from mic.pluginbase.imager_plugin import ImagerPlugin
import mic.chroot as chroot
import mic.utils.misc as misc
import mic.utils.fs_related as fs_related
import mic.utils.cmdln as cmdln
import mic.configmgr as configmgr
import mic.pluginmgr as pluginmgr
import mic.imager.livecd as livecd
from mic.utils.errors import *

class LiveCDPlugin(ImagerPlugin):

    @classmethod
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create livecd image

        ${cmd_usage}
        ${cmd_option_list}
        """
        if len(args) == 0:
            return
        if len(args) == 1:
            ksconf = args[0]
        else:
            raise errors.Usage("Extra arguments given")

        cfgmgr = configmgr.getConfigMgr()
        cfgmgr.setProperty("ksconf", ksconf)
        creatoropts = cfgmgr.create
        plgmgr = pluginmgr.PluginMgr()
        plgmgr.loadPlugins()

        for (key, pcls) in plgmgr.getBackendPlugins():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls

        if not pkgmgr:
            raise CreatorError("Can't find backend %s" % pkgmgr)

        creator = livecd.LiveCDImageCreator(creatoropts, pkgmgr)
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
        except CreatorError, e:
            raise CreatorError("failed to create image : %s" % e)
        finally:
            creator.cleanup()
#        if not creatoropts["image_info"]:
            print "Finished."
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
        #if misc.fstype_is_btrfs(os_image):
        #    tfstype = "btrfs"
        #    tlabel = "btrfs label"
        #    MyDiskMount = fs_related.BtrfsDiskMount
        extloop = MyDiskMount(fs_related.SparseLoopbackDisk(os_image, imgsize),
                                              extmnt,
                                              tfstype,
                                                                                                                           4096,
                                              tlabel)
        try:
            extloop.mount()
        except MountError, e:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors = True)
            shutil.rmtree(os_image_dir, ignore_errors = True)
            raise CreatorError("Failed to loopback mount '%s' : %s" %(os_image, e))
        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            raise CreatorError("Failed to chroot to %s." %target)
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
               raise CreatorError("Failed to execute /usr/libexec/mkliveinitrd: %s" % msg)

        def __run_post_cleanups(instance):
            kernelver = instance._get_kernel_versions().values()[0][0]
            args = ["rm", "-f", "/boot/initrd-%s.img" % kernelver]
            try:
                subprocess.call(args, preexec_fn = instance._chroot)
            except OSError, (err, msg):
               raise CreatorError("Failed to run post cleanups: %s" % msg)
        convertor = livecd.LiveCDImageCreator()
        srcimgsize = (misc.get_file_size(base_on)) * 1024L * 1024L
        base_on_dir = os.path.dirname(base_on)
        convertor._LoopImageCreator__imgdir = base_on_dir
        convertor._set_fstype("ext3")
        convertor._set_image_size(srcimgsize)
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
        imgmnt = misc.mkdtemp()
        imgloop = fs_related.DiskMount(fs_related.LoopbackDisk(img, 0), imgmnt)
        try:
            imgloop.mount()
        except MountError, e:
            imgloop.cleanup()
            raise CreatorError("Failed to loopback mount '%s' : %s" %(img, e))

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
                raise CreatorError("'%s' is not a valid live CD ISO : neither "
                                    "LiveOS/ext3fs.img nor os.img exist" %img)

            rtimage = os.path.join(tempfile.mkdtemp(dir = "/var/tmp", prefix = "tmp"), "meego.img")
            shutil.copyfile(os_image, rtimage)
        finally:
            imgloop.cleanup()
            shutil.rmtree(tmpoutdir, ignore_errors = True)
            shutil.rmtree(imgmnt, ignore_errors = True)

        return rtimage

mic_plugin = ["livecd", LiveCDPlugin]
