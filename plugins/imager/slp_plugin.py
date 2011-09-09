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

from mic import kickstart, msger, configmgr, pluginmgr
from mic.utils import errors, misc, fs_related as fs
from mic.imager.loop import LoopImageCreator

from mic.pluginbase import ImagerPlugin
class SLPlugin(ImagerPlugin):
    name = 'slp'

    @classmethod
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create slp image

        ${cmd_usage}
        ${cmd_option_list}
        """

        if not args:
            raise errors.Usage("More arguments needed")

        if len(args) != 1:
            raise errors.Usage("Extra arguments given")

        cfgmgr = configmgr.getConfigMgr()
        creatoropts = cfgmgr.create
        cfgmgr._ksconf = args[0]

        # try to find the pkgmgr
        pkgmgr = None
        for (key, pcls) in pluginmgr.PluginMgr().get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        if not pkgmgr:
            raise errors.CreatorError("Can't find package manager: %s" % creatoropts['pkgmgr'])

        creator = SLPImageCreator(creatoropts, pkgmgr)
        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.unmount()
            creator.package(creatoropts["outdir"])
            creator.print_outimage_info()

        except errors.CreatorError:
            raise
        finally:
            creator.cleanup()

        msger.info("Finished.")
        return 0

class SLPImageCreator(LoopImageCreator):
    """ SLPImageCreator is based on LoopImageCreator with the ability to
        support multiple partitions in kickstart file. And each partition
        will be created as a separated loop image.
    """

    def __init__(self, creatoropts = None, pkgmgr = None):
        LoopImageCreator.__init__(self, creatoropts, pkgmgr)

        if not self.ks:
            msger.error('No kickstart file specified')

        allloops = []
        for part in sorted(kickstart.get_partitions(self.ks),
                           key = lambda p: p.mountpoint):
            label = part.label

            mp = part.mountpoint
            if mp == '/':
                # the base image
                if not label:
                    label =  self.name
            else:
                mp = mp.rstrip('/')
                if not label:
                    msger.warning('no "label" specified for loop img at %s, use the mountpoint as the name' % mp)
                    label = mp.split('/')[-1]

            imgname = misc.strip_end(label,'.img') + '.img'
            allloops.append({
                'mountpoint': mp,
                'label': label,
                'name': imgname,
                'size': part.size or 4096L * 1024 * 1024,
                'fstype': part.fstype or 'ext4',
                'loop': None, # to be created in _mount_instroot
                })

        self._allloops = allloops # list of dict of image_name:loop_device

    def _mount_instroot(self, base_on = None):
        self._check_imgdir()
        self._base_on(base_on)
        imgdir = os.path.dirname(self._image)

        for loop in self._allloops:
            fstype = loop['fstype']
            mp = os.path.join(self._instroot, loop['mountpoint'].lstrip('/'))
            size = loop['size'] * 1024L * 1024L
            imgname = loop['name']

            if fstype in ("ext2", "ext3", "ext4"):
                MyDiskMount = fs.ExtDiskMount
            elif fstype == "btrfs":
                MyDiskMount = fs.BtrfsDiskMount
            else:
                msger.error('Cannot support fstype: %s' % fstype)

            loop['loop'] = MyDiskMount(fs.SparseLoopbackDisk(os.path.join(imgdir, imgname), size),
                                       mp,
                                       fstype,
                                       self._blocksize,
                                       loop['label'])

            try:
                msger.verbose('Mounting image "%s" on "%s"' %(imgname, mp))
                fs.makedirs(mp)
                loop['loop'].mount()
            except errors.MountError, e:
                raise

        self._instloops = self._allloops

    def _stage_final_image(self):
        import tarfile

        imgdir = os.path.dirname(self._image)
        curdir = os.getcwd()
        os.chdir(imgdir)
        self._resparse(0)

        tar = tarfile.open(os.path.join(self._outdir, 'platform.tar'), 'w')
        for item in self._instloops:
            tar.add(item['name'])
        tar.close()

        os.chdir(curdir)
