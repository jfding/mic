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
import stat
import shutil

from urlgrabber import progress

from mic import kickstart, msger
from mic.utils import fs_related, runner, misc
from mic.utils.partitionedfs import PartitionedMount
from mic.utils.errors import CreatorError, MountError

from baseimager import BaseImageCreator
class RawImageCreator(BaseImageCreator):
    """Installs a system into a file containing a partitioned disk image.

    ApplianceImageCreator is an advanced ImageCreator subclass; a sparse file
    is formatted with a partition table, each partition loopback mounted
    and the system installed into an virtual disk. The disk image can
    subsequently be booted in a virtual machine or accessed with kpartx
    """

    def __init__(self, creatoropts=None, pkgmgr=None, compress_image=None):
        """Initialize a ApplianceImageCreator instance.

            This method takes the same arguments as ImageCreator.__init__()
        """
        BaseImageCreator.__init__(self, creatoropts, pkgmgr)

        self.__instloop = None
        self.__imgdir = None
        self.__disks = {}
        self.__disk_format = "raw"
        self._diskinfo = []
        self.vmem = 512
        self.vcpu = 1
        self.checksum = False
        self.appliance_version = None
        self.appliance_release = None
        self.compress_image = compress_image
        #self.getsource = False
        #self.listpkg = False

        self._dep_checks.extend(["sync", "kpartx", "parted", "extlinux"])

    def configure(self, repodata = None):
        import subprocess
        def chroot():
            os.chroot(self._instroot)
            os.chdir("/")

        if os.path.exists(self._instroot + "/usr/bin/Xorg"):
            subprocess.call(["/bin/chmod", "u+s", "/usr/bin/Xorg"],
                            preexec_fn = chroot)

        BaseImageCreator.configure(self, repodata)

    def _get_fstab(self):
        s = ""
        for mp in self.__instloop.mountOrder:
            p = None
            for p1 in self.__instloop.partitions:
                if p1['mountpoint'] == mp:
                    p = p1
                    break

            s += "%(device)s  %(mountpoint)s  %(fstype)s  %(fsopts)s 0 0\n" % {
               'device': "UUID=%s" % p['uuid'],
               'mountpoint': p['mountpoint'],
               'fstype': p['fstype'],
               'fsopts': "defaults,noatime" if not p['fsopts'] else p['fsopts']}

            if p['mountpoint'] == "/":
                for subvol in self.__instloop.subvolumes:
                    if subvol['mountpoint'] == "/":
                        continue
                    s += "%(device)s  %(mountpoint)s  %(fstype)s  %(fsopts)s 0 0\n" % {
                         'device': "/dev/%s%-d" % (p['disk'], p['num']),
                         'mountpoint': subvol['mountpoint'],
                         'fstype': p['fstype'],
                         'fsopts': "defaults,noatime" if not subvol['fsopts'] else subvol['fsopts']}

        s += "devpts     /dev/pts  devpts  gid=5,mode=620   0 0\n"
        s += "tmpfs      /dev/shm  tmpfs   defaults         0 0\n"
        s += "proc       /proc     proc    defaults         0 0\n"
        s += "sysfs      /sys      sysfs   defaults         0 0\n"
        return s

    def _create_mkinitrd_config(self):
        """write to tell which modules to be included in initrd"""

        mkinitrd = ""
        mkinitrd += "PROBE=\"no\"\n"
        mkinitrd += "MODULES+=\"ext3 ata_piix sd_mod libata scsi_mod\"\n"
        mkinitrd += "rootfs=\"ext3\"\n"
        mkinitrd += "rootopts=\"defaults\"\n"

        msger.debug("Writing mkinitrd config %s/etc/sysconfig/mkinitrd" \
                    % self._instroot)
        os.makedirs(self._instroot + "/etc/sysconfig/",mode=644)
        cfg = open(self._instroot + "/etc/sysconfig/mkinitrd", "w")
        cfg.write(mkinitrd)
        cfg.close()

    def _get_parts(self):
        if not self.ks:
            raise CreatorError("Failed to get partition info, "
                               "please check your kickstart setting.")

        # Set a default partition if no partition is given out
        if not self.ks.handler.partition.partitions:
            partstr = "part / --size 1900 --ondisk sda --fstype=ext3"
            args = partstr.split()
            pd = self.ks.handler.partition.parse(args[1:])
            if pd not in self.ks.handler.partition.partitions:
                self.ks.handler.partition.partitions.append(pd)

        # partitions list from kickstart file
        return kickstart.get_partitions(self.ks)

    def get_diskinfo(self):

        if self._diskinfo:
            return self._diskinfo

        #get partition info from ks handler
        parts = self._get_parts()

        for i in range(len(parts)):
            if parts[i].disk:
                disk = parts[i].disk
            else:
                raise CreatorError("Failed to create disks, no --ondisk "
                                   "specified in partition line of ks file")

            if not parts[i].fstype:
                 raise CreatorError("Failed to create disks, no --fstype "
                                    "specified in partition line of ks file")

            size =   parts[i].size * 1024L * 1024L

            # If we have alignment set for partition we need to enlarge the
            # drive, so that the alignment changes fits there as well
            if parts[i].align:
                size += parts[i].align * 1024L

            found = False
            for j in range(len(self._diskinfo)):
                if self._diskinfo[j]['name'] == disk:
                    self._diskinfo[j]['size'] = self._diskinfo[j]['size'] + size
                    found = True
                    break
                else:
                    found = False

            if not found:
                self._diskinfo.append({ 'name': disk, 'size': size })

        return self._diskinfo

    #
    # Actual implemention
    #
    def _mount_instroot(self, base_on = None):
        self.__imgdir = self._mkdtemp()

        parts = self._get_parts()

        #create disk
        for item in self.get_diskinfo():
            msger.debug("Adding disk %s as %s/%s-%s.raw with size %s bytes" %
                        (item['name'], self.__imgdir, self.name, item['name'],
                         item['size']))

            disk = fs_related.SparseLoopbackDisk("%s/%s-%s.raw" % (
                                                                self.__imgdir,
                                                                self.name,
                                                                item['name']),
                                                 item['size'])
            self.__disks[item['name']] = disk

        self.__instloop = PartitionedMount(self.__disks, self._instroot)

        for p in parts:
            self.__instloop.add_partition(int(p.size),
                                          p.disk,
                                          p.mountpoint,
                                          p.fstype,
                                          p.label,
                                          fsopts = p.fsopts,
                                          boot = p.active,
                                          align = p.align)

        self.__instloop.mount()
        self._create_mkinitrd_config()

    def _get_required_packages(self):
        required_packages = BaseImageCreator._get_required_packages(self)
        if not self.target_arch or not self.target_arch.startswith("arm"):
            required_packages += ["syslinux", "syslinux-extlinux"]
        return required_packages

    def _get_excluded_packages(self):
        return BaseImageCreator._get_excluded_packages(self)

    def _get_syslinux_boot_config(self):
        bootdevnum = None
        rootdevnum = None
        rootdev = None
        for p in self.__instloop.partitions:
            if p['mountpoint'] == "/boot":
                bootdevnum = p['num'] - 1
            elif p['mountpoint'] == "/" and bootdevnum is None:
                bootdevnum = p['num'] - 1

            if p['mountpoint'] == "/":
                rootdevnum = p['num'] - 1
                rootdev = "/dev/%s%-d" % (p['disk'], p['num'])

        prefix = ""
        if bootdevnum == rootdevnum:
            prefix = "/boot"

        return (bootdevnum, rootdevnum, rootdev, prefix)

    def _create_syslinux_config(self):
        #Copy splash
        splash = "%s/usr/lib/anaconda-runtime/syslinux-vesa-splash.jpg" \
                 % self._instroot

        if os.path.exists(splash):
            shutil.copy(splash, "%s%s/splash.jpg" \
                                % (self._instroot, "/boot/extlinux"))
            splashline = "menu background splash.jpg"
        else:
            splashline = ""

        (bootdevnum, rootdevnum, rootdev, prefix) = \
                                            self._get_syslinux_boot_config()
        options = self.ks.handler.bootloader.appendLine

        #XXX don't hardcode default kernel - see livecd code
        syslinux_conf = ""
        syslinux_conf += "prompt 0\n"
        syslinux_conf += "timeout 1\n"
        syslinux_conf += "\n"
        syslinux_conf += "default vesamenu.c32\n"
        syslinux_conf += "menu autoboot Starting %s...\n" % self.distro_name
        syslinux_conf += "menu hidden\n"
        syslinux_conf += "\n"
        syslinux_conf += "%s\n" % splashline
        syslinux_conf += "menu title Welcome to %s!\n" % self.distro_name
        syslinux_conf += "menu color border 0 #ffffffff #00000000\n"
        syslinux_conf += "menu color sel 7 #ffffffff #ff000000\n"
        syslinux_conf += "menu color title 0 #ffffffff #00000000\n"
        syslinux_conf += "menu color tabmsg 0 #ffffffff #00000000\n"
        syslinux_conf += "menu color unsel 0 #ffffffff #00000000\n"
        syslinux_conf += "menu color hotsel 0 #ff000000 #ffffffff\n"
        syslinux_conf += "menu color hotkey 7 #ffffffff #ff000000\n"
        syslinux_conf += "menu color timeout_msg 0 #ffffffff #00000000\n"
        syslinux_conf += "menu color timeout 0 #ffffffff #00000000\n"
        syslinux_conf += "menu color cmdline 0 #ffffffff #00000000\n"

        versions = []
        kernels = self._get_kernel_versions()
        symkern = "%s/boot/vmlinuz" % self._instroot

        if os.path.lexists(symkern):
            v = os.path.realpath(symkern).replace('%s-' % symkern, "")
            syslinux_conf += "label %s\n" % self.distro_name.lower()
            syslinux_conf += "\tmenu label %s (%s)\n" % (self.distro_name, v)
            syslinux_conf += "\tlinux /vmlinuz\n"
            syslinux_conf += "\tappend ro root=%s %s\n" % (rootdev, options)
            syslinux_conf += "\tmenu default\n"
        else:
            for kernel in kernels:
                for version in kernels[kernel]:
                    versions.append(version)

            footlabel = 0
            for v in versions:
                shutil.copy("%s/boot/vmlinuz-%s" %(self._instroot, v),
                            "%s%s/vmlinuz-%s" % (self._instroot,
                                                 "/boot/extlinux/", v))
                syslinux_conf += "label %s%d\n" \
                                 % (self.distro_name.lower(), footlabel)
                syslinux_conf += "\tmenu label %s (%s)\n" % (self.distro_name, v)
                syslinux_conf += "\tlinux vmlinuz-%s\n" % v
                syslinux_conf += "\tappend ro root=%s %s\n" \
                                 % (rootdev, options)
                if footlabel == 0:
                    syslinux_conf += "\tmenu default\n"
                footlabel += 1;

        msger.debug("Writing syslinux config %s/boot/extlinux/extlinux.conf" \
                    % self._instroot)
        cfg = open(self._instroot + "/boot/extlinux/extlinux.conf", "w")
        cfg.write(syslinux_conf)
        cfg.close()

    def _install_syslinux(self):
        i = 0
        for name in self.__disks.keys():
            loopdev = self.__disks[name].device
            i =i+1

        msger.debug("Installing syslinux bootloader to %s" % loopdev)

        (bootdevnum, rootdevnum, rootdev, prefix) = \
                                    self._get_syslinux_boot_config()


        #Set MBR
        mbrsize = os.stat("%s/usr/share/syslinux/mbr.bin" \
                          % self._instroot)[stat.ST_SIZE]
        rc = runner.show(['dd',
                          'if=%s/usr/share/syslinux/mbr.bin' % self._instroot,
                          'of=' + loopdev])
        if rc != 0:
            raise MountError("Unable to set MBR to %s" % loopdev)

        #Set Bootable flag
        parted = fs_related.find_binary_path("parted")
        rc = runner.quiet([parted,
                           "-s",
                           loopdev,
                           "set",
                           "%d" % (bootdevnum + 1),
                           "boot",
                           "on"])
        #XXX disabled return code check because parted always fails to
        #reload part table with loop devices. Annoying because we can't
        #distinguish this failure from real partition failures :-(
        if rc != 0 and 1 == 0:
            raise MountError("Unable to set bootable flag to %sp%d" \
                             % (loopdev, (bootdevnum + 1)))

        #Ensure all data is flushed to disk before doing syslinux install
        runner.quiet('sync')

        fullpathsyslinux = fs_related.find_binary_path("extlinux")
        rc = runner.show([fullpathsyslinux,
                          "-i",
                          "%s/boot/extlinux" % self._instroot])
        if rc != 0:
            raise MountError("Unable to install syslinux bootloader to %sp%d" \
                             % (loopdev, (bootdevnum + 1)))

    def _create_bootconfig(self):
        #If syslinux is available do the required configurations.
        if os.path.exists("%s/usr/share/syslinux/" % (self._instroot)) \
           and os.path.exists("%s/boot/extlinux/" % (self._instroot)):
            self._create_syslinux_config()
            self._install_syslinux()

    def _unmount_instroot(self):
        if not self.__instloop is None:
            self.__instloop.cleanup()

    def _resparse(self, size = None):
        return self.__instloop.resparse(size)

    def _stage_final_image(self):
        """Stage the final system image in _outdir.
           write meta data
        """
        self._resparse()

        if self.compress_image:
            for imgfile in os.listdir(self.__imgdir):
                if imgfile.endswith('.raw') or imgfile.endswith('bin'):
                    imgpath = os.path.join(self.__imgdir, imgfile)
                    misc.compressing(imgpath, self.compress_image)

        if self.pack_to:
            dst = os.path.join(self._outdir, self.pack_to)
            msger.info("Pack all raw images to %s" % dst)
            misc.packing(dst, self.__imgdir)
        else:
            msger.debug("moving disks to stage location")
	    for imgfile in os.listdir(self.__imgdir):
                src = os.path.join(self.__imgdir, imgfile)
                dst = os.path.join(self._outdir, imgfile)
                msger.debug("moving %s to %s" % (src,dst))
                shutil.move(src,dst)
        self._write_image_xml()

    def _write_image_xml(self):
        imgarch = "i686"
        if self.target_arch and self.target_arch.startswith("arm"):
            imgarch = "arm"
        xml = "<image>\n"

        name_attributes = ""
        if self.appliance_version:
            name_attributes += " version='%s'" % self.appliance_version
        if self.appliance_release:
            name_attributes += " release='%s'" % self.appliance_release
        xml += "  <name%s>%s</name>\n" % (name_attributes, self.name)
        xml += "  <domain>\n"
        # XXX don't hardcode - determine based on the kernel we installed for
        # grub baremetal vs xen
        xml += "    <boot type='hvm'>\n"
        xml += "      <guest>\n"
        xml += "        <arch>%s</arch>\n" % imgarch
        xml += "      </guest>\n"
        xml += "      <os>\n"
        xml += "        <loader dev='hd'/>\n"
        xml += "      </os>\n"

        i = 0
        for name in self.__disks.keys():
            xml += "      <drive disk='%s-%s.%s' target='hd%s'/>\n" \
                   % (self.name,name, self.__disk_format,chr(ord('a')+i))
            i = i + 1

        xml += "    </boot>\n"
        xml += "    <devices>\n"
        xml += "      <vcpu>%s</vcpu>\n" % self.vcpu
        xml += "      <memory>%d</memory>\n" %(self.vmem * 1024)
        for network in self.ks.handler.network.network:
            xml += "      <interface/>\n"
        xml += "      <graphics/>\n"
        xml += "    </devices>\n"
        xml += "  </domain>\n"
        xml += "  <storage>\n"

        if self.checksum is True:
            for name in self.__disks.keys():
                diskpath = "%s/%s-%s.%s" \
                           % (self._outdir,self.name,name, self.__disk_format)
                disk_size = os.path.getsize(diskpath)
                meter_ct = 0
                meter = progress.TextMeter()
                meter.start(size=disk_size,
                            text="Generating disk signature for %s-%s.%s" \
                                 % (self.name,
                                    name,
                                    self.__disk_format))
                xml += "    <disk file='%s-%s.%s' use='system' format='%s'>\n"\
                       % (self.name,
                          name,
                          self.__disk_format,
                          self.__disk_format)

                try:
                    import hashlib
                    m1 = hashlib.sha1()
                    m2 = hashlib.sha256()
                except:
                    import sha
                    m1 = sha.new()
                    m2 = None
                f = open(diskpath,"r")
                while 1:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    m1.update(chunk)
                    if m2:
                       m2.update(chunk)
                    meter.update(meter_ct)
                    meter_ct = meter_ct + 65536

                sha1checksum = m1.hexdigest()
                xml +=  "      <checksum type='sha1'>%s</checksum>\n" \
                        % sha1checksum

                if m2:
                    sha256checksum = m2.hexdigest()
                    xml += "      <checksum type='sha256'>%s</checksum>\n" \
                           % sha256checksum

                xml += "    </disk>\n"
        else:
            for name in self.__disks.keys():
                xml += "    <disk file='%s-%s.%s' use='system' format='%s'/>\n"\
                       %(self.name,
                         name,
                         self.__disk_format,
                         self.__disk_format)

        xml += "  </storage>\n"
        xml += "</image>\n"

        msger.debug("writing image XML to %s/%s.xml" %(self._outdir, self.name))
        cfg = open("%s/%s.xml" % (self._outdir, self.name), "w")
        cfg.write(xml)
        cfg.close()
