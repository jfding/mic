#!/usr/bin/python
from micng.pluginbase.base_plugin import PluginBase
import micng.configmgr as configmgr

class ImagerPlugin(PluginBase):
    plugin_type = "imager"
    def __init__(self, configinfo=None):
        if not configinfo:
            self.configinfo = configmgr.getConfigInfo()
            return 
        self.configinfo = configinfo

    def do_mount_instroot(self):
        """Mount or prepare the install root directory.

        This is the interface where plugin may prepare the install root by e.g.
        mounting creating and loopback mounting a filesystem image to
        _instroot.
        """
        pass

    def do_umount_instroot(self):
        """Undo anything performed in do_mount_instroot().

        This is the interface where plugin must undo anything which was done
        in do_mount_instroot(). For example, if a filesystem image was mounted
        onto _instroot, it should be unmounted here.
        """
        pass

    def do_mount(self):
        """Setup the target filesystem in preparation for an install.

        This interface should setup the filesystem which other functions will
        install into and configure.
        """
        pass

    def do_umount(self):
        """Unmounts the target filesystem.

        It should detache the system from the install root.
        """
        pass

    def do_cleanup(self):
        """Unmounts the target filesystem and deletes temporary files.

        This interface deletes any temporary files and directories that were created
        on the host system while building the image.
        """
        pass

    def do_install(self):
        """Install packages into the install root.

        This interface installs the packages listed in the supplied kickstart
        into the install root. By default, the packages are installed from the
        repository URLs specified in the kickstart.
        """
        pass

    def do_configure(self):
        """Configure the system image according to the kickstart.

        This interface applies the (e.g. keyboard or network) configuration
        specified in the kickstart and executes the kickstart %post scripts.

        If neccessary, it also prepares the image to be bootable by e.g.
        creating an initrd and bootloader configuration.
        """
        pass

    def do_package(self, destdir):
        """Prepares the created image for final delivery.

        This interface merely copies the install root to the supplied destination
        directory,
        """
        pass

    def do_create(self, args):
        """ Temporary solution to create image in one single interface """
        pass

    def pack(self):
        pass

    def unpack(self):
        pass
