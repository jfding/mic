#
# partitionedfs.py: partitioned files system class, extends fs.py
#
# Copyright 2007-2008, Red Hat  Inc.
# Copyright 2008, Daniel P. Berrange
# Copyright 2008,  David P. Huff
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os
import os.path
import glob
import shutil
import subprocess
import logging
import time

from micng.utils.errors import *
from micng.utils.fs_related import *

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
                                 # Sector 0 is used by the MBR and can't be used
                                 # as the start, so setting offset to 1.
                                 'offset': 1 } # Offset of next partition (in sectors)

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
        self.sector_size = 512

    def add_partition(self, size, disk, mountpoint, fstype = None, fsopts = None, boot = False):
        # Converting M to s for parted
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
                                    'disk': disk, # physical disk name holding partition
                                    'device': None, # kpartx device node for partition
                                    'mount': None, # Mount object
                                    'num': None, # Partition number
                                    'boot': boot}) # Bootable flag

    def __create_part_to_image(self,device, parttype, fstype, start, size):
        # Start is included to the size so we need to substract one from the end.
        end = start+size-1
        logging.debug("Added '%s' part at %d of size %d" % (parttype,start,end))
        part_cmd = [self.parted, "-s", device, "unit", "s", "mkpart", parttype]
        if fstype:
            part_cmd.extend([fstype])
        part_cmd.extend(["%d" % start, "%d" % end])
        logging.debug(part_cmd)
        p1 = subprocess.Popen(part_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out,err) = p1.communicate()
        logging.debug(out)
        return p1

    def __format_disks(self):
        logging.debug("Assigning partitions to disks")
        
        mbr_sector_skipped = False
        
        for n in range(len(self.partitions)):
            p = self.partitions[n]

            if not self.disks.has_key(p['disk']):
                raise MountError("No disk %s for partition %s" % (p['disk'], p['mountpoint']))
            
            if not mbr_sector_skipped:
                # This hack is used to remove one sector from the first partition,
                # that is the used to the MBR.
                p['size'] -= 1
                mbr_sector_skipped = True

            d = self.disks[p['disk']]
            d['numpart'] += 1
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
            logging.debug("Assigned %s to %s%d at %d at size %d" % (p['mountpoint'], p['disk'], p['num'], p['start'], p['size']))

        if self.skipformat:
            logging.debug("Skipping disk format, because skipformat flag is set.")
            return
            
        for dev in self.disks.keys():
            d = self.disks[dev]
            logging.debug("Initializing partition table for %s" % (d['disk'].device))
            p1 = subprocess.Popen([self.parted, "-s", d['disk'].device, "mklabel", "msdos"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out,err) = p1.communicate()            
            logging.debug(out)
            
            if p1.returncode != 0:
                # NOTE: We don't throw exception when return code is not 0, because
                # parted always fails to reload part table with loop devices.
                # This prevents us from distinguishing real errors based on return code.
                logging.debug("WARNING: parted returned '%s' instead of 0 when creating partition-table for disk '%s'." % (p1.returncode,d['disk'].device))

        logging.debug("Creating partitions")

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
                logging.debug("Substracting one sector from '%s' partition to get even number of sectors for the partition." % (p['mountpoint']))
                p['size'] -= 1
                
            p1 = self.__create_part_to_image(d['disk'].device,p['type'], 
                                             parted_fs_type, p['start'], 
                                             p['size'])

            if p1.returncode != 0:
                # NOTE: We don't throw exception when return code is not 0, because
                # parted always fails to reload part table with loop devices.
                # This prevents us from distinguishing real errors based on return code.
                logging.debug("WARNING: parted returned '%s' instead of 0 when creating partition '%s' for disk '%s'." % (p1.returncode,p['mountpoint'],d['disk'].device))

            if p['boot']:
                logging.debug("Setting boot flag for partition '%s' on disk '%s'." % (p['num'],d['disk'].device))
                boot_cmd = [self.parted, "-s", d['disk'].device, "set", "%d" % p['num'], "boot", "on"]
                logging.debug(boot_cmd)
                p1 = subprocess.Popen(boot_cmd,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                (out,err) = p1.communicate()            
                logging.debug(out)

                if p1.returncode != 0:
                    # NOTE: We don't throw exception when return code is not 0, because
                    # parted always fails to reload part table with loop devices.
                    # This prevents us from distinguishing real errors based on return code.
                    logging.debug("WARNING: parted returned '%s' instead of 0 when adding boot flag for partition '%s' disk '%s'." % (p1.returncode,p['num'],d['disk'].device))

    def __map_partitions(self):
        """Load it if dm_snapshot isn't loaded"""
        load_module("dm_snapshot")

        dev_null = os.open("/dev/null", os.O_WRONLY)
        for dev in self.disks.keys():
            d = self.disks[dev]
            if d['mapped']:
                continue

            logging.debug("Running kpartx on %s" % d['disk'].device )
            kpartx = subprocess.Popen([self.kpartx, "-l", "-v", d['disk'].device],
                                      stdout=subprocess.PIPE, stderr=dev_null)

            kpartxOutput = kpartx.communicate()[0].strip().split("\n")

            if kpartx.returncode:
                os.close(dev_null)
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
                os.close(dev_null)
                raise MountError("Unexpected number of partitions from kpartx: %d != %d" %
                                 (len(kpartxOutput), d['numpart']))

            for i in range(len(kpartxOutput)):
                line = kpartxOutput[i]
                newdev = line.split()[0]
                mapperdev = "/dev/mapper/" + newdev
                loopdev = d['disk'].device + newdev[-1]

                logging.debug("Dev %s: %s -> %s" % (newdev, loopdev, mapperdev))
                pnum = d['partitions'][i]
                self.partitions[pnum]['device'] = loopdev

                # grub's install wants partitions to be named
                # to match their parent device + partition num
                # kpartx doesn't work like this, so we add compat
                # symlinks to point to /dev/mapper
                if os.path.lexists(loopdev):
                    os.unlink(loopdev)
                os.symlink(mapperdev, loopdev)

            logging.debug("Adding partx mapping for %s" % d['disk'].device)
            p1 = subprocess.Popen([self.kpartx, "-v", "-a", d['disk'].device],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            
            (out,err) = p1.communicate()
            logging.debug(out)
            
            if p1.returncode != 0:
                # Make sure that the device maps are also removed on error case.
                # The d['mapped'] isn't set to True if the kpartx fails so
                # failed mapping will not be cleaned on cleanup either.
                subprocess.call([self.kpartx, "-d", d['disk'].device],
                                stdout=dev_null, stderr=dev_null)
                os.close(dev_null)
                raise MountError("Failed to map partitions for '%s'" %
                                 d['disk'].device)
            d['mapped'] = True
        os.close(dev_null)


    def __unmap_partitions(self):
        dev_null = os.open("/dev/null", os.O_WRONLY)
        for dev in self.disks.keys():
            d = self.disks[dev]
            if not d['mapped']:
                continue

            logging.debug("Removing compat symlinks")
            for pnum in d['partitions']:
                if self.partitions[pnum]['device'] != None:
                    os.unlink(self.partitions[pnum]['device'])
                    self.partitions[pnum]['device'] = None

            logging.debug("Unmapping %s" % d['disk'].device)
            rc = subprocess.call([self.kpartx, "-d", d['disk'].device],
                                 stdout=dev_null, stderr=dev_null)
            if rc != 0:
                os.close(dev_null)
                raise MountError("Failed to unmap partitions for '%s'" %
                                 d['disk'].device)

            d['mapped'] = False
            os.close(dev_null)


    def __calculate_mountorder(self):
        logging.debug("Calculating mount order")
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
        p1 = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out,err) = p1.communicate()
        logging.debug(out)
        if p1.returncode != 0:
            raise MountError("Failed to get subvolume id from %s', return code: %d." % (rootpath, p1.returncode))
        subvolid = -1
        for line in out.split("\n"):
            if line.endswith(" path %s" % subvol):
                subvolid = line.split(" ")[1]
                if not subvolid.isdigit():
                    raise MountError("Invalid subvolume id: %s" % subvolid)
                subvolid = int(subvolid)
                break
        return subvolid

    def __create_subvolume_metadata(self, p, pdisk):
        if len(self.subvolumes) == 0:
            return
        argv = [ self.btrfscmd, "subvolume", "list", pdisk.mountdir ]
        p1 = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out,err) = p1.communicate()
        logging.debug(out)
        if p1.returncode != 0:
            raise MountError("Failed to get subvolume id from %s', return code: %d." % (pdisk.mountdir, p1.returncode))
        subvolid_items = out.split("\n")
        subvolume_metadata = ""
        for subvol in self.subvolumes:
            for line in subvolid_items:
                if line.endswith(" path %s" % subvol["subvol"]):
                    subvolid = line.split(" ")[1]
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
        for line in content.split("\n"):
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
            p1 = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out,err) = p1.communicate()
            logging.debug(out)
            if p1.returncode != 0:
                raise MountError("Failed to create subvolume '%s', return code: %d." % (subvol["subvol"], p1.returncode))

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
                argv = [ self.btrfscmd, "subvolume", "set-default", "%d" % subvolid, pdisk.mountdir]
                p1 = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                (out,err) = p1.communicate()
                logging.debug(out)
                if p1.returncode != 0:
                    raise MountError("Failed to set default subvolume id: %d', return code: %d." % (subvolid, p1.returncode))

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
        rc = subprocess.call([self.umountcmd, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)
        rc = subprocess.call([self.mountcmd, "-o", pdisk.fsopts, pdisk.disk.device, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)
        for subvol in self.subvolumes:
            if subvol["mountpoint"] == "/":
                continue
            subvolid = self. __get_subvolume_id(pdisk.mountdir, subvol["subvol"])
            if subvolid == -1:
                logging.debug("WARNING: invalid subvolume %s" % subvol["subvol"])
                continue
            """ Replace subvolume name with subvolume ID """
            opts = subvol["fsopts"].split(",")
            for opt in opts:
                if opt.strip().startswith("subvol="):
                    opts.remove(opt)
                    break
            #opts.append("subvolid=%d" % subvolid)
            opts.extend(["subvolrootid=0", "subvol=%s" % subvol["subvol"]])
            fsopts = ",".join(opts)
            subvol['fsopts'] = fsopts
            mountpoint = self.mountdir + subvol['mountpoint']
            makedirs(mountpoint)
            rc = subprocess.call([self.mountcmd, "-o", fsopts, pdisk.disk.device, mountpoint])
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
            rc = subprocess.call([self.umountcmd, mountpoint])
            if rc != 0:
                raise MountError("Failed to unmount subvolume %s from %s" % (subvol["subvol"], mountpoint))
            subvol["mounted"] = False

    def __create_subvolume_snapshots(self, p, pdisk):
        if self.snapshot_created:
            return

        """ Remount with subvolid=0 """
        rc = subprocess.call([self.umountcmd, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)
        if pdisk.fsopts:
            mountopts = pdisk.fsopts + ",subvolid=0"
        else:
            mountopts = "subvolid=0"
        rc = subprocess.call([self.mountcmd, "-o", mountopts, pdisk.disk.device, pdisk.mountdir])
        if rc != 0:
            raise MountError("Failed to umount %s" % pdisk.mountdir)

        """ Create all the subvolume snapshots """
        snapshotts = time.strftime("%Y%m%d-%H%M")
        for subvol in self.subvolumes:
            subvolpath = pdisk.mountdir + "/" + subvol["subvol"]
            snapshotpath = subvolpath + "_%s-1" % snapshotts
            argv = [ self.btrfscmd, "subvolume", "snapshot", subvolpath, snapshotpath ]
            p1 = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out,err) = p1.communicate()
            logging.debug(out)
            if p1.returncode != 0:
                raise MountError("Failed to create subvolume snapshot '%s' for '%s', return code: %d." % (snapshotpath, subvolpath, p1.returncode))
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

            if mp == 'swap':
                subprocess.call([self.mkswap, p['device']])
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
                                 p['mountpoint'],
                                 rmmountdir,
                                 self.skipformat,
                                 fsopts = p['fsopts'])
            pdisk.mount(pdisk.fsopts)
            if p['fstype'] == "btrfs" and p['mountpoint'] == "/":
                if not self.skipformat:
                    self.__create_subvolumes(p, pdisk)
                self.__mount_subvolumes(p, pdisk)
            p['mount'] = pdisk

    def resparse(self, size = None):
        # Can't re-sparse a disk image - too hard
        pass
