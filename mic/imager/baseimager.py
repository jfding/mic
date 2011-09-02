#
# creator.py : ImageCreator and LoopImageCreator base classes
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

import os, sys
import stat
import tempfile
import shutil
import subprocess
import re
import tarfile
import glob

import rpm

from mic.utils.errors import CreatorError
from mic.utils.misc import get_filesystem_avail, is_statically_linked,setup_qemu_emulator, create_release
from mic.utils.fs_related import find_binary_path, makedirs, BindChrootMount
from mic.utils import rpmmisc
from mic import kickstart
from mic import msger

class BaseImageCreator(object):
    """Installs a system to a chroot directory.

    ImageCreator is the simplest creator class available; it will install and
    configure a system image according to the supplied kickstart file.

    e.g.

      import mic.imgcreate as imgcreate
      ks = imgcreate.read_kickstart("foo.ks")
      imgcreate.ImageCreator(ks, "foo").create()

    """

    def __init__(self, createopts = None, pkgmgr = None):
        """Initialize an ImageCreator instance.

        ks -- a pykickstart.KickstartParser instance; this instance will be
              used to drive the install by e.g. providing the list of packages
              to be installed, the system configuration and %post scripts

        name -- a name for the image; used for e.g. image filenames or
                filesystem labels

        """
        self.pkgmgr = pkgmgr

        if createopts:
            # A pykickstart.KickstartParser instance."""
            self.ks = createopts['ks']
            self.repometadata = createopts['repomd']

            # A name for the image."""
            self.name = createopts['name']

            # The directory in which all temporary files will be created."""
            self.tmpdir = createopts['tmpdir']

            self.cachedir = createopts['cachedir']

            self.destdir = createopts['outdir']
            # target arch for non-x86 image
            self.target_arch = createopts['arch']
            self._local_pkgs_path = createopts['local_pkgs_path']

        else:
            self.ks = None
            self.repometadata = None
            self.name = "target"
            self.tmpdir = "/var/tmp/mic"
            self.cachedir = "/var/tmp/mic/cache"
            self.destdir = "."
            self.target_arch = None
            self._local_pkgs_path = None

        self.__builddir = None
        self.__bindmounts = []

        self._dep_checks = ["ls", "bash", "cp", "echo", "modprobe", "passwd"]

        #FIXME to be obsolete
        self.distro_name = "MeeGo"

        # Output image file names"""
        self.outimage = []

        # A flag to generate checksum"""
        self._genchecksum = False

        self._alt_initrd_name = None

        # the disk image after creation, e.g., bz2.
        # This value is set with compression_method function. """
        self.__img_compression_method = None

        self._recording_pkgs = None
        self._include_src = None

        # available size in root fs, init to 0
        self._root_fs_avail = 0

        # Name of the disk image file that is created. """
        self._img_name = None

        self.image_format = None

        # Save qemu emulator file name in order to clean up it finally """
        self.qemu_emulator = None

        # No ks provided when called by convertor, so skip the dependency check """
        if self.ks:
            # If we have btrfs partition we need to check that we have toosl for those """
            for part in self.ks.handler.partition.partitions:
                if part.fstype and part.fstype == "btrfs":
                    self._dep_checks.append("mkfs.btrfs")
                    break

        # make sure the specified tmpdir and cachedir exist
        if not os.path.exists(self.tmpdir):
            makedirs(self.tmpdir)
        if not os.path.exists(self.cachedir):
            makedirs(self.cachedir)

    def set_target_arch(self, arch):
        if arch not in rpmmisc.arches:
            return False

        self.target_arch = arch
        if self.target_arch.startswith("arm"):
            for dep in self._dep_checks:
                if dep == "extlinux":
                    self._dep_checks.remove(dep)

            if not os.path.exists("/usr/bin/qemu-arm") or not is_statically_linked("/usr/bin/qemu-arm"):
                self._dep_checks.append("qemu-arm-static")

            if os.path.exists("/proc/sys/vm/vdso_enabled"):
                vdso_fh = open("/proc/sys/vm/vdso_enabled","r")
                vdso_value = vdso_fh.read().strip()
                vdso_fh.close()
                if (int)(vdso_value) == 1:
                    msger.warning("vdso is enabled on your host, which might cause problems with arm emulations.\n"
                                  "\tYou can disable vdso with following command before starting image build:\n"
                                  "\techo 0 | sudo tee /proc/sys/vm/vdso_enabled")

        return True


    def __del__(self):
        self.cleanup()

    #
    # Properties
    #
    def __get_instroot(self):
        if self.__builddir is None:
            raise CreatorError("_instroot is not valid before calling mount()")
        return self.__builddir + "/install_root"
    _instroot = property(__get_instroot)
    """The location of the install root directory.

    This is the directory into which the system is installed. Subclasses may
    mount a filesystem image here or copy files to/from here.

    Note, this directory does not exist before ImageCreator.mount() is called.

    Note also, this is a read-only attribute.

    """

    def __get_outdir(self):
        if self.__builddir is None:
            raise CreatorError("_outdir is not valid before calling mount()")
        return self.__builddir + "/out"
    _outdir = property(__get_outdir)
    """The staging location for the final image.

    This is where subclasses should stage any files that are part of the final
    image. ImageCreator.package() will copy any files found here into the
    requested destination directory.

    Note, this directory does not exist before ImageCreator.mount() is called.

    Note also, this is a read-only attribute.

    """

    #
    # Hooks for subclasses
    #
    def _mount_instroot(self, base_on = None):
        """Mount or prepare the install root directory.

        This is the hook where subclasses may prepare the install root by e.g.
        mounting creating and loopback mounting a filesystem image to
        _instroot.

        There is no default implementation.

        base_on -- this is the value passed to mount() and can be interpreted
                   as the subclass wishes; it might e.g. be the location of
                   a previously created ISO containing a system image.

        """
        pass

    def _unmount_instroot(self):
        """Undo anything performed in _mount_instroot().

        This is the hook where subclasses must undo anything which was done
        in _mount_instroot(). For example, if a filesystem image was mounted
        onto _instroot, it should be unmounted here.

        There is no default implementation.

        """
        pass

    def _create_bootconfig(self):
        """Configure the image so that it's bootable.

        This is the hook where subclasses may prepare the image for booting by
        e.g. creating an initramfs and bootloader configuration.

        This hook is called while the install root is still mounted, after the
        packages have been installed and the kickstart configuration has been
        applied, but before the %post scripts have been executed.

        There is no default implementation.

        """
        pass

    def _stage_final_image(self):
        """Stage the final system image in _outdir.

        This is the hook where subclasses should place the image in _outdir
        so that package() can copy it to the requested destination directory.

        By default, this moves the install root into _outdir.

        """
        shutil.move(self._instroot, self._outdir + "/" + self.name)

    def get_installed_packages(self):
        return self._pkgs_content.keys()

    def _save_recording_pkgs(self, destdir):
        """Save the list or content of installed packages to file.
        """
        if self._recording_pkgs not in ('content', 'name'):
            return

        pkgs = self._pkgs_content.keys()
        pkgs.sort() # inplace op

        # save package name list anyhow
        if not os.path.exists(destdir):
            makedirs(destdir)

        namefile = os.path.join(destdir, self.name + '-pkgs.txt')
        f = open(namefile, "w")
        content = '\n'.join(pkgs)
        f.write(content)
        f.close()
        self.outimage.append(namefile);

        # if 'content', save more details
        if self._recording_pkgs == 'content':
            contfile = os.path.join(destdir, self.name + '-pkgs-content.txt')
            f = open(contfile, "w")

            for pkg in pkgs:
                content = pkg + '\n'

                pkgcont = self._pkgs_content[pkg]
                items = []
                if pkgcont.has_key('dir'):
                    items = map(lambda x:x+'/', pkgcont['dir'])
                if pkgcont.has_key('file'):
                    items.extend(pkgcont['file'])

                if items:
                    content += '    '
                    content += '\n    '.join(items)
                    content += '\n'

                content += '\n'
                f.write(content)
            f.close()
            self.outimage.append(contfile)

    def _get_required_packages(self):
        """Return a list of required packages.

        This is the hook where subclasses may specify a set of packages which
        it requires to be installed.

        This returns an empty list by default.

        Note, subclasses should usually chain up to the base class
        implementation of this hook.

        """
        return []

    def _get_excluded_packages(self):
        """Return a list of excluded packages.

        This is the hook where subclasses may specify a set of packages which
        it requires _not_ to be installed.

        This returns an empty list by default.

        Note, subclasses should usually chain up to the base class
        implementation of this hook.

        """
        excluded_packages = []
        for rpm_path in self._get_local_packages():
            rpm_name = os.path.basename(rpm_path)
            package_name = rpmmisc.splitFilename(rpm_name)[0]
            excluded_packages += [package_name]
        return excluded_packages

    def _get_local_packages(self):
        """Return a list of rpm path to be local installed.

        This is the hook where subclasses may specify a set of rpms which
        it requires to be installed locally.

        This returns an empty list by default.

        Note, subclasses should usually chain up to the base class
        implementation of this hook.

        """
        if self._local_pkgs_path:
            if os.path.isdir(self._local_pkgs_path):
                return glob.glob(
                        os.path.join(self._local_pkgs_path, '*.rpm'))
            elif os.path.splitext(self._local_pkgs_path)[-1] == '.rpm':
                return [self._local_pkgs_path]

        return []

    def _get_fstab(self):
        """Return the desired contents of /etc/fstab.

        This is the hook where subclasses may specify the contents of
        /etc/fstab by returning a string containing the desired contents.

        A sensible default implementation is provided.

        """
        s =  "/dev/root  /         %s    %s 0 0\n" % (self._fstype, "defaults,noatime" if not self._fsopts else self._fsopts)
        s += self._get_fstab_special()
        return s

    def _get_fstab_special(self):
        s = "devpts     /dev/pts  devpts  gid=5,mode=620   0 0\n"
        s += "tmpfs      /dev/shm  tmpfs   defaults         0 0\n"
        s += "proc       /proc     proc    defaults         0 0\n"
        s += "sysfs      /sys      sysfs   defaults         0 0\n"
        return s

    def _get_post_scripts_env(self, in_chroot):
        """Return an environment dict for %post scripts.

        This is the hook where subclasses may specify some environment
        variables for %post scripts by return a dict containing the desired
        environment.

        By default, this returns an empty dict.

        in_chroot -- whether this %post script is to be executed chroot()ed
                     into _instroot.

        """
        return {}

    def __get_imgname(self):
        return self.name
    _name = property(__get_imgname)
    """The name of the image file.

    """

    def _get_kernel_versions(self):
        """Return a dict detailing the available kernel types/versions.

        This is the hook where subclasses may override what kernel types and
        versions should be available for e.g. creating the booloader
        configuration.

        A dict should be returned mapping the available kernel types to a list
        of the available versions for those kernels.

        The default implementation uses rpm to iterate over everything
        providing 'kernel', finds /boot/vmlinuz-* and returns the version
        obtained from the vmlinuz filename. (This can differ from the kernel
        RPM's n-v-r in the case of e.g. xen)

        """
        def get_kernel_versions(instroot):
            ret = {}
            versions = set()
            files = glob.glob(instroot + "/boot/vmlinuz-*")
            for file in files:
                version = os.path.basename(file)[8:]
                if version is None:
                    continue
                versions.add(version)
            ret["kernel"] = list(versions)
            return ret

        def get_version(header):
            version = None
            for f in header['filenames']:
                if f.startswith('/boot/vmlinuz-'):
                    version = f[14:]
            return version

        if self.ks is None:
            return get_kernel_versions(self._instroot)

        ts = rpm.TransactionSet(self._instroot)

        ret = {}
        for header in ts.dbMatch('provides', 'kernel'):
            version = get_version(header)
            if version is None:
                continue

            name = header['name']
            if not name in ret:
                ret[name] = [version]
            elif not version in ret[name]:
                ret[name].append(version)

        return ret

    #
    # Helpers for subclasses
    #
    def _do_bindmounts(self):
        """Mount various system directories onto _instroot.

        This method is called by mount(), but may also be used by subclasses
        in order to re-mount the bindmounts after modifying the underlying
        filesystem.

        """
        for b in self.__bindmounts:
            b.mount()

    def _undo_bindmounts(self):
        """Unmount the bind-mounted system directories from _instroot.

        This method is usually only called by unmount(), but may also be used
        by subclasses in order to gain access to the filesystem obscured by
        the bindmounts - e.g. in order to create device nodes on the image
        filesystem.

        """
        self.__bindmounts.reverse()
        for b in self.__bindmounts:
            b.unmount()

    def _chroot(self):
        """Chroot into the install root.

        This method may be used by subclasses when executing programs inside
        the install root e.g.

          subprocess.call(["/bin/ls"], preexec_fn = self.chroot)

        """
        os.chroot(self._instroot)
        os.chdir("/")

    def _mkdtemp(self, prefix = "tmp-"):
        """Create a temporary directory.

        This method may be used by subclasses to create a temporary directory
        for use in building the final image - e.g. a subclass might create
        a temporary directory in order to bundle a set of files into a package.

        The subclass may delete this directory if it wishes, but it will be
        automatically deleted by cleanup().

        The absolute path to the temporary directory is returned.

        Note, this method should only be called after mount() has been called.

        prefix -- a prefix which should be used when creating the directory;
                  defaults to "tmp-".

        """
        self.__ensure_builddir()
        return tempfile.mkdtemp(dir = self.__builddir, prefix = prefix)

    def _mkstemp(self, prefix = "tmp-"):
        """Create a temporary file.

        This method may be used by subclasses to create a temporary file
        for use in building the final image - e.g. a subclass might need
        a temporary location to unpack a compressed file.

        The subclass may delete this file if it wishes, but it will be
        automatically deleted by cleanup().

        A tuple containing a file descriptor (returned from os.open() and the
        absolute path to the temporary directory is returned.

        Note, this method should only be called after mount() has been called.

        prefix -- a prefix which should be used when creating the file;
                  defaults to "tmp-".

        """
        self.__ensure_builddir()
        return tempfile.mkstemp(dir = self.__builddir, prefix = prefix)

    def _mktemp(self, prefix = "tmp-"):
        """Create a temporary file.

        This method simply calls _mkstemp() and closes the returned file
        descriptor.

        The absolute path to the temporary file is returned.

        Note, this method should only be called after mount() has been called.

        prefix -- a prefix which should be used when creating the file;
                  defaults to "tmp-".

        """

        (f, path) = self._mkstemp(prefix)
        os.close(f)
        return path

    #
    # Actual implementation
    #
    def __ensure_builddir(self):
        if not self.__builddir is None:
            return

        try:
            self.__builddir = tempfile.mkdtemp(dir = self.tmpdir,
                                               prefix = "imgcreate-")
        except OSError, (err, msg):
            raise CreatorError("Failed create build directory in %s: %s" %
                               (self.tmpdir, msg))

    def get_cachedir(self, cachedir = None):
        if self.cachedir:
            return self.cachedir

        self.__ensure_builddir()
        if cachedir:
            self.cachedir = cachedir
        else:
            self.cachedir = self.__builddir + "/yum-cache"
        makedirs(self.cachedir)
        return self.cachedir

    def __sanity_check(self):
        """Ensure that the config we've been given is sane."""
        if not (kickstart.get_packages(self.ks) or
                kickstart.get_groups(self.ks)):
            raise CreatorError("No packages or groups specified")

        kickstart.convert_method_to_repo(self.ks)

        if not kickstart.get_repos(self.ks):
            raise CreatorError("No repositories specified")

    def __write_fstab(self):
        fstab = open(self._instroot + "/etc/fstab", "w")
        fstab.write(self._get_fstab())
        fstab.close()

    def __create_minimal_dev(self):
        """Create a minimal /dev so that we don't corrupt the host /dev"""
        origumask = os.umask(0000)
        devices = (('null',   1, 3, 0666),
                   ('urandom',1, 9, 0666),
                   ('random', 1, 8, 0666),
                   ('full',   1, 7, 0666),
                   ('ptmx',   5, 2, 0666),
                   ('tty',    5, 0, 0666),
                   ('zero',   1, 5, 0666))
        links = (("/proc/self/fd", "/dev/fd"),
                 ("/proc/self/fd/0", "/dev/stdin"),
                 ("/proc/self/fd/1", "/dev/stdout"),
                 ("/proc/self/fd/2", "/dev/stderr"))

        for (node, major, minor, perm) in devices:
            if not os.path.exists(self._instroot + "/dev/" + node):
                os.mknod(self._instroot + "/dev/" + node, perm | stat.S_IFCHR, os.makedev(major,minor))
        for (src, dest) in links:
            if not os.path.exists(self._instroot + dest):
                os.symlink(src, self._instroot + dest)
        os.umask(origumask)


    def mount(self, base_on = None, cachedir = None):
        """Setup the target filesystem in preparation for an install.

        This function sets up the filesystem which the ImageCreator will
        install into and configure. The ImageCreator class merely creates an
        install root directory, bind mounts some system directories (e.g. /dev)
        and writes out /etc/fstab. Other subclasses may also e.g. create a
        sparse file, format it and loopback mount it to the install root.

        base_on -- a previous install on which to base this install; defaults
                   to None, causing a new image to be created

        cachedir -- a directory in which to store the Yum cache; defaults to
                    None, causing a new cache to be created; by setting this
                    to another directory, the same cache can be reused across
                    multiple installs.

        """
        self.__ensure_builddir()

        makedirs(self._instroot)
        makedirs(self._outdir)

        self._mount_instroot(base_on)

        for d in ("/dev/pts", "/etc", "/boot", "/var/log", "/var/cache/yum", "/sys", "/proc", "/usr/bin"):
            makedirs(self._instroot + d)

        if self.target_arch and self.target_arch.startswith("arm"):
            self.qemu_emulator = setup_qemu_emulator(self._instroot, self.target_arch)

        self.get_cachedir(cachedir)

        # bind mount system directories into _instroot
        for (f, dest) in [("/sys", None), ("/proc", None), ("/proc/sys/fs/binfmt_misc", None),
                          ("/dev/pts", None),
                          (self.get_cachedir(), "/var/cache/yum")]:
            self.__bindmounts.append(BindChrootMount(f, self._instroot, dest))


        self._do_bindmounts()

        self.__create_minimal_dev()

        if os.path.exists(self._instroot + "/etc/mtab"):
            os.unlink(self._instroot + "/etc/mtab")
        os.symlink("../proc/mounts", self._instroot + "/etc/mtab")

        self.__write_fstab()

        # get size of available space in 'instroot' fs
        self._root_fs_avail = get_filesystem_avail(self._instroot)

    def unmount(self):
        """Unmounts the target filesystem.

        The ImageCreator class detaches the system from the install root, but
        other subclasses may also detach the loopback mounted filesystem image
        from the install root.

        """
        try:
            os.unlink(self._instroot + "/etc/mtab")
            if self.qemu_emulator:
                os.unlink(self._instroot + self.qemu_emulator)
            """ Clean up yum garbage """
            instroot_pdir = os.path.dirname(self._instroot + self._instroot)
            if os.path.exists(instroot_pdir):
                shutil.rmtree(instroot_pdir, ignore_errors = True)
        except OSError:
            pass


        self._undo_bindmounts()

        self._unmount_instroot()

    def cleanup(self):
        """Unmounts the target filesystem and deletes temporary files.

        This method calls unmount() and then deletes any temporary files and
        directories that were created on the host system while building the
        image.

        Note, make sure to call this method once finished with the creator
        instance in order to ensure no stale files are left on the host e.g.:

          creator = ImageCreator(ks, name)
          try:
              creator.create()
          finally:
              creator.cleanup()

        """
        if not self.__builddir:
            return

        self.unmount()

        shutil.rmtree(self.__builddir, ignore_errors = True)
        self.__builddir = None

    def __is_excluded_pkg(self, pkg):
        if pkg in self._excluded_pkgs:
            self._excluded_pkgs.remove(pkg)
            return True

        for xpkg in self._excluded_pkgs:
            if xpkg.endswith('*'):
                if pkg.startswith(xpkg[:-1]):
                    return True
            elif xpkg.startswith('*'):
                if pkg.endswith(xpkg[1:]):
                    return True

        return None

    def __select_packages(self, pkg_manager):
        skipped_pkgs = []
        for pkg in self._required_pkgs:
            e = pkg_manager.selectPackage(pkg)
            if e:
                if kickstart.ignore_missing(self.ks):
                    skipped_pkgs.append(pkg)
                elif self.__is_excluded_pkg(pkg):
                    skipped_pkgs.append(pkg)
                else:
                    raise CreatorError("Failed to find package '%s' : %s" %
                                       (pkg, e))

        for pkg in skipped_pkgs:
            msger.warning("Skipping missing package '%s'" % (pkg,))

    def __select_groups(self, pkg_manager):
        skipped_groups = []
        for group in self._required_groups:
            e = pkg_manager.selectGroup(group.name, group.include)
            if e:
                if kickstart.ignore_missing(self.ks):
                    skipped_groups.append(group)
                else:
                    raise CreatorError("Failed to find group '%s' : %s" %
                                       (group.name, e))

        for group in skipped_groups:
            msger.warning("Skipping missing group '%s'" % (group.name,))

    def __deselect_packages(self, pkg_manager):
        for pkg in self._excluded_pkgs:
            pkg_manager.deselectPackage(pkg)

    def __localinst_packages(self, pkg_manager):
        for rpm_path in self._get_local_packages():
            pkg_manager.installLocal(rpm_path)

    def install(self, repo_urls = {}):
        """Install packages into the install root.

        This function installs the packages listed in the supplied kickstart
        into the install root. By default, the packages are installed from the
        repository URLs specified in the kickstart.

        repo_urls -- a dict which maps a repository name to a repository URL;
                     if supplied, this causes any repository URLs specified in
                     the kickstart to be overridden.

        """


        # initialize pkg list to install
        if self.ks:
            self.__sanity_check()

            self._required_pkgs = \
                kickstart.get_packages(self.ks, self._get_required_packages())
            self._excluded_pkgs = \
                kickstart.get_excluded(self.ks, self._get_excluded_packages())
            self._required_groups = kickstart.get_groups(self.ks)
        else:
            self._required_pkgs = None
            self._excluded_pkgs = None
            self._required_groups = None

        yum_conf = self._mktemp(prefix = "yum.conf-")

        keep_record = None
        if self._include_src:
            keep_record = 'include_src'
        if self._recording_pkgs in ('name', 'content'):
            keep_record = self._recording_pkgs

        pkg_manager = self.get_pkg_manager(keep_record)
        pkg_manager.setup(yum_conf, self._instroot)

        for repo in kickstart.get_repos(self.ks, repo_urls):
            (name, baseurl, mirrorlist, inc, exc, proxy, proxy_username, proxy_password, debuginfo, source, gpgkey, disable) = repo

            yr = pkg_manager.addRepository(name, baseurl, mirrorlist, proxy, proxy_username, proxy_password, inc, exc)

        if kickstart.exclude_docs(self.ks):
            rpm.addMacro("_excludedocs", "1")
        rpm.addMacro("__file_context_path", "%{nil}")
        if kickstart.inst_langs(self.ks) != None:
            rpm.addMacro("_install_langs", kickstart.inst_langs(self.ks))

        try:
            try:
                self.__select_packages(pkg_manager)
                self.__select_groups(pkg_manager)
                self.__deselect_packages(pkg_manager)
                self.__localinst_packages(pkg_manager)

                BOOT_SAFEGUARD = 256L * 1024 * 1024 # 256M
                checksize = self._root_fs_avail
                if checksize:
                    checksize -= BOOT_SAFEGUARD
                if self.target_arch:
                    pkg_manager._add_prob_flags(rpm.RPMPROB_FILTER_IGNOREARCH)
                pkg_manager.runInstall(checksize)
            except CreatorError, e:
                raise CreatorError("%s" % (e,))
        finally:
            if keep_record:
                self._pkgs_content = pkg_manager.getAllContent()

            pkg_manager.closeRpmDB()
            pkg_manager.close()
            os.unlink(yum_conf)

        # do some clean up to avoid lvm info leakage.  this sucks.
        for subdir in ("cache", "backup", "archive"):
            lvmdir = self._instroot + "/etc/lvm/" + subdir
            try:
                for f in os.listdir(lvmdir):
                    os.unlink(lvmdir + "/" + f)
            except:
                pass

    def __run_post_scripts(self):
        msger.info("Running scripts ...")
        for s in kickstart.get_post_scripts(self.ks):
            (fd, path) = tempfile.mkstemp(prefix = "ks-script-",
                                          dir = self._instroot + "/tmp")

            s.script = s.script.replace("\r", "")
            os.write(fd, s.script)
            os.close(fd)
            os.chmod(path, 0700)

            env = self._get_post_scripts_env(s.inChroot)

            if not s.inChroot:
                env["INSTALL_ROOT"] = self._instroot
                env["IMG_NAME"] = self._name
                preexec = None
                script = path
            else:
                preexec = self._chroot
                script = "/tmp/" + os.path.basename(path)

            try:
                try:
                    subprocess.call([s.interp, script],
                                    preexec_fn = preexec, env = env, stdout = sys.stdout, stderr = sys.stderr)
                except OSError, (err, msg):
                    raise CreatorError("Failed to execute %%post script "
                                       "with '%s' : %s" % (s.interp, msg))
            finally:
                os.unlink(path)

    def __save_repo_keys(self, repodata):
        if not repodata:
            return None

        gpgkeydir = "/etc/pki/rpm-gpg"
        makedirs(self._instroot + gpgkeydir)
        for repo in repodata:
            if repo["repokey"]:
                repokey = gpgkeydir + "/RPM-GPG-KEY-%s" %  repo["name"]
                shutil.copy(repo["repokey"], self._instroot + repokey)

    def configure(self, repodata = None):
        """Configure the system image according to the kickstart.

        This method applies the (e.g. keyboard or network) configuration
        specified in the kickstart and executes the kickstart %post scripts.

        If neccessary, it also prepares the image to be bootable by e.g.
        creating an initrd and bootloader configuration.

        """
        ksh = self.ks.handler

        msger.info('Applying configurations ...')
        try:
            kickstart.LanguageConfig(self._instroot).apply(ksh.lang)
            kickstart.KeyboardConfig(self._instroot).apply(ksh.keyboard)
            kickstart.TimezoneConfig(self._instroot).apply(ksh.timezone)
            #kickstart.AuthConfig(self._instroot).apply(ksh.authconfig)
            kickstart.FirewallConfig(self._instroot).apply(ksh.firewall)
            kickstart.RootPasswordConfig(self._instroot).apply(ksh.rootpw)
            kickstart.UserConfig(self._instroot).apply(ksh.user)
            kickstart.ServicesConfig(self._instroot).apply(ksh.services)
            kickstart.XConfig(self._instroot).apply(ksh.xconfig)
            kickstart.NetworkConfig(self._instroot).apply(ksh.network)
            kickstart.RPMMacroConfig(self._instroot).apply(self.ks)
            kickstart.DesktopConfig(self._instroot).apply(ksh.desktop)
            self.__save_repo_keys(repodata)
            kickstart.MoblinRepoConfig(self._instroot).apply(ksh.repo, repodata)
        except:
            msger.warning("Failed to apply configuration to image")
            raise

        self._create_bootconfig()
        self.__run_post_scripts()

    def launch_shell(self, launch):
        """Launch a shell in the install root.

        This method is launches a bash shell chroot()ed in the install root;
        this can be useful for debugging.

        """
        if launch:
            msger.info("Launching shell. Exit to continue.")
            subprocess.call(["/bin/bash"], preexec_fn = self._chroot)

    def do_genchecksum(self, image_name):
        if not self._genchecksum:
            return

        """ Generate md5sum if /usr/bin/md5sum is available """
        if os.path.exists("/usr/bin/md5sum"):
            p = subprocess.Popen(["/usr/bin/md5sum", "-b", image_name],
                                 stdout=subprocess.PIPE)
            (md5sum, errorstr) = p.communicate()
            if p.returncode != 0:
                msger.warning("Can't generate md5sum for image %s" % image_name)
            else:
                pattern = re.compile("\*.*$")
                md5sum = pattern.sub("*" + os.path.basename(image_name), md5sum)
                fd = open(image_name + ".md5sum", "w")
                fd.write(md5sum)
                fd.close()
                self.outimage.append(image_name+".md5sum")

    def package(self, destdir = "."):
        """Prepares the created image for final delivery.

        In its simplest form, this method merely copies the install root to the
        supplied destination directory; other subclasses may choose to package
        the image by e.g. creating a bootable ISO containing the image and
        bootloader configuration.

        destdir -- the directory into which the final image should be moved;
                   this defaults to the current directory.

        """
        self._stage_final_image()

        if not os.path.exists(destdir):
            makedirs(destdir)
        if self.__img_compression_method:
            if not self._img_name:
                raise CreatorError("Image name not set.")
            rc = None
            img_location = os.path.join(self._outdir,self._img_name)
            if self.__img_compression_method == "bz2":
                bzip2 = find_binary_path('bzip2')
                msger.info("Compressing %s with bzip2. Please wait..." % img_location)
                rc = msger.run([bzip2, "-f", img_location])
                if rc:
                    raise CreatorError("Failed to compress image %s with %s." % (img_location, self.__img_compression_method))
                for bootimg in glob.glob(os.path.dirname(img_location) + "/*-boot.bin"):
                    msger.info("Compressing %s with bzip2. Please wait..." % bootimg)
                    rc = msger.run([bzip2, "-f", bootimg])
                    if rc:
                        raise CreatorError("Failed to compress image %s with %s." % (bootimg, self.__img_compression_method))

        if self._recording_pkgs:
            self._save_recording_pkgs(destdir)

        """ For image formats with two or multiple image files, it will be better to put them under a directory """
        if self.image_format in ("raw", "vmdk", "vdi", "nand", "mrstnand"):
            destdir = os.path.join(destdir, "%s-%s" % (self.name, self.image_format))
            msger.debug("creating destination dir: %s" % destdir)
            makedirs(destdir)

        # Ensure all data is flushed to _outdir
        msger.run('sync', True)

        for f in os.listdir(self._outdir):
            shutil.move(os.path.join(self._outdir, f),
                        os.path.join(destdir, f))
            self.outimage.append(os.path.join(destdir, f))
            self.do_genchecksum(os.path.join(destdir, f))

    def print_outimage_info(self):
        msger.info("Your new image can be found here:")
        self.outimage.sort()
        for file in self.outimage:
            msger.raw(os.path.abspath(file))

    def check_depend_tools(self):
        for tool in self._dep_checks:
            find_binary_path(tool)

    def package_output(self, image_format, destdir = ".", package="none"):
        if not package or package == "none":
            return

        destdir = os.path.abspath(os.path.expanduser(destdir))
        (pkg, comp) = os.path.splitext(package)
        if comp:
            comp=comp.lstrip(".")

        if pkg == "tar":
            if comp:
                dst = "%s/%s-%s.tar.%s" % (destdir, self.name, image_format, comp)
            else:
                dst = "%s/%s-%s.tar" % (destdir, self.name, image_format)
            msger.info("creating %s" % dst)
            tar = tarfile.open(dst, "w:" + comp)

            for file in self.outimage:
                msger.info("adding %s to %s" % (file, dst))
                tar.add(file, arcname=os.path.join("%s-%s" % (self.name, image_format), os.path.basename(file)))
                if os.path.isdir(file):
                    shutil.rmtree(file, ignore_errors = True)
                else:
                    os.remove(file)


            tar.close()

            '''All the file in outimage has been packaged into tar.* file'''
            self.outimage = [dst]

    def release_output(self, config, destdir, name, release):
        self.outimage = create_release(config, destdir, name, self.outimage, release)

    def save_kernel(self, destdir):
        if not os.path.exists(destdir):
            makedirs(destdir)
        for kernel in glob.glob("%s/boot/vmlinuz-*" % self._instroot):
            kernelfilename = "%s/%s-%s" % (destdir, self.name, os.path.basename(kernel))
            shutil.copy(kernel, kernelfilename)
            self.outimage.append(kernelfilename)

    def compress_disk_image(self, compression_method):
        """
        With this you can set the method that is used to compress the disk
        image after it is created.
        """

        if compression_method not in ('bz2'):
            raise CreatorError("Given disk image compression method ('%s') is not valid." % (compression_method))

        self.__img_compression_method = compression_method

    def get_pkg_manager(self, recording_pkgs=None):
        return self.pkgmgr(creator = self, recording_pkgs = recording_pkgs)


