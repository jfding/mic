#!/usr/bin/python

from micng.pluginbase.imager_plugin import ImagerPlugin
from micng.imager.fs import *
import micng.configmgr as configmgr
try:
    import argparse
except:
    import micng.utils.argparse

class FsPlugin(ImagerPlugin):
    """hello livecd
    """
    @classmethod
    def do_options(self, parser):
        parser.add_argument('ksfile', nargs='?', help='kickstart file')
        parser.add_argument('--release', help='fs options test')

    @classmethod
    def do_create(self, args):
        if args.release:
            print "fs option release: ", args.release
        if not args.ksfile:
            print "please specify a kickstart file"
            return
#        print "ksfile", args.ksfile
        self.configmgr = configmgr.getConfigMgr()
        self.configmgr.setProperty('ksfile', args.ksfile)
#        print "ksfile", self.configmgr.getProperty('ksfile')
        self.ks = self.configmgr.getProperty('kickstart')
        self.name = self.configmgr.getProperty('name')
        fs = FsImageCreator(self.ks, self.name)
        try:
            fs.outdir = self.configmgr.getProperty('outdir')
            fs.mount(None, self.configmgr.cache)
            fs.install()
            fs.configure(self.configmgr.repometadata)
            fs.unmount()
            fs.package(self.configmgr.outdir)
            print "Finished"
        except Exception, e:
            print "failed to create image: %s" % e
        finally:
            fs.cleanup()


mic_plugin = ["fs", FsPlugin]
