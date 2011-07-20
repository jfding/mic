#
#live.py : LiveImageCreator class for creating Live CD images
#
# Copyright 2007, Red Hat  Inc.
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
import re
import time

from micng.utils.errors import *
from micng.utils.fs_related import *
from micng.utils.rpmmisc import *
from BaseImageCreator import LiveImageCreatorBase

class LivecdImageCreator(LiveImageCreatorBase):
    """ImageCreator for x86 machines"""
 
    def _get_mkisofs_options(self, isodir):
        return [ "-b", "isolinux/isolinux.bin",
                 "-c", "isolinux/boot.cat",
                 "-no-emul-boot", "-boot-info-table",
                 "-boot-load-size", "4" ]

    def _get_required_packages(self):
        return ["syslinux", "syslinux-extlinux", "moblin-live"] + LiveImageCreatorBase._get_required_packages(self)

    def _get_isolinux_stanzas(self, isodir):
        return ""

    def __find_syslinux_menu(self):
        for menu in ["vesamenu.c32", "menu.c32"]:
            if os.path.isfile(self._instroot + "/usr/share/syslinux/" + menu):
                return menu

        raise CreatorError("syslinux not installed : "
                           "no suitable /usr/share/syslinux/*menu.c32 found")

    def __find_syslinux_mboot(self):
        #
        # We only need the mboot module if we have any xen hypervisors
        #
        if not glob.glob(self._instroot + "/boot/xen.gz*"):
            return None

        return "mboot.c32"

    def __copy_syslinux_files(self, isodir, menu, mboot = None):
        files = ["isolinux.bin", menu]
        if mboot:
            files += [mboot]

        for f in files:
            path = self._instroot + "/usr/share/syslinux/" + f

            if not os.path.isfile(path):
                raise CreatorError("syslinux not installed : "
                                   "%s not found" % path)

            shutil.copy(path, isodir + "/isolinux/")

    def __copy_syslinux_background(self, isodest):
        background_path = self._instroot + \
                          "/usr/lib/anaconda-runtime/syslinux-vesa-splash.jpg"

        if not os.path.exists(background_path):
            return False

        shutil.copyfile(background_path, isodest)

        return True

    def __copy_kernel_and_initramfs(self, isodir, version, index):
        bootdir = self._instroot + "/boot"

        if self._alt_initrd_name:
            src_initrd_path = os.path.join(bootdir, self._alt_initrd_name)
        else:
            src_initrd_path = os.path.join(bootdir, "initrd-" + version + ".img")

        try:
            shutil.copyfile(bootdir + "/vmlinuz-" + version,
                            isodir + "/isolinux/vmlinuz" + index)
            shutil.copyfile(src_initrd_path,
                            isodir + "/isolinux/initrd" + index + ".img")
        except:
            raise CreatorError("Unable to copy valid kernels or initrds, please check the repo")

        is_xen = False
        if os.path.exists(bootdir + "/xen.gz-" + version[:-3]):
            shutil.copyfile(bootdir + "/xen.gz-" + version[:-3],
                            isodir + "/isolinux/xen" + index + ".gz")
            is_xen = True

        return is_xen

    def __is_default_kernel(self, kernel, kernels):
        if len(kernels) == 1:
            return True

        if kernel == self._default_kernel:
            return True

        if kernel.startswith("kernel-") and kernel[7:] == self._default_kernel:
            return True

        return False

    def __get_basic_syslinux_config(self, **args):
        return """
default %(menu)s
timeout %(timeout)d

%(background)s
menu title Welcome to %(distroname)s!
menu color border 0 #ffffffff #00000000
menu color sel 7 #ffffffff #ff000000
menu color title 0 #ffffffff #00000000
menu color tabmsg 0 #ffffffff #00000000
menu color unsel 0 #ffffffff #00000000
menu color hotsel 0 #ff000000 #ffffffff
menu color hotkey 7 #ffffffff #ff000000
menu color timeout_msg 0 #ffffffff #00000000
menu color timeout 0 #ffffffff #00000000
menu color cmdline 0 #ffffffff #00000000
""" % args

    def __get_image_stanza(self, is_xen, **args):
        if not is_xen:
            template = """label %(short)s
  menu label %(long)s
  kernel vmlinuz%(index)s
  append initrd=initrd%(index)s.img root=CDLABEL=%(fslabel)s rootfstype=iso9660 %(liveargs)s %(extra)s
"""
        else:
            template = """label %(short)s
  menu label %(long)s
  kernel mboot.c32
  append xen%(index)s.gz --- vmlinuz%(index)s root=CDLABEL=%(fslabel)s rootfstype=iso9660 %(liveargs)s %(extra)s --- initrd%(index)s.img
"""
        return template % args

    def __get_image_stanzas(self, isodir):
        versions = []
        kernels = self._get_kernel_versions()
        for kernel in kernels:
            for version in kernels[kernel]:
                versions.append(version)

        if not versions:
            raise CreatorError("Unable to find valid kernels, please check the repo")

        kernel_options = self._get_kernel_options()
        menu_options = self._get_menu_options()


        cfg = ""

        default_version = None
        default_index = None
        index = "0"
        for version in versions:
            is_xen = self.__copy_kernel_and_initramfs(isodir, version, index)

            default = self.__is_default_kernel(kernel, kernels)
            liveinst = False
            autoliveinst = False
            netinst = False
            checkisomd5 = False
            basicinst = False
            
            if menu_options.find("bootinstall") >= 0:
                liveinst = True
            
            if menu_options.find("autoinst") >= 0:
                autoliveinst = True
                
            if menu_options.find("verify") >= 0 and self._has_checkisomd5():
                checkisomd5 = True 
                               
            if menu_options.find("netinst") >= 0:
                netinst = True 
                
            if default:
                long = "Boot %s" % self.distro_name
            elif kernel.startswith("kernel-"):
                long = "Boot %s(%s)" % (self.name, kernel[7:])
            else:
                long = "Boot %s(%s)" % (self.name, kernel)

            cfg += self.__get_image_stanza(is_xen,
                                           fslabel = self.fslabel,
                                           liveargs = kernel_options,
                                           long = long,
                                           short = "linux" + index,
                                           extra = "",
                                           index = index)

            if default:
                cfg += "menu default\n"
                default_version = version
                default_index = index
            if basicinst:
                cfg += self.__get_image_stanza(is_xen,
                                               fslabel = self.fslabel,
                                               liveargs = kernel_options,
                                               long = "Installation Only (Text based)",
                                               short = "basic" + index,
                                               extra = "basic nosplash 4",
                                               index = index)
                
            if liveinst:
                cfg += self.__get_image_stanza(is_xen,
                                               fslabel = self.fslabel,
                                               liveargs = kernel_options,
                                               long = "Installation Only",
                                               short = "liveinst" + index,
                                               extra = "liveinst nosplash 4",
                                               index = index)
            if autoliveinst:
                cfg += self.__get_image_stanza(is_xen,
                                               fslabel = self.fslabel,
                                               liveargs = kernel_options,
                                               long = "Autoinstall (Deletes all existing content)",
                                               short = "autoinst" + index,
                                               extra = "autoinst nosplash 4",
                                               index = index)

            if checkisomd5:
                cfg += self.__get_image_stanza(is_xen,
                                               fslabel = self.fslabel,
                                               liveargs = kernel_options,
                                               long = "Verify and " + long,
                                               short = "check" + index,
                                               extra = "check",
                                               index = index)

            index = str(int(index) + 1)

        if not default_version:
            default_version = versions[0]
        if not default_index:
            default_index = "0"

        
        if netinst:
            cfg += self.__get_image_stanza(is_xen,
                                           fslabel = self.fslabel,
                                           liveargs = kernel_options,
                                           long = "Network Installation",
                                           short = "netinst",
                                           extra = "netinst 4",
                                           index = default_index)

        return cfg

    def __get_memtest_stanza(self, isodir):
        memtest = glob.glob(self._instroot + "/boot/memtest86*")
        if not memtest:
            return ""

        shutil.copyfile(memtest[0], isodir + "/isolinux/memtest")

        return """label memtest
  menu label Memory Test
  kernel memtest
"""

    def __get_local_stanza(self, isodir):
        return """label local
  menu label Boot from local drive
  localboot 0xffff
"""

    def _configure_syslinux_bootloader(self, isodir):
        """configure the boot loader"""
        makedirs(isodir + "/isolinux")

        menu = self.__find_syslinux_menu()

        self.__copy_syslinux_files(isodir, menu,
                                   self.__find_syslinux_mboot())

        background = ""
        if self.__copy_syslinux_background(isodir + "/isolinux/splash.jpg"):
            background = "menu background splash.jpg"

        cfg = self.__get_basic_syslinux_config(menu = menu,
                                               background = background,
                                               name = self.name,
                                               timeout = self._timeout * 10,
                                               distroname = self.distro_name)

        cfg += self.__get_image_stanzas(isodir)
        cfg += self.__get_memtest_stanza(isodir)
        cfg += self.__get_local_stanza(isodir)
        cfg += self._get_isolinux_stanzas(isodir)

        cfgf = open(isodir + "/isolinux/isolinux.cfg", "w")
        cfgf.write(cfg)
        cfgf.close()

    def __copy_efi_files(self, isodir):
        if not os.path.exists(self._instroot + "/boot/efi/EFI/redhat/grub.efi"):
            return False
        shutil.copy(self._instroot + "/boot/efi/EFI/redhat/grub.efi",
                    isodir + "/EFI/boot/grub.efi")
        shutil.copy(self._instroot + "/boot/grub/splash.xpm.gz",
                    isodir + "/EFI/boot/splash.xpm.gz")

        return True

    def __get_basic_efi_config(self, **args):
        return """
default=0
splashimage=/EFI/boot/splash.xpm.gz
timeout %(timeout)d
hiddenmenu

""" %args

    def __get_efi_image_stanza(self, **args):
        return """title %(long)s
  kernel /EFI/boot/vmlinuz%(index)s root=CDLABEL=%(fslabel)s rootfstype=iso9660 %(liveargs)s %(extra)s
  initrd /EFI/boot/initrd%(index)s.img
""" %args

    def __get_efi_image_stanzas(self, isodir, name):
        # FIXME: this only supports one kernel right now...

        kernel_options = self._get_kernel_options()
        checkisomd5 = self._has_checkisomd5()

        cfg = ""

        for index in range(0, 9):
            # we don't support xen kernels
            if os.path.exists("%s/EFI/boot/xen%d.gz" %(isodir, index)):
                continue
            cfg += self.__get_efi_image_stanza(fslabel = self.fslabel,
                                               liveargs = kernel_options,
                                               long = name,
                                               extra = "", index = index)
            if checkisomd5:
                cfg += self.__get_efi_image_stanza(fslabel = self.fslabel,
                                                   liveargs = kernel_options,
                                                   long = "Verify and Boot " + name,
                                                   extra = "check",
                                                   index = index)
            break

        return cfg

    def _configure_efi_bootloader(self, isodir):
        """Set up the configuration for an EFI bootloader"""
        makedirs(isodir + "/EFI/boot")

        if not self.__copy_efi_files(isodir):
            shutil.rmtree(isodir + "/EFI")
            return

        for f in os.listdir(isodir + "/isolinux"):
            os.link("%s/isolinux/%s" %(isodir, f),
                    "%s/EFI/boot/%s" %(isodir, f))


        cfg = self.__get_basic_efi_config(name = self.name,
                                          timeout = self._timeout)
        cfg += self.__get_efi_image_stanzas(isodir, self.name)

        cfgf = open(isodir + "/EFI/boot/grub.conf", "w")
        cfgf.write(cfg)
        cfgf.close()

        # first gen mactel machines get the bootloader name wrong apparently
        if getBaseArch() == "i386":
            os.link(isodir + "/EFI/boot/grub.efi", isodir + "/EFI/boot/boot.efi")
            os.link(isodir + "/EFI/boot/grub.conf", isodir + "/EFI/boot/boot.conf")

        # for most things, we want them named boot$efiarch
        efiarch = {"i386": "ia32", "x86_64": "x64"}
        efiname = efiarch[getBaseArch()]
        os.rename(isodir + "/EFI/boot/grub.efi", isodir + "/EFI/boot/boot%s.efi" %(efiname,))
        os.link(isodir + "/EFI/boot/grub.conf", isodir + "/EFI/boot/boot%s.conf" %(efiname,))


    def _configure_bootloader(self, isodir):
        self._configure_syslinux_bootloader(isodir)
        self._configure_efi_bootloader(isodir)

