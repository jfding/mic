#
# fs.py : Filesystem related utilities and classes
#
# Copyright 2007, Red Hat  Inc.
# Copyright 2009, 2010, 2011  Intel, Inc.
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
import sys
import errno
import stat
import random
import string
import time
import fcntl
import struct
import termios

from errors import *
from mic import msger
import runner

def terminal_width(fd=1):
    """ Get the real terminal width """
    try:
        buf = 'abcdefgh'
        buf = fcntl.ioctl(fd, termios.TIOCGWINSZ, buf)
        return struct.unpack('hhhh', buf)[1]
    except: # IOError
        return 80

def truncate_url(url, width):
    return os.path.basename(url)[0:width]

class TextProgress(object):
    # make the class as singleton
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TextProgress, cls).__new__(cls, *args, **kwargs)

        return cls._instance

    def __init__(self, totalnum = None):
        self.total = totalnum
        self.counter = 1

    def start(self, filename, url, *args, **kwargs):
        self.url = url
        self.termwidth = terminal_width()
        msger.info("\r%-*s" % (self.termwidth, " "))
        if self.total is None:
            msger.info("\rRetrieving %s ..." % truncate_url(self.url, self.termwidth - 15))
        else:
            msger.info("\rRetrieving %s [%d/%d] ..." % (truncate_url(self.url, self.termwidth - 25), self.counter, self.total))

    def update(self, *args):
        pass

    def end(self, *args):
        if self.counter == self.total:
            msger.raw("\n")

        if self.total is not None:
            self.counter += 1

def find_binary_path(binary):
    if os.environ.has_key("PATH"):
        paths = os.environ["PATH"].split(":")
    else:
        paths = []
        if os.environ.has_key("HOME"):
            paths += [os.environ["HOME"] + "/bin"]
        paths += ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"]

    for path in paths:
        bin_path = "%s/%s" % (path, binary)
        if os.path.exists(bin_path):
            return bin_path
    raise CreatorError("Command '%s' is not available." % binary)

def makedirs(dirname):
    """A version of os.makedirs() that doesn't throw an
    exception if the leaf directory already exists.
    """
    try:
        os.makedirs(dirname)
    except OSError, (err, msg):
        if err != errno.EEXIST:
            raise

def mksquashfs(in_img, out_img):
    fullpathmksquashfs = find_binary_path("mksquashfs")
    args = [fullpathmksquashfs, in_img, out_img]

    if not sys.stdout.isatty():
        args.append("-no-progress")

    ret = runner.show(args)
    if ret != 0:
        raise SquashfsError("'%s' exited with error (%d)" % (' '.join(args), ret))

def resize2fs(fs, size):
    resize2fs = find_binary_path("resize2fs")
    if size == 0:
        # it means to minimalize it
        return runner.show([resize2fs, '-M', fs])
    else:
        return runner.show([resize2fs, fs, "%sK" % (size / 1024,)])

def my_fuser(fp):
    fuser = find_binary_path("fuser")
    if not os.path.exists(fp):
        return False

    rc = runner.quiet([fuser, "-s", fp])
    if rc == 0:
        for pid in runner.outs([fuser, fp]).split():
            fd = open("/proc/%s/cmdline" % pid, "r")
            cmdline = fd.read()
            fd.close()
            if cmdline[:-1] == "/bin/bash":
                return True

    # not found
    return False

class BindChrootMount:
    """Represents a bind mount of a directory into a chroot."""
    def __init__(self, src, chroot, dest = None, option = None):
        self.src = src
        self.root = os.path.abspath(os.path.expanduser(chroot))
        self.option = option

        if not dest:
            dest = src
        self.dest = self.root + "/" + dest

        self.mounted = False
        self.mountcmd = find_binary_path("mount")
        self.umountcmd = find_binary_path("umount")

    def ismounted(self):
        with open('/proc/mounts') as f:
            for line in f:
                if line.split()[1] == os.path.abspath(self.dest):
                    return True

        return False

    def has_chroot_instance(self):
        lock = os.path.join(self.root, ".chroot.lock")
        return my_fuser(lock)

    def mount(self):
        if self.mounted or self.ismounted():
            return

        makedirs(self.dest)
        rc = runner.show([self.mountcmd, "--bind", self.src, self.dest])
        if rc != 0:
            raise MountError("Bind-mounting '%s' to '%s' failed" %
                             (self.src, self.dest))
        if self.option:
            rc = runner.show([self.mountcmd, "--bind", "-o", "remount,%s" % self.option, self.dest])
            if rc != 0:
                raise MountError("Bind-remounting '%s' failed" % self.dest)
        self.mounted = True

    def unmount(self):
        if self.has_chroot_instance():
            return

        if self.ismounted():
            runner.show([self.umountcmd, "-l", self.dest])
        self.mounted = False

class LoopbackMount:
    """LoopbackMount  compatibility layer for old API"""
    def __init__(self, lofile, mountdir, fstype = None):
        self.diskmount = DiskMount(LoopbackDisk(lofile,size = 0),mountdir,fstype,rmmountdir = True)
        self.losetup = False
        self.losetupcmd = find_binary_path("losetup")

    def cleanup(self):
        self.diskmount.cleanup()

    def unmount(self):
        self.diskmount.unmount()

    def lounsetup(self):
        if self.losetup:
            runner.show([self.losetupcmd, "-d", self.loopdev])
            self.losetup = False
            self.loopdev = None

    def loopsetup(self):
        if self.losetup:
            return

        rc, losetupOutput  = runner.runtool([self.losetupcmd, "-f"])
        if rc != 0:
            raise MountError("Failed to allocate loop device for '%s'" %
                             self.lofile)

        self.loopdev = losetupOutput.split()[0]

        rc = runner.show([self.losetupcmd, self.loopdev, self.lofile])
        if rc != 0:
            raise MountError("Failed to allocate loop device for '%s'" %
                             self.lofile)

        self.losetup = True

    def mount(self):
        self.diskmount.mount()

class SparseLoopbackMount(LoopbackMount):
    """SparseLoopbackMount  compatibility layer for old API"""
    def __init__(self, lofile, mountdir, size, fstype = None):
        self.diskmount = DiskMount(SparseLoopbackDisk(lofile,size),mountdir,fstype,rmmountdir = True)

    def expand(self, create = False, size = None):
        self.diskmount.disk.expand(create, size)

    def truncate(self, size = None):
        self.diskmount.disk.truncate(size)

    def create(self):
        self.diskmount.disk.create()

class SparseExtLoopbackMount(SparseLoopbackMount):
    """SparseExtLoopbackMount  compatibility layer for old API"""
    def __init__(self, lofile, mountdir, size, fstype, blocksize, fslabel):
        self.diskmount = ExtDiskMount(SparseLoopbackDisk(lofile,size), mountdir, fstype, blocksize, fslabel, rmmountdir = True)


    def __format_filesystem(self):
        self.diskmount.__format_filesystem()

    def create(self):
        self.diskmount.disk.create()

    def resize(self, size = None):
        return self.diskmount.__resize_filesystem(size)

    def mount(self):
        self.diskmount.mount()

    def __fsck(self):
        self.extdiskmount.__fsck()

    def __get_size_from_filesystem(self):
        return self.diskmount.__get_size_from_filesystem()

    def __resize_to_minimal(self):
        return self.diskmount.__resize_to_minimal()

    def resparse(self, size = None):
        return self.diskmount.resparse(size)

class Disk:
    """Generic base object for a disk

    The 'create' method must make the disk visible as a block device - eg
    by calling losetup. For RawDisk, this is obviously a no-op. The 'cleanup'
    method must undo the 'create' operation.
    """
    def __init__(self, size, device = None):
        self._device = device
        self._size = size

    def create(self):
        pass

    def cleanup(self):
        pass

    def get_device(self):
        return self._device
    def set_device(self, path):
        self._device = path
    device = property(get_device, set_device)

    def get_size(self):
        return self._size
    size = property(get_size)


class RawDisk(Disk):
    """A Disk backed by a block device.
    Note that create() is a no-op.
    """
    def __init__(self, size, device):
        Disk.__init__(self, size, device)

    def fixed(self):
        return True

    def exists(self):
        return True

class LoopbackDisk(Disk):
    """A Disk backed by a file via the loop module."""
    def __init__(self, lofile, size):
        Disk.__init__(self, size)
        self.lofile = lofile
        self.losetupcmd = find_binary_path("losetup")

    def fixed(self):
        return False

    def exists(self):
        return os.path.exists(self.lofile)

    def create(self):
        if self.device is not None:
            return

        rc, losetupOutput  = runner.runtool([self.losetupcmd, "-f"])
        if rc != 0:
            raise MountError("Failed to allocate loop device for '%s'" %
                             self.lofile)

        device = losetupOutput.split()[0]

        msger.debug("Losetup add %s mapping to %s"  % (device, self.lofile))
        rc = runner.show([self.losetupcmd, device, self.lofile])
        if rc != 0:
            raise MountError("Failed to allocate loop device for '%s'" %
                             self.lofile)
        self.device = device

    def cleanup(self):
        if self.device is None:
            return
        msger.debug("Losetup remove %s" % self.device)
        rc = runner.show([self.losetupcmd, "-d", self.device])
        self.device = None

class SparseLoopbackDisk(LoopbackDisk):
    """A Disk backed by a sparse file via the loop module."""
    def __init__(self, lofile, size):
        LoopbackDisk.__init__(self, lofile, size)

    def expand(self, create = False, size = None):
        flags = os.O_WRONLY
        if create:
            flags |= os.O_CREAT
            if not os.path.exists(self.lofile):
                makedirs(os.path.dirname(self.lofile))

        if size is None:
            size = self.size

        msger.debug("Extending sparse file %s to %d" % (self.lofile, size))
        if create:
            fd = os.open(self.lofile, flags, 0644)
        else:
            fd = os.open(self.lofile, flags)

        os.lseek(fd, size, os.SEEK_SET)
        os.write(fd, '\x00')
        os.close(fd)

    def truncate(self, size = None):
        if size is None:
            size = self.size

        msger.debug("Truncating sparse file %s to %d" % (self.lofile, size))
        fd = os.open(self.lofile, os.O_WRONLY)
        os.ftruncate(fd, size)
        os.close(fd)

    def create(self):
        self.expand(create = True)
        LoopbackDisk.create(self)

class Mount:
    """A generic base class to deal with mounting things."""
    def __init__(self, mountdir):
        self.mountdir = mountdir

    def cleanup(self):
        self.unmount()

    def mount(self, options = None):
        pass

    def unmount(self):
        pass

class DiskMount(Mount):
    """A Mount object that handles mounting of a Disk."""
    def __init__(self, disk, mountdir, fstype = None, rmmountdir = True):
        Mount.__init__(self, mountdir)

        self.disk = disk
        self.fstype = fstype
        self.rmmountdir = rmmountdir

        self.mounted = False
        self.rmdir   = False
        if fstype:
            self.mkfscmd = find_binary_path("mkfs." + self.fstype)
        else:
            self.mkfscmd = None
        self.mountcmd = find_binary_path("mount")
        self.umountcmd = find_binary_path("umount")

    def cleanup(self):
        Mount.cleanup(self)
        self.disk.cleanup()

    def unmount(self):
        if self.mounted:
            msger.debug("Unmounting directory %s" % self.mountdir)
            runner.quiet('sync') # sync the data on this mount point
            rc = runner.show([self.umountcmd, "-l", self.mountdir])
            if rc == 0:
                self.mounted = False
            else:
                raise MountError("Failed to umount %s" % self.mountdir)
        if self.rmdir and not self.mounted:
            try:
                os.rmdir(self.mountdir)
            except OSError, e:
                pass
            self.rmdir = False


    def __create(self):
        self.disk.create()


    def mount(self, options = None):
        if self.mounted:
            return

        if not os.path.isdir(self.mountdir):
            msger.debug("Creating mount point %s" % self.mountdir)
            os.makedirs(self.mountdir)
            self.rmdir = self.rmmountdir

        self.__create()

        msger.debug("Mounting %s at %s" % (self.disk.device, self.mountdir))
        if options:
            args = [ self.mountcmd, "-o", options, self.disk.device, self.mountdir ]
        else:
            args = [ self.mountcmd, self.disk.device, self.mountdir ]
        if self.fstype:
            args.extend(["-t", self.fstype])

        rc = runner.show(args)
        if rc != 0:
            raise MountError("Failed to mount '%s' to '%s' with command '%s'. Retval: %s" %
                             (self.disk.device, self.mountdir, " ".join(args), rc))

        self.mounted = True

class ExtDiskMount(DiskMount):
    """A DiskMount object that is able to format/resize ext[23] filesystems."""
    def __init__(self, disk, mountdir, fstype, blocksize, fslabel, rmmountdir=True, skipformat = False, fsopts = None):
        DiskMount.__init__(self, disk, mountdir, fstype, rmmountdir)
        self.blocksize = blocksize
        self.fslabel = fslabel.replace("/", "")
        self.uuid  = None
        self.skipformat = skipformat
        self.fsopts = fsopts
        self.dumpe2fs = find_binary_path("dumpe2fs")
        self.tune2fs = find_binary_path("tune2fs")

    def __parse_field(self, output, field):
        for line in output.split("\n"):
            if line.startswith(field + ":"):
                return line[len(field) + 1:].strip()

        raise KeyError("Failed to find field '%s' in output" % field)

    def __format_filesystem(self):
        if self.skipformat:
            msger.debug("Skip filesystem format.")
            return

        msger.verbose("Formating %s filesystem on %s" % (self.fstype, self.disk.device))
        rc = runner.show([self.mkfscmd,
                          "-F", "-L", self.fslabel,
                          "-m", "1", "-b", str(self.blocksize),
                          self.disk.device]) # str(self.disk.size / self.blocksize)])
        if rc != 0:
            raise MountError("Error creating %s filesystem on disk %s" % (self.fstype, self.disk.device))

        out = runner.outs([self.dumpe2fs, '-h', self.disk.device])

        self.uuid = self.__parse_field(out, "Filesystem UUID")
        msger.debug("Tuning filesystem on %s" % self.disk.device)
        runner.show([self.tune2fs, "-c0", "-i0", "-Odir_index", "-ouser_xattr,acl", self.disk.device])

    def __resize_filesystem(self, size = None):
        current_size = os.stat(self.disk.lofile)[stat.ST_SIZE]

        if size is None:
            size = self.disk.size

        if size == current_size:
            return

        if size > current_size:
            self.disk.expand(size)

        self.__fsck()

        resize2fs(self.disk.lofile, size)
        return size

    def __create(self):
        resize = False
        if not self.disk.fixed() and self.disk.exists():
            resize = True

        self.disk.create()

        if resize:
            self.__resize_filesystem()
        else:
            self.__format_filesystem()

    def mount(self, options = None):
        self.__create()
        DiskMount.mount(self, options)

    def __fsck(self):
        msger.info("Checking filesystem %s" % self.disk.lofile)
        runner.quiet(["/sbin/e2fsck", "-f", "-y", self.disk.lofile])

    def __get_size_from_filesystem(self):
        return int(self.__parse_field(runner.outs([self.dumpe2fs, '-h', self.disk.lofile]),
                                      "Block count")) * self.blocksize

    def __resize_to_minimal(self):
        self.__fsck()

        #
        # Use a binary search to find the minimal size
        # we can resize the image to
        #
        bot = 0
        top = self.__get_size_from_filesystem()
        while top != (bot + 1):
            t = bot + ((top - bot) / 2)

            if not resize2fs(self.disk.lofile, t):
                top = t
            else:
                bot = t
        return top

    def resparse(self, size = None):
        self.cleanup()
        if size == 0:
            minsize = 0
        else:
            minsize = self.__resize_to_minimal()
            self.disk.truncate(minsize)

        self.__resize_filesystem(size)
        return minsize

class VfatDiskMount(DiskMount):
    """A DiskMount object that is able to format vfat/msdos filesystems."""
    def __init__(self, disk, mountdir, fstype, blocksize, fslabel, rmmountdir=True, skipformat = False, fsopts = None):
        DiskMount.__init__(self, disk, mountdir, fstype, rmmountdir)
        self.blocksize = blocksize
        self.fslabel = fslabel.replace("/", "")
        self.uuid = "%08X" % int(time.time())
        self.skipformat = skipformat
        self.fsopts = fsopts
        self.fsckcmd = find_binary_path("fsck." + self.fstype)

    def __format_filesystem(self):
        if self.skipformat:
            msger.debug("Skip filesystem format.")
            return

        msger.verbose("Formating %s filesystem on %s" % (self.fstype, self.disk.device))
        rc = runner.show([self.mkfscmd, "-n", self.fslabel, "-i", self.uuid, self.disk.device])
        if rc != 0:
            raise MountError("Error creating %s filesystem on disk %s" % (self.fstype,self.disk.device))

        msger.verbose("Tuning filesystem on %s" % self.disk.device)

    def __resize_filesystem(self, size = None):
        current_size = os.stat(self.disk.lofile)[stat.ST_SIZE]

        if size is None:
            size = self.disk.size

        if size == current_size:
            return

        if size > current_size:
            self.disk.expand(size)

        self.__fsck()

        #resize2fs(self.disk.lofile, size)
        return size

    def __create(self):
        resize = False
        if not self.disk.fixed() and self.disk.exists():
            resize = True

        self.disk.create()

        if resize:
            self.__resize_filesystem()
        else:
            self.__format_filesystem()

    def mount(self, options = None):
        self.__create()
        DiskMount.mount(self, options)

    def __fsck(self):
        msger.debug("Checking filesystem %s" % self.disk.lofile)
        runner.show([self.fsckcmd, "-y", self.disk.lofile])

    def __get_size_from_filesystem(self):
        return self.disk.size

    def __resize_to_minimal(self):
        self.__fsck()

        #
        # Use a binary search to find the minimal size
        # we can resize the image to
        #
        bot = 0
        top = self.__get_size_from_filesystem()
        return top

    def resparse(self, size = None):
        self.cleanup()
        minsize = self.__resize_to_minimal()
        self.disk.truncate(minsize)
        self.__resize_filesystem(size)
        return minsize

class BtrfsDiskMount(DiskMount):
    """A DiskMount object that is able to format/resize btrfs filesystems."""
    def __init__(self, disk, mountdir, fstype, blocksize, fslabel, rmmountdir=True, skipformat = False, fsopts = None):
        self.__check_btrfs()
        DiskMount.__init__(self, disk, mountdir, fstype, rmmountdir)
        self.blocksize = blocksize
        self.fslabel = fslabel.replace("/", "")
        self.uuid  = None
        self.skipformat = skipformat
        self.fsopts = fsopts
        self.blkidcmd = find_binary_path("blkid")
        self.btrfsckcmd = find_binary_path("btrfsck")

    def __check_btrfs(self):
        found = False
        """ Need to load btrfs module to mount it """
        load_module("btrfs")
        for line in open("/proc/filesystems").xreadlines():
            if line.find("btrfs") > -1:
                found = True
                break
        if not found:
            raise MountError("Your system can't mount btrfs filesystem, please make sure your kernel has btrfs support and the module btrfs.ko has been loaded.")

        # disable selinux, selinux will block write
        if os.path.exists("/usr/sbin/setenforce"):
            runner.show(["/usr/sbin/setenforce", "0"])

    def __parse_field(self, output, field):
        for line in output.split(" "):
            if line.startswith(field + "="):
                return line[len(field) + 1:].strip().replace("\"", "")

        raise KeyError("Failed to find field '%s' in output" % field)

    def __format_filesystem(self):
        if self.skipformat:
            msger.debug("Skip filesystem format.")
            return

        msger.verbose("Formating %s filesystem on %s" % (self.fstype, self.disk.device))
        rc = runner.show([self.mkfscmd, "-L", self.fslabel, self.disk.device])
        if rc != 0:
            raise MountError("Error creating %s filesystem on disk %s" % (self.fstype,self.disk.device))

        self.uuid = self.__parse_field(runner.outs([self.blkidcmd, self.disk.device]), "UUID")

    def __resize_filesystem(self, size = None):
        current_size = os.stat(self.disk.lofile)[stat.ST_SIZE]

        if size is None:
            size = self.disk.size

        if size == current_size:
            return

        if size > current_size:
            self.disk.expand(size)

        self.__fsck()
        return size

    def __create(self):
        resize = False
        if not self.disk.fixed() and self.disk.exists():
            resize = True

        self.disk.create()

        if resize:
            self.__resize_filesystem()
        else:
            self.__format_filesystem()

    def mount(self, options = None):
        self.__create()
        DiskMount.mount(self, options)

    def __fsck(self):
        msger.debug("Checking filesystem %s" % self.disk.lofile)
        runner.quiet([self.btrfsckcmd, self.disk.lofile])

    def __get_size_from_filesystem(self):
        return self.disk.size

    def __resize_to_minimal(self):
        self.__fsck()

        return self.__get_size_from_filesystem()

    def resparse(self, size = None):
        self.cleanup()
        minsize = self.__resize_to_minimal()
        self.disk.truncate(minsize)
        self.__resize_filesystem(size)
        return minsize

class DeviceMapperSnapshot(object):
    def __init__(self, imgloop, cowloop):
        self.imgloop = imgloop
        self.cowloop = cowloop

        self.__created = False
        self.__name = None
        self.dmsetupcmd = find_binary_path("dmsetup")

        """Load dm_snapshot if it isn't loaded"""
        load_module("dm_snapshot")

    def get_path(self):
        if self.__name is None:
            return None
        return os.path.join("/dev/mapper", self.__name)
    path = property(get_path)

    def create(self):
        if self.__created:
            return

        self.imgloop.create()
        self.cowloop.create()

        self.__name = "imgcreate-%d-%d" % (os.getpid(),
                                           random.randint(0, 2**16))

        size = os.stat(self.imgloop.lofile)[stat.ST_SIZE]

        table = "0 %d snapshot %s %s p 8" % (size / 512,
                                             self.imgloop.device,
                                             self.cowloop.device)

        args = [self.dmsetupcmd, "create", self.__name, "--table", table]
        if runner.show(args) != 0:
            self.cowloop.cleanup()
            self.imgloop.cleanup()
            raise SnapshotError("Could not create snapshot device using: " + ' '.join(args))

        self.__created = True

    def remove(self, ignore_errors = False):
        if not self.__created:
            return

        time.sleep(2)
        rc = runner.show([self.dmsetupcmd, "remove", self.__name])
        if not ignore_errors and rc != 0:
            raise SnapshotError("Could not remove snapshot device")

        self.__name = None
        self.__created = False

        self.cowloop.cleanup()
        self.imgloop.cleanup()

    def get_cow_used(self):
        if not self.__created:
            return 0

        #
        # dmsetup status on a snapshot returns e.g.
        #   "0 8388608 snapshot 416/1048576"
        # or, more generally:
        #   "A B snapshot C/D"
        # where C is the number of 512 byte sectors in use
        #
        out = runner.outs([self.dmsetupcmd, "status", self.__name])
        try:
            return int((out.split()[3]).split('/')[0]) * 512
        except ValueError:
            raise SnapshotError("Failed to parse dmsetup status: " + out)

def create_image_minimizer(path, image, minimal_size):
    """
    Builds a copy-on-write image which can be used to
    create a device-mapper snapshot of an image where
    the image's filesystem is as small as possible

    The steps taken are:
      1) Create a sparse COW
      2) Loopback mount the image and the COW
      3) Create a device-mapper snapshot of the image
         using the COW
      4) Resize the filesystem to the minimal size
      5) Determine the amount of space used in the COW
      6) Restroy the device-mapper snapshot
      7) Truncate the COW, removing unused space
      8) Create a squashfs of the COW
    """
    imgloop = LoopbackDisk(image, None) # Passing bogus size - doesn't matter

    cowloop = SparseLoopbackDisk(os.path.join(os.path.dirname(path), "osmin"),
                                 64L * 1024L * 1024L)

    snapshot = DeviceMapperSnapshot(imgloop, cowloop)

    try:
        snapshot.create()

        resize2fs(snapshot.path, minimal_size)

        cow_used = snapshot.get_cow_used()
    finally:
        snapshot.remove(ignore_errors = (not sys.exc_info()[0] is None))

    cowloop.truncate(cow_used)

    mksquashfs(cowloop.lofile, path)

    os.unlink(cowloop.lofile)

def load_module(module):
    found = False
    for line in open('/proc/modules').xreadlines():
        if line.startswith("%s " % module):
            found = True
            break
    if not found:
        msger.info("Loading %s..." % module)
        runner.quiet(['modprobe', module])

def myurlgrab(url, filename, proxies, progress_obj = None):
    from pykickstart.urlgrabber.grabber import URLGrabber, URLGrabError

    g = URLGrabber()
    if progress_obj is None:
        progress_obj = TextProgress()

    if url.startswith("file:///"):
        file = url.replace("file://", "")
        if not os.path.exists(file):
            raise CreatorError("URLGrabber error: can't find file %s" % file)
        runner.show(['cp', "-f", file, filename])
    else:
        try:
            filename = g.urlgrab(url = url, filename = filename,
                ssl_verify_host = False, ssl_verify_peer = False,
                proxies = proxies, http_headers = (('Pragma', 'no-cache'),), progress_obj = progress_obj)
        except URLGrabError, e:
            raise CreatorError("URLGrabber error: %s" % url)

    return filename
