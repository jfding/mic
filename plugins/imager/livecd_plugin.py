#!/usr/bin/python
from micng.pluginbase.imager_plugin import ImagerPlugin
import micng.imager as imager
import micng.configmgr as cfgmgr
import micng.utils as utils
import micng.utils.cmdln as cmdln
import os, time

class LivecdPlugin(ImagerPlugin):
    @classmethod
    def do_options(self, parser):
        parser.add_argument("-vid", "--volumeid", type="string", default=None, help="Specify volume id")
        parser.add_argument("ksfile", help="kickstart file")

    @classmethod
    def do_create(self, args):
        if not args.ksfile:
            print "please specify kickstart file"
            return

        self.configmgr = cfgmgr.getConfigMgr()
        self.configmgr.setProperty('ksfile', args.ksfile)

        fs_label = utils.kickstart.build_name(
                     args.ksfile,
                     "%s-" % self.configmgr.name,
                     maxlen = 32,
                     suffix = "%s-%s" %(os.uname()[4], time.strftime("%Y%m%d%H%M")))
        
        creator = imager.livecd.LivecdImageCreator(
                    self.configmgr.kickstart, self.configmgr.name, fs_label)
        
        creator.skip_compression = False
        creator.skip_minimize = False
            
        creator.tmpdir = self.configmgr.tmpdir
        creator._alt_initrd_name = None
        creator._recording_pkgs = None
        creator._include_src = False
        creator._local_pkgs_path = None
        creator._genchecksum = False
        creator.distro_name = self.configmgr.name
        creator.image_format = "livecd"
    
        
        utils.kickstart.resolve_groups(creator, self.configmgr.repometadata, False)
    
        imgname = creator.name
            
        try:
            creator.check_depend_tools()
            creator.mount(None, self.configmgr.cache)
            creator.install()
    
            creator.configure(self.configmgr.repometadata)
            creator.unmount()
            creator.package(self.configmgr.outdir)
            outimage = creator.outimage
                
            creator.package_output("livecd", self.configmgr.outdir, "none")
            creator.print_outimage_info()
            outimage = creator.outimage
            
        except Exception, e:
            raise Exception("failed to create image : %s" % e)
        finally:
            creator.cleanup()
    
        print "Finished."        

mic_plugin = ["livecd", LivecdPlugin]
