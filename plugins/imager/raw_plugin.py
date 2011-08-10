#!/usr/bin/python
import os.path
import sys
import subprocess
import logging
import shutil
import re

from micng.pluginbase.imager_plugin import ImagerPlugin
import micng.utils.misc as misc
import micng.utils.fs_related as fs_related
import micng.utils.cmdln as cmdln
from micng.utils.errors import *
from micng.utils.partitionedfs import PartitionedMount
import micng.configmgr as configmgr
import micng.pluginmgr as pluginmgr
import micng.imager.raw as raw
import micng.chroot as chroot

class RawPlugin(ImagerPlugin):

    @classmethod
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create fs image

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
        creatoropts = cfgmgr.create
        cfgmgr.setProperty("ksconf", ksconf)
        plgmgr = pluginmgr.PluginMgr()
        plgmgr.loadPlugins()
        
        for (key, pcls) in plgmgr.getBackendPlugins():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls

        if not pkgmgr:
            raise CreatorError("Can't find backend %s" % pkgmgr)

        creator = raw.RawImageCreator(creatoropts, pkgmgr)
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
            print "Finished."
        return 0
    
    @classmethod    
    def do_chroot(cls, target):
        img = target
        imgsize = misc.get_file_size(img) * 1024L * 1024L
        partedcmd = fs_related.find_binary_path("parted")
        disk = fs_related.SparseLoopbackDisk(img, imgsize)
        extmnt = misc.mkdtemp()
        tmpoutdir = misc.mkdtemp()
        imgloop = PartitionedMount({'/dev/sdb':disk}, extmnt, skipformat = True)
        img_fstype = "ext3"
        extloop = None
        
        # Check the partitions from raw disk.
        p1 = subprocess.Popen([partedcmd,"-s",img,"unit","B","print"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out,err = p1.communicate()
        lines = out.strip().split("\n")
        
        root_mounted = False
        partition_mounts = 0

        for line in lines:
            line = line.strip()
            # Lines that start with number are the partitions,
            # because parted can be translated we can't refer to any text lines.
            if not line or not line[0].isdigit():
                continue
            
            # Some vars have extra , as list seperator.
            line = line.replace(",","")
            
            # Example of parted output lines that are handled:
            # Number  Start        End          Size         Type     File system     Flags
            #  1      512B         3400000511B  3400000000B  primary
            #  2      3400531968B  3656384511B  255852544B   primary  linux-swap(v1)
            #  3      3656384512B  3720347647B  63963136B    primary  fat16           boot, lba

            partition_info = re.split("\s+",line)

            size = partition_info[3].split("B")[0]

            if len(partition_info) < 6 or partition_info[5] in ["boot"]:
                # No filesystem can be found from partition line. Assuming
                # btrfs, because that is the only MeeGo fs that parted does 
                # not recognize properly.
                # TODO: Can we make better assumption?
                fstype = "btrfs"
            elif partition_info[5] in ["ext2","ext3","ext4","btrfs"]:
                fstype = partition_info[5]
            elif partition_info[5] in ["fat16","fat32"]:
                fstype = "vfat"
            elif "swap" in partition_info[5]:
                fstype = "swap"
            else:
                raise CreatorError("Could not recognize partition fs type '%s'." % partition_info[5])

            if not root_mounted and fstype in ["ext2","ext3","ext4","btrfs"]:
                # TODO: Check that this is actually the valid root partition from /etc/fstab
                mountpoint = "/"
                root_mounted = True
            elif fstype == "swap":
                mountpoint = "swap"
            else:
                # TODO: Assing better mount points for the rest of the partitions.
                partition_mounts += 1
                mountpoint = "/media/partition_%d" % partition_mounts

            if "boot" in partition_info:
                boot = True
            else:
                boot = False
            
            print "Size: %s Bytes, fstype: %s, mountpoint: %s, boot: %s" % ( size, fstype, mountpoint, boot )
            # TODO: add_partition should take bytes as size parameter.
            imgloop.add_partition((int)(size)/1024/1024, "/dev/sdb", mountpoint, fstype = fstype, boot = boot)
        
        try:
            imgloop.mount()
            os_image = img
        except MountError, e:
            imgloop.cleanup()
            raise CreatorError("Failed to loopback mount '%s' : %s" %
                               (img, e))

        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            chroot.cleanup_after_chroot("img", imgloop, None, None)
            print >> sys.stderr, "Failed to chroot to %s." % img
            return 1
            
    def do_unpack(self):
        convertoropts = configmgr.getConfigMgr().convert
        convertor = convertoropts["convertor"](convertoropts)        #consistent with destfmt
        srcimgsize = (misc.get_file_size(convertoropts["srcimg"])) * 1024L * 1024L
        convertor._set_fstype("ext3")
        convertor._set_image_size(srcimgsize)
        srcloop = RawImageCreator._mount_srcimg(convertoropts["srcimg"])
        base_on = srcloop.partitions[0]['device']
        convertor.check_depend_tools()
        convertor.mount(base_on, None)
        return convertor

mic_plugin = ["raw", RawPlugin]

