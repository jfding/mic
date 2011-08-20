#!/usr/bin/python
import sys
import subprocess

from mic.pluginbase.imager_plugin import ImagerPlugin
import mic.utils.cmdln as cmdln
import mic.utils.errors as errors
import mic.configmgr as configmgr
import mic.pluginmgr as pluginmgr
import mic.imager.fs as fs
import mic.chroot as chroot


class FsPlugin(ImagerPlugin):
    @classmethod
    @cmdln.option("--include-src", dest="include_src", help="include source pakcage")
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
        createopts = cfgmgr.create
        cfgmgr.setProperty("ksconf", ksconf)

        plgmgr = pluginmgr.PluginMgr()
        plgmgr.loadPlugins()
        for (key, pcls) in plgmgr.getBackendPlugins():
            if key == createopts['pkgmgr']:
                pkgmgr = pcls
        if not pkgmgr:
            raise CreatorError("Can't find backend plugin: %s" % createopts['pkgmgr'])

        creator = fs.FsImageCreator(createopts, pkgmgr)
        try:
            creator.check_depend_tools()
            creator.mount(None, createopts["cachedir"])
            creator.install()
            #Download the source packages ###private options
            if opts.include_src:
                installed_pkgs =  creator.get_installed_packages()
                print '--------------------------------------------------'
                print 'Generating the image with source rpms included, The number of source packages is %d.' %(len(installed_pkgs))
                if not misc.SrcpkgsDownload(installed_pkgs, createopts["repomd"], creator._instroot, createopts["cachedir"]):
                    print "Source packages can't be downloaded"

            creator.configure(createopts["repomd"])
            creator.unmount()
            creator.package(createopts["outdir"])
            outimage = creator.outimage
            creator.print_outimage_info()
        except errors.CreatorError, e:
            raise errors.CreatorError("failed to create image : %s" % e)
        finally:
            creator.cleanup()
            print "Finished."

        return 0

    @classmethod
    def do_chroot(self, target):#chroot.py parse opts&args
            try:
                chroot.chroot(target, None, "/bin/env HOME=/root /bin/bash")
            except:
                print >> sys.stderr, "Failed to chroot to %s." % target
            finally:
                chroot.cleanup_after_chroot("dir", None, None, None)
                return 1

mic_plugin = ["fs", FsPlugin]
