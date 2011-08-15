#!/usr/bin/python
import os
import sys
import subprocess
import logging
import shutil
import tempfile

from micng.pluginbase.imager_plugin import ImagerPlugin
import micng.utils.misc as misc
import micng.utils.cmdln as cmdln
import micng.utils.fs_related as fs_related
from micng.utils.errors import * 
import micng.configmgr as configmgr
import micng.pluginmgr as pluginmgr
import micng.imager.loop as loop
import micng.chroot as chroot

class LoopPlugin(ImagerPlugin):
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

        creator = loop.LoopImageCreator(creatoropts, pkgmgr)
        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])  
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.unmount()
            creator.package(creatoropts["outdir"])
        except CreatorError, e:
            raise CreatorError("failed to create image : %s" % e)
        finally:
            creator.cleanup()
        print "Finished."
        return 0    
           
    @classmethod
    def do_chroot(cls, target):#chroot.py parse opts&args
        #import pdb
        #pdb.set_trace()
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
            #os_image = img
        except MountError, e:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors = True)
            raise CreatorError("Failed to loopback mount '%s' : %s" %(img, e))
        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            raise CreatorError("Failed to chroot to %s." %img)  
        finally:
            chroot.cleanup_after_chroot("img", extloop, None, extmnt)

    @classmethod
    def do_unpack(cls, srcimg):
        image = os.path.join(tempfile.mkdtemp(dir = "/var/tmp", prefix = "tmp"), "meego.img")
        shutil.copyfile(srcimg, image)
        return image

        
mic_plugin = ["loop", LoopPlugin]

