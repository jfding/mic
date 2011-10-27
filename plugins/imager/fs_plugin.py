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

from mic import configmgr, pluginmgr, chroot, msger
from mic.utils import cmdln, misc, errors
from mic.imager import fs

from mic.pluginbase import ImagerPlugin
class FsPlugin(ImagerPlugin):
    name = 'fs'

    @classmethod
    @cmdln.option("--include-src", dest="include_src", action="store_true", default=False, help="Generate a image with source rpms included")
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create fs image

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

        creator = fs.FsImageCreator(creatoropts, pkgmgr)
        creator._include_src = opts.include_src

        if len(recording_pkgs) > 0:
            creator._recording_pkgs = recording_pkgs

        if creatoropts['release'] is None:
            fsdir = os.path.join(creator.destdir, creator.name)
            if os.path.exists(fsdir):
                if msger.ask('The target dir: %s already exists, cleanup and continue?' % fsdir):
                    import shutil
                    shutil.rmtree(fsdir)
                else:
                    raise errors.Abort('Canceled')

        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            #Download the source packages ###private options
            if opts.include_src:
                installed_pkgs =  creator.get_installed_packages()
                msger.info('--------------------------------------------------')
                msger.info('Generating the image with source rpms included, The number of source packages is %d.' %(len(installed_pkgs)))
                if not misc.SrcpkgsDownload(installed_pkgs, creatoropts["repomd"], creator._instroot, creatoropts["cachedir"]):
                    msger.warning("Source packages can't be downloaded")

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
    def do_chroot(self, target):#chroot.py parse opts&args
            try:
                chroot.chroot(target, None, "/bin/env HOME=/root /bin/bash")
            finally:
                chroot.cleanup_after_chroot("dir", None, None, None)
                return 1

