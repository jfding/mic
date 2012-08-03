#!/usr/bin/python -tt
#
# Copyright (c) 2009, 2010, 2011 Intel, Inc.
# Copyright (c) 2007, 2008 Red Hat, Inc.
# Copyright (c) 2008 Daniel P. Berrange
# Copyright (c) 2008 David P. Huff
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

from mic import msger
from mic.utils import runner
from mic.utils.errors import MountError
from mic.utils.fs_related import *

# Lenght of MBR in sectors
MBR_SECTOR_LEN = 1

# Size of a sector in bytes
SECTOR_SIZE = 512

class PartitionedMount(Mount):
    def __init__(self, disks, mountdir, skipformat = False):
        Mount.__init__(self, mountdir)
        self.disks = {}
        for name in disks.keys():
            self.disks[name] = { 'disk': disks[name],  # Disk object
                                 'mapped': False, # True if kpartx mapping exists
                                 'numpart': 0, # Number of allocate partitions
                                 'partitions': [], # indexes to self.partitions
                                 # Partitions with part num higher than 3 will
                                 # be put inside extended partition.
                                 'extended': 0, # Size of extended partition
                                 # Offset of next partition (in sectors)
                                 'offset': 0 }

        self.partitions = []
        self.subvolumes = []
        self.mapped = False
        self.mountOrder = []
        self.unmountOrder = []
        self.parted=find_binary_path("parted")
        self.kpartx=find_binary_path("kpartx")
        self.mkswap=find_binary_path("mkswap")
        self.btrfscmd=None
        self.mountcmd=find_binary_path("mount")
        self.umountcmd=find_binary_path("umount")
        self.skipformat = skipformat
        self.snapshot_created = self.skipformat
        # Size of a sector used in calculations
        self.sector_size = SECTOR_SIZE

    def add_partition(self, size, disk, mountpoint, fstype = None, label=None, fsopts = None, boot = False, align = None):
        # Converting MB to sectors for parted
        size = size * 1024 * 1024 / self.sector_size

        """ We need to handle subvolumes for btrfs """
        if fstype == "btrfs" and fsopts and fsopts.find("subvol=") != -1:
            self.btrfscmd=find_binary_path("btrfs")
            subvol = None
            opts = fsopts.split(",")
            for opt in opts:
                if opt.find("subvol=") != -1:
                    subvol = opt.replace("subvol=", "").strip()
                    break
            if not subvol:
                raise MountError("No subvolume: %s" % fsopts)
            self.subvolumes.append({'size': size, # In sectors
                                    'mountpoint': mountpoint, # Mount relative to chroot
                                    'fstype': fstype, # Filesystem type
                                    'fsopts': fsopts, # Filesystem mount options
                                    'disk': disk, # physical disk name holding partition
                                    'device': None, # kpartx device node for partition
                                    'mount': None, # Mount object
                                    'subvol': subvol, # Subvolume name
                                    'boot': boot, # Bootable flag
                                    'mounted': False # Mount flag
                                   })

        """ We still need partition for "/" or non-subvolume """
        if mountpoint == "/" or not fsopts or fsopts.find("subvol=") == -1:
            """ Don't need subvolume for "/" because it will be set as default subvolume """
            if fsopts and fsopts.find("subvol=") != -1:
                opts = fsopts.split(",")
                for opt in opts:
                    if opt.strip().startswith("subvol="):
                        opts.remove(opt)
                        break
                fsopts = ",".join(opts)
            self.partitions.append({'size': size, # In sectors
                                    'mountpoint': mountpoint, # Mount relative to chroot
                                    'fstype': fstype, # Filesystem type
                                    'fsopts': fsopts, # Filesystem mount options
                                    'label': label, # Partition label
                                    'disk': disk, # physical disk name holding partition
                                    'device': None, # kpartx device node for partition
                                    'mount': None, # Mount object
                                    'num': None, # Partition number
                                    'boot': boot, # Bootable flag
                                    'align': align}) # Partition alignment

    def __create_part_to_image(self, device, parttype, fstype, start, size):
        # Start is included to the size so we need to substract one from the end.
        end = start+size-1
        msger.debug("Added '%s' part at Sector %d with size %d sectors" %
                    (parttype, start, end))
        part_cmd = [self.parted, "-s", device, "unit", "s", "mkpart", parttype]
        if fstype:
            part_cmd.extend([fstype])
        part_cmd.extend(["%d" % start, "%d" % end])

        msger.debug(part_cmd)
        rc, out = runner.runtool(part_cmd, catch=3)
        out = out.strip()
        if out:
            msger.debug('"parted" output: %s' % out)
        return rc

    def __format_disks(self):
        msger.debug("Assigning partitions to disks")

        mbr_sector_skipped = False

        # Go through partitions in the order they are added in .ks file
        for n in range(len(self.partitions)):
            p = self.partitions[n]

            if not self.disks.has_key(p['disk']):
                raise MountError("No disk %s for partition %s" % (p['disk'], p['mountpoint']))

            if not mbr_sector_skipped:
                #  This hack is used to remove one sector from the first partition,
                #  that is the used to the MBR.
                p['size'] -= 1
                mbr_sector_skipped = True

            # Get the disk where the partition is located
            d = self.disks[p['disk']]
            d['numpart'] += 1

            # alignment in sectors
            align_sectors = None
            # if first partition then we need to skip the first sector
            # where the MBR is located, if the alignment isn't set
            # See: https://wiki.linaro.org/WorkingGroups/Kernel/Projects/FlashCardSurvey
            if d['numpart'] == 1:
                if p['align'] and p['align'] > 0:
                    align_sectors = p['align'] * 1024 / self.sector_size
                else:
                    align_sectors = MBR_SECTOR_LEN
            elif p['align']:
                # If not first partition and we do have alignment set we need
                # to align the partition.
                # FIXME: This leaves a empty spaces to the disk. To fill the
                # gaps we could enlargea the previous partition?

                # Calc how much the alignment is off.
                align_sectors = d['offset'] % (p['align'] * 1024 / self.sector_size)
                # We need to move forward to the next alignment point
                align_sectors = (p['align'] * 1024 / self.sector_size) - align_sectors

            if align_sectors:
                if p['align'] and p['align'] > 0:
                    msger.debug("Realignment for %s%s with %s sectors, original"
                                " offset %s, target alignment is %sK." %
                                (p['disk'], d['numpart'], align_sectors,
                                 d['offset'], p['align']))
                # p['size'] already converted in secctors
                if p['size'] <= align_sectors:
                    raise MountError("Partition for %s is too small to handle "
                                     "the alignment change." % p['mountpoint'])

                # increase the offset so we actually start the partition on right alignment
                d['offset'] += align_sectors

            if d['numpart'] > 3:
                # Increase allocation of extended partition to hold this partition
                d['extended'] += p['size']
                p['type'] = 'logical'
                p['num'] = d['numpart'] + 1
            else:
                p['type'] = 'primary'
                p['num'] = d['numpart']

            p['start'] = d['offset']
            d['offset'] += p['size']
            d['partitions'].append(n)
            msger.debug("Assigned %s to %s%d at Sector %d with size %d sectors "
                        "/ %d bytes." % (p['mountpoint'], p['disk'], p['num'],
                                         p['start'], p['size'],
                                         p['size'] * self.sector_size))

        if self.skipformat:
            msger.debug("Skipping disk format, because skipformat flag is set.")
            return

        for dev in self.disks.keys():
            d = self.disks[dev]
            msger.debug("Initializing partition table for %s" % (d['disk'].device))
            rc, out = runner.runtool([self.parted, "-s", d['disk'].device, "mklabel", "msdos"], catch=3)
            out = out.strip()
            if out:
                msger.debug('"parted" output: %s' % out)

            if rc != 0:
                # NOTE: We don't throw exception when return code is not 0, because
                # parted always fails to reload part table with loop devices.
                # This prevents us from distinguishing real errors based on return code.
                msger.debug("WARNING: parted returned '%s' instead of 0 when creating partition-table for disk '%s'." % (rc, d['disk'].device))

        msger.debug("Creating partitions")

        for p in self.partitions:
            d = self.disks[p['disk']]
            if p['num'] == 5:
                self.__create_part_to_image(d['disk'].device,"extended",None,p['start'],d['extended'])

            if p['fstype'] == "swap":
                parted_fs_type = "linux-swap"
            elif p['fstype'] == "vfat":
                parted_fs_type = "fat32"
            elif p['fstype'] == "msdos":
                parted_fs_type = "fat16"
            else:
                # Type for ext2/ext3/ext4/btrfs
                parted_fs_type = "ext2"

            # Boot ROM of OMAP boards require vfat boot partition to have an
            # even number of sectors.
            if p['mountpoint'] == "/boot" and p['fstype'] in ["vfat","msdos"] and p['size'] % 2:
                msger.debug("Substracting one sector from '%s' partition to get even number of sectors for the partition." % (p['mountpoint']))
                p['size'] -= 1

            ret = self.__create_part_to_image(d['disk'].device,p['type'],
                                             parted_fs_type, p['start'],
                                             p['size'])

            if ret != 0:
                # NOTE: We don't throw exception when return code is not 0, because
                # parted always fails to reload part table with loop devices.
                # This prevents us from distinguishing real errors based on return code.
                msger.debug("WARNING: parted returned '%s' instead of 0 when creating partition '%s' for disk '%s'." % (ret, p['mountpoint'], d['disk'].device))

            if p['boot']:
                msger.debug("Setting boot flag for partition '%s' on disk '%s'." % (p['num'],d['disk'].device))
                boot_cmd = [self.parted, "-s", d['disk'].device, "set", "%d" % p['num'], "boot", "on"]
                msger.debug(boot_cmd)
                rc = runner.show(boot_cmd)

                if rc != 0:
                    # NOTE: We don't throw exception when return code is not 0, because
                    # parted always fails to reload part table with loop devices.
                    # This prevents us from distinguishing real errors based on return code.
                    msger.warning("parted returned '%s' instead of 0 when adding boot flag for partition '%s' disk '%s'." % (rc,p['num'],d['disk'].device))

    def __map_partitions(self):
        """Load it if dm_snapshot isn't loaded"""
        load_module("dm_snapshot")

        for dev in self.disks.keys():
            d = self.disks[dev]
            if d['mapped']:
                continue

            msger.debug("Running kpartx on %s" % d['disk'].device )
            rc, kpartxOutput = runner.runtool([self.kpartx, "-l", "-v", d['disk'].device])
            kpartxOutput = kpartxOutput.splitlines()

            if rc != 0:
                raise MountError("Failed to query partition mapping for '%s'" %
                                 d['disk'].device)

            # Strip trailing blank and mask verbose output
            i = 0
            while i < len(kpartxOutput) and kpartxOutput[i][0:4] != "loop":
               i = i + 1
            kpartxOutput = kpartxOutput[i:]

            # Quick sanity check that the number of partitions matches
            # our expectation. If it doesn't, someone broke the code
            # further up
            if len(kpartxOutput) != d['numpart']:
                raise MountError("Unexpected number of partitions from kpartx: %d != %d" %
                                 (len(kpartxOutput), d['numpart']))

            for i in range(len(kpartxOutput)):
                line = kpartxOutput[i]
                newdev = line.split()[0]
                mapperdev = "/dev/mapper/" + newdev
                loopdev = d['disk'].device + newdev[-1]

                msger.debug("Dev %s: %s -> %s" % (newdev, loopdev, mapperdev))
                pnum = d['partitions'][i]
                self.partitions[pnum]['device'] = loopdev

                # grub's install wants partitions to be named
                # to match their parent device + partition num
                # kpartx doesn't work like this, so we add compat
                # symlinks to point to /dev/mapper
                if os.path.lexists(loopdev):
                    os.unlink(loopdev)
                os.symlink(mapperdev, loopdev)

            msger.debug("Adding partx mapping for %s" % d['disk'].device)
            rc = runner.show([self.kpartx, "-v", "-a", d['disk'].device])

            if rc != 0:
                # Make sure that the device maps are also removed on error case.
                # The d['mapped'] isn't set to True if the kpartx fails so
                # failed mapping will not be cleaned on cleanup either.
                runner.quiet([self.kpartx, "-d", d['disk'].device])
                raise MountError("Failed to map partitions for '%s'" %
                                 d['disk'].device)

            d['mapped'] = True

    def __unmap_partitions(self):
        for dev in self.disks.keys():
            d = self.disks[dev]
            if not d['mapped']:
                continue

            msger.debug("Removing compat symlinks")
            for pnum in d['partitions']:
                if self.partitions[pnum]['device'] != None:
                    os.unlink(self.partitions[pnum]['device'])
                    self.partitions[pnum]['device'] = None

            msger.debug("Unmapping %s" % d['disk'].device)
            rc = runner.quiet([self.kpartx, "-d", d['disk'].device])
            if rc != 0:
                raise MountError("Failed to unmap partitions for '%s'" %
                                 d['disk'].device)

            d['mapped'] = False

    def __calculate_mountorder(self):
        msger.debug("Calculating mount order")
        for p in self.partitions:
            self.mountOrder.append(p['mountpoint'])
            self.unmountOrder.append(p['mountpoint'])

        self.mountOrder.sort()
        self.unmountOrder.sort()
        self.unmountOrder.reverse()

    def cleanup(self):
        Mount.cleanup(self)
        self.__unmap_partitions()
        for dev in self.disks.keys():
            d = self.disks[dev]
            try:
                d['disk'].cleanup()
            except:
                pass

    def unmount(self):
        self.__unmount_subvolumes()
        for mp in self.unmountOrder:
            if mp == 'swap':
                continue
            p = None
            for p1 in self.partitions:
                if p1['mountpoint'] == mp:
                    p = p1
                    break

            if p['mount'] != None:
                try:
                    """ Create subvolume snapshot here """
                    if p['fstype'] == "btrfs" and p['mountpoint'] == "/" and not self.snapshot_created:
                        self.__create_subvolume_snapshots(p, p["mount"])
                    p['mount'].cleanup()
                except:
                    pass
                p['mount'] = None

    """ Only for btrfs """
    def __get_subvolume_id(self, rootpath, subvol):
        if not self.btrfscmd:
            self.btrfscmd=find_binary_path("btrfs")
        argv = [ self.btrfscmd, "subvolume", "list", rootpath ]

        rc, out = runner.runtool(argv)
        msger.debug(out)

        if rc != 0:
            raise MountError("Failed to get subvolume id from %s', return code: %d." % (rootpath, rc))

        subvolid = -1
        for line in out.splitlines():
            if line.endswith(" path %s" % subvol):
                subvolid = line.split()[1]
                if not subvolid.isdigit():
                    raise MountError("Invalid subvolume id: %s" % subvolid)
                subvolid = int(subvolid)
                break
        return subvolid

    def __create_subvolume_metadata(self, p, pdisk):
        if len(self.subvolumes) == 0:
            return

        argv = [ self.btrfscmd, "subvolume", "list", pdisk.mountdir ]
        rc, out = runner.runtool(argv)
        msger.debug(out)

        if rc != 0:
            raise MountError("Failed to get subvolume id from %s', return code: %d." % (pdisk.mountdir, rc))

        subvolid_items = out.splitlines()
        subvolume_metadata = ""
        for subvol in self.subvolumes:
            for line in subvolid_items:
                if line.endswith(" path %s" % subvol["subvol"]):
                    subvolid = line.split()[1]
                    if not subvolid.isdigit():
                        raise MountError("Invalid subvolume id: %s" % subvolid)

                    subvolid = int(subvolid)
                    opts = subvol["fsopts"].split(",")
                    for opt in opts:
                        if opt.strip().startswith("subvol="):
                            opts.remove(opt)
                            break
                    fsopts = ",".join(opts)
                    subvolume_metadata += "%d\t%s\t%s\t%s\n" % (subvolid, subvol["subvol"], subvol['mountpoint'], fsopts)

        if subvolume_metadata:
            fd = open("%s/.subvolume_metadata" % pdisk.mountdir, "w")
            fd.write(subvolume_metadata)
            fd.close()

    def __get_subvolume_metadata(self, p, pdisk):
        subvolume_metadata_file = "%s/.subvolume_metadata" % pdisk.mountdir
        if not os.path.exists(subvolume_metadata_file):
            return

        fd = open(subvolume_metadata_file, "r")
        content = fd.read()
        fd.close()

        for line in content.splitlines():
            items = line.split("\t")
            if items and len(items) == 4:
                self.subvolumes.append({'size': 0, # In sectors
                                        'mountpoint': items[2], # Mount relative to chroot
                                        'fstype': "btrfs", # Filesystem type
                                        'fsopts': items[3] + ",subvol=%s" %  items[1], # Filesystem mount options
                                        'disk': p['disk'], # physical disk name holding partition
                                        'device': None, # kpartx device node for partition
                                        'mount': None, # Mount object
                                        'subvol': items[1], # Subvolume name
                                        'boot': False, # Bootable flag
                                        'mounted': False # Mount flag
                                   })

    def __create_subvolumes(self, p, pdisk):
        """ Create all the subvolumes """

        for subvol in self.subvolumes:
            argv = [ self.btrfscmd, "subvolume", "create", pdisk.mountdir + "/" + subvol["subvol"]]

            rc = runner.show(argv)
            if rc != 0:
                raise MountError("Failed to create subvolume '%s', return code: %d." % (subvol["subvol"], rc))

        """ Set default subvolume, subvolume for "/" is default """
        subvol = None
        for subvolume in self.subvolumes:
            if subvolume["mountpoint"] == "/" and p["disk"] == subvolume["disk"]:
                subvol = subvolume
                break

        if subvol:
            """ Get default subvolume id """
            subvolid = self. __get_subvolume_id(pdisk.mountdir, subvol["subvol"])
            """ Set default subvolume """
            if subvolid != -1:
                rc = runner.show([ self.btrfscmd, "subvolume", "set-default", "%d" % subvolid, pdisk.mountdir])
                if rc != 0:
                    raise MountError("Failed to set default subvolume id: %d', return code: %d." % (subvolid, rc))

        self.__create_subvolume_metadata(p, pdisk)

    def __mount_subvolumes(self, p, pdisk):
        if self.skipformat:
            """ Get subvolume info """
            self.__get_subvolume_metadata(p, pdisk)
            """ Set default mount options """
            if len(self.subvolumes) != 0:
                for subvol in self.subvolumes:
                    if subvol["mountpoint"] == p["mountpoint"] == "/":
                        opts = subvol["fsopts"].split(",")
                        for opt in opts:
                            if opt.strip().startswith("subvol="):
                                opts.remove(opt)
                                break
                        pdisk.fsopts = ",".join(opts)
                        break

        if len(self.subvolumes) == 0:
            """ Return directly if no subvolumes """
            return

        """ Remount to make default subvolume mounted """
        rc = runner.show([self.umountcmd, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)

        rc = runner.show([self.mountcmd, "-o", pdisk.fsopts, pdisk.disk.device, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)

        for subvol in self.subvolumes:
            if subvol["mountpoint"] == "/":
                continue
            subvolid = self. __get_subvolume_id(pdisk.mountdir, subvol["subvol"])
            if subvolid == -1:
                msger.debug("WARNING: invalid subvolume %s" % subvol["subvol"])
                continue
            """ Replace subvolume name with subvolume ID """
            opts = subvol["fsopts"].split(",")
            for opt in opts:
                if opt.strip().startswith("subvol="):
                    opts.remove(opt)
                    break

            opts.extend(["subvolrootid=0", "subvol=%s" % subvol["subvol"]])
            fsopts = ",".join(opts)
            subvol['fsopts'] = fsopts
            mountpoint = self.mountdir + subvol['mountpoint']
            makedirs(mountpoint)
            rc = runner.show([self.mountcmd, "-o", fsopts, pdisk.disk.device, mountpoint])
            if rc != 0:
                raise MountError("Failed to mount subvolume %s to %s" % (subvol["subvol"], mountpoint))
            subvol["mounted"] = True

    def __unmount_subvolumes(self):
        """ It may be called multiple times, so we need to chekc if it is still mounted. """
        for subvol in self.subvolumes:
            if subvol["mountpoint"] == "/":
                continue
            if not subvol["mounted"]:
                continue
            mountpoint = self.mountdir + subvol['mountpoint']
            rc = runner.show([self.umountcmd, mountpoint])
            if rc != 0:
                raise MountError("Failed to unmount subvolume %s from %s" % (subvol["subvol"], mountpoint))
            subvol["mounted"] = False

    def __create_subvolume_snapshots(self, p, pdisk):
        import time

        if self.snapshot_created:
            return

        """ Remount with subvolid=0 """
        rc = runner.show([self.umountcmd, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)
        if pdisk.fsopts:
            mountopts = pdisk.fsopts + ",subvolid=0"
        else:
            mountopts = "subvolid=0"
        rc = runner.show([self.mountcmd, "-o", mountopts, pdisk.disk.device, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)

        """ Create all the subvolume snapshots """
        snapshotts = time.strftime("%Y%m%d-%H%M")
        for subvol in self.subvolumes:
            subvolpath = pdisk.mountdir + "/" + subvol["subvol"]
            snapshotpath = subvolpath + "_%s-1" % snapshotts
            rc = runner.show([ self.btrfscmd, "subvolume", "snapshot", subvolpath, snapshotpath ])
            if rc != 0:
                raise MountError("Failed to create subvolume snapshot '%s' for '%s', return code: %d." % (snapshotpath, subvolpath, rc))

        self.snapshot_created = True

    def mount(self):
        for dev in self.disks.keys():
            d = self.disks[dev]
            d['disk'].create()

        self.__format_disks()
        self.__map_partitions()
        self.__calculate_mountorder()

        for mp in self.mountOrder:
            p = None
            for p1 in self.partitions:
                if p1['mountpoint'] == mp:
                    p = p1
                    break

            if not p['label']:
                if p['mountpoint'] == "/":
                    p['label'] = 'platform'
                else:
                    p['label'] = mp.split('/')[-1]

            if mp == 'swap':
                import uuid
                p['uuid'] = str(uuid.uuid1())
                runner.show([self.mkswap,
                             '-L', p['label'],
                             '-U', p['uuid'],
                             p['device']])
                continue

            rmmountdir = False
            if p['mountpoint'] == "/":
                rmmountdir = True
            if p['fstype'] == "vfat" or p['fstype'] == "msdos":
                myDiskMount = VfatDiskMount
            elif p['fstype'] in ("ext2", "ext3", "ext4"):
                myDiskMount = ExtDiskMount
            elif p['fstype'] == "btrfs":
                myDiskMount = BtrfsDiskMount
            else:
                raise MountError("Fail to support file system " + p['fstype'])

            if p['fstype'] == "btrfs" and not p['fsopts']:
                p['fsopts'] = "subvolid=0"

            pdisk = myDiskMount(RawDisk(p['size'] * self.sector_size, p['device']),
                                 self.mountdir + p['mountpoint'],
                                 p['fstype'],
                                 4096,
                                 p['label'],
                                 rmmountdir,
                                 self.skipformat,
                                 fsopts = p['fsopts'])
            pdisk.mount(pdisk.fsopts)
            if p['fstype'] == "btrfs" and p['mountpoint'] == "/":
                if not self.skipformat:
                    self.__create_subvolumes(p, pdisk)
                self.__mount_subvolumes(p, pdisk)
            p['mount'] = pdisk
            p['uuid'] = pdisk.uuid

    def resparse(self, size = None):
        # Can't re-sparse a disk image - too hard
        pass
