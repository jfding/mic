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

from mic import chroot, msger, rt_util
from mic.utils import misc, fs_related, errors, cmdln
from mic.conf import configmgr
from mic.plugin import pluginmgr
from mic.imager.loop import LoopImageCreator, load_mountpoints

from mic.pluginbase import ImagerPlugin
class LoopPlugin(ImagerPlugin):
    name = 'loop'

    @classmethod
    @cmdln.option("--compress-disk-image", dest="compress_image",
                  type='choice', choices=("gz", "bz2"), default=None,
                  help="Same with --compress-image")
                  # alias to compress-image for compatibility
    @cmdln.option("--compress-image", dest="compress_image",
                  type='choice', choices=("gz", "bz2"), default=None,
                  help="Compress all loop images with 'gz' or 'bz2'")
    @cmdln.option("--shrink", action='store_true', default=False,
                  help="Whether to shrink loop images to minimal size")
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create loop image

        Usage:
            ${name} ${cmd_name} <ksfile> [OPTS]

        ${cmd_option_list}
        """

        if not args:
            raise errors.Usage("need one argument as the path of ks file")

        if len(args) != 1:
            raise errors.Usage("Extra arguments given")

        creatoropts = configmgr.create
        ksconf = args[0]

        if not os.path.exists(ksconf):
            raise errors.CreatorError("Can't find the file: %s" % ksconf)

        recording_pkgs = []
        if len(creatoropts['record_pkgs']) > 0:
            recording_pkgs = creatoropts['record_pkgs']

        if creatoropts['release'] is not None:
            if 'name' not in recording_pkgs:
                recording_pkgs.append('name')

        ksconf = misc.normalize_ksfile(ksconf,
                                       creatoropts['release'],
                                       creatoropts['arch'])
        configmgr._ksconf = ksconf

        # Called After setting the configmgr._ksconf
        # as the creatoropts['name'] is reset there.
        if creatoropts['release'] is not None:
            creatoropts['outdir'] = "%s/%s/images/%s/" % (creatoropts['outdir'],
                                                          creatoropts['release'],
                                                          creatoropts['name'])

        # try to find the pkgmgr
        pkgmgr = None
        for (key, pcls) in pluginmgr.get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        if not pkgmgr:
            pkgmgrs = pluginmgr.get_plugins('backend').keys()
            raise errors.CreatorError("Can't find package manager: %s "
                                      "(availables: %s)" \
                                      % (creatoropts['pkgmgr'],
                                         ', '.join(pkgmgrs)))

        if creatoropts['runtime']:
            rt_util.runmic_in_runtime(creatoropts['runtime'], creatoropts, ksconf, None)

        creator = LoopImageCreator(creatoropts,
                                   pkgmgr,
                                   opts.compress_image,
                                   opts.shrink)

        if len(recording_pkgs) > 0:
            creator._recording_pkgs = recording_pkgs

        self.check_image_exists(creator.destdir,
                                creator.pack_to,
                                [creator.name + ".img"],
                                creatoropts['release'])

        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.copy_kernel()
            creator.unmount()
            creator.package(creatoropts["outdir"])

            if creatoropts['release'] is not None:
                creator.release_output(ksconf,
                                       creatoropts['outdir'],
                                       creatoropts['release'])
            creator.print_outimage_info()

        except errors.CreatorError:
            raise
        finally:
            creator.cleanup()

        msger.info("Finished.")
        return 0

    @classmethod
    def _do_chroot_tar(cls, target):
        mountfp_xml = os.path.splitext(target)[0] + '.xml'
        if not os.path.exists(mountfp_xml):
            raise errors.CreatorError("No mount point file found for this tar "
                                      "image, please check %s" % mountfp_xml)

        import tarfile
        tar = tarfile.open(target, 'r')
        tmpdir = misc.mkdtemp()
        tar.extractall(path=tmpdir)
        tar.close()

        mntdir = misc.mkdtemp()

        loops = []
        for (mp, label, name, size, fstype) in load_mountpoints(mountfp_xml):
            if fstype in ("ext2", "ext3", "ext4"):
                myDiskMount = fs_related.ExtDiskMount
            elif fstype == "btrfs":
                myDiskMount = fs_related.BtrfsDiskMount
            elif fstype in ("vfat", "msdos"):
                myDiskMount = fs_related.VfatDiskMount
            else:
                msger.error("Cannot support fstype: %s" % fstype)

            name = os.path.join(tmpdir, name)
            size = size * 1024L * 1024L
            loop = myDiskMount(fs_related.SparseLoopbackDisk(name, size),
                               os.path.join(mntdir, mp.lstrip('/')),
                               fstype, size, label)

            try:
                msger.verbose("Mount %s to %s" % (mp, mntdir + mp))
                fs_related.makedirs(os.path.join(mntdir, mp.lstrip('/')))
                loop.mount()

            except:
                loop.cleanup()
                for lp in reversed(loops):
                    chroot.cleanup_after_chroot("img", lp, None, mntdir)

                shutil.rmtree(tmpdir, ignore_errors=True)
                raise

            loops.append(loop)

        try:
            chroot.chroot(mntdir, None, "/usr/bin/env HOME=/root /bin/bash")
        except:
            raise errors.CreatorError("Failed to chroot to %s." % target)
        finally:
            for loop in reversed(loops):
                chroot.cleanup_after_chroot("img", loop, None, mntdir)

            shutil.rmtree(tmpdir, ignore_errors=True)

    @classmethod
    def do_chroot(cls, target):
        if target.endswith('.tar'):
            import tarfile
            if tarfile.is_tarfile(target):
                LoopPlugin._do_chroot_tar(target)
                return
            else:
                raise errors.CreatorError("damaged tarball for loop images")

        img = target
        imgsize = misc.get_file_size(img) * 1024L * 1024L
        imgtype = misc.get_image_type(img)
        if imgtype == "btrfsimg":
            fstype = "btrfs"
            myDiskMount = fs_related.BtrfsDiskMount
        elif imgtype in ("ext3fsimg", "ext4fsimg"):
            fstype = imgtype[:4]
            myDiskMount = fs_related.ExtDiskMount
        else:
            raise errors.CreatorError("Unsupported filesystem type: %s" \
                                      % imgtype)

        extmnt = misc.mkdtemp()
        extloop = myDiskMount(fs_related.SparseLoopbackDisk(img, imgsize),
                                                         extmnt,
                                                         fstype,
                                                         4096,
                                                         "%s label" % fstype)
        try:
            extloop.mount()

        except errors.MountError:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors=True)
            raise

        try:
            envcmd = fs_related.find_binary_inchroot("env", extmnt)
            if envcmd:
                cmdline = "%s HOME=/root /bin/bash" % envcmd
            else:
                cmdline = "/bin/bash"
            chroot.chroot(extmnt, None, cmdline)
        except:
            raise errors.CreatorError("Failed to chroot to %s." % img)
        finally:
            chroot.cleanup_after_chroot("img", extloop, None, extmnt)

    @classmethod
    def do_unpack(cls, srcimg):
        image = os.path.join(tempfile.mkdtemp(dir="/var/tmp", prefix="tmp"),
                             "target.img")
        msger.info("Copying file system ...")
        shutil.copyfile(srcimg, image)
        return image
