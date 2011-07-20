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

import os
import os.path
import stat
import sys
import tempfile
import shutil
import logging
import subprocess
import re
import tarfile
import glob

import rpm

from micng.utils.errors import *
from micng.utils.fs_related import *
from micng.utils import kickstart
from micng.utils import pkgmanagers
from micng.utils.rpmmisc import *
from micng.utils.misc import *

FSLABEL_MAXLEN = 32
"""The maximum string length supported for LoopImageCreator.fslabel."""

class ImageCreator(object):
    """Installs a system to a chroot directory.

    ImageCreator is the simplest creator class available; it will install and
    configure a system image according to the supplied kickstart file.

    e.g.

      import micng.imgcreate as imgcreate
      ks = imgcreate.read_kickstart("foo.ks")
      imgcreate.ImageCreator(ks, "foo").create()

    """

    def __init__(self, ks, name):
        """Initialize an ImageCreator instance.

        ks -- a pykickstart.KickstartParser instance; this instance will be
              used to drive the install by e.g. providing the list of packages
              to be installed, the system configuration and %post scripts

        name -- a name for the image; used for e.g. image filenames or
                filesystem labels

        """

        """ Initialize package managers """
#package plugin manager
        self.pkgmgr = pkgmanagers.pkgManager()
        self.pkgmgr.load_pkg_managers()

        self.ks = ks
        """A pykickstart.KickstartParser instance."""

        self.name = name
        """A name for the image."""

        self.distro_name = "MeeGo"

        """Output image file names"""
        self.outimage = []

        """A flag to generate checksum"""
        self._genchecksum = False

        self.tmpdir = "/var/tmp"
        """The directory in which all temporary files will be created."""

        self.cachedir = None

        self._alt_initrd_name = None

        self.__builddir = None
        self.__bindmounts = []

        """ Contains the compression method that is used to compress
        the disk image after creation, e.g., bz2.
        This value is set with compression_method function. """
        self.__img_compression_method = None

        # dependent commands to check
        self._dep_checks = ["ls", "bash", "cp", "echo", "modprobe", "passwd"]

        self._recording_pkgs = None

        self._include_src = None

        self._local_pkgs_path = None

        # available size in root fs, init to 0
        self._root_fs_avail = 0

        # target arch for non-x86 image
        self.target_arch = None

        """ Name of the disk image file that is created. """
        self._img_name = None

        """ Image format """
        self.image_format = None

        """ Save qemu emulator file name in order to clean up it finally """
        self.qemu_emulator = None

        """ No ks provided when called by convertor, so skip the dependency check """
        if self.ks:
            """ If we have btrfs partition we need to check that we have toosl for those """
            for part in self.ks.handler.partition.partitions:
                if part.fstype and part.fstype == "btrfs":
                    self._dep_checks.append("mkfs.btrfs")
                    break

    def set_target_arch(self, arch):
        if arch not in arches.keys():
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
                    print "\n= WARNING ="
                    print "vdso is enabled on your host, which might cause problems with arm emulations."
                    print "You can disable vdso with following command before starting image build:"
                    print "echo 0 | sudo tee /proc/sys/vm/vdso_enabled"
                    print "= WARNING =\n"

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
            package_name = splitFilename(rpm_name)[0]
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
        def get_version(header):
            version = None
            for f in header['filenames']:
                if f.startswith('/boot/vmlinuz-'):
                    version = f[14:]
            return version

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
            logging.warn("Skipping missing package '%s'" % (pkg,))

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
            logging.warn("Skipping missing group '%s'" % (group.name,))

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
        #import pdb
        #pdb.set_trace()
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
                #import pdb
                #pdb.set_trace()
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
        print "Running scripts"
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
            print "Failed to apply configuration to image"
            raise

        self._create_bootconfig()
        self.__run_post_scripts()

    def launch_shell(self, launch):
        """Launch a shell in the install root.

        This method is launches a bash shell chroot()ed in the install root;
        this can be useful for debugging.

        """
        if launch:
            print "Launching shell. Exit to continue."
            print "----------------------------------"
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
                logging.warning("Can't generate md5sum for image %s" % image_name)
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

        if self.__img_compression_method:
            if not self._img_name:
                raise CreatorError("Image name not set.")
            rc = None
            img_location = os.path.join(self._outdir,self._img_name)
            if self.__img_compression_method == "bz2":
                bzip2 = find_binary_path('bzip2')
                print "Compressing %s with bzip2. Please wait..." % img_location
                rc = subprocess.call([bzip2, "-f", img_location])
                if rc:
                    raise CreatorError("Failed to compress image %s with %s." % (img_location, self.__img_compression_method))
                for bootimg in glob.glob(os.path.dirname(img_location) + "/*-boot.bin"):
                    print "Compressing %s with bzip2. Please wait..." % bootimg
                    rc = subprocess.call([bzip2, "-f", bootimg])
                    if rc:
                        raise CreatorError("Failed to compress image %s with %s." % (bootimg, self.__img_compression_method))

        if self._recording_pkgs:
            self._save_recording_pkgs(destdir)

        """ For image formats with two or multiple image files, it will be better to put them under a directory """
        if self.image_format in ("raw", "vmdk", "vdi", "nand", "mrstnand"):
            destdir = os.path.join(destdir, "%s-%s" % (self.name, self.image_format))
            logging.debug("creating destination dir: %s" % destdir)
            makedirs(destdir)

        # Ensure all data is flushed to _outdir
        synccmd = find_binary_path("sync")
        subprocess.call([synccmd])

        for f in os.listdir(self._outdir):
            shutil.move(os.path.join(self._outdir, f),
                        os.path.join(destdir, f))
            self.outimage.append(os.path.join(destdir, f))
            self.do_genchecksum(os.path.join(destdir, f))

    def create(self):
        """Install, configure and package an image.

        This method is a utility method which creates and image by calling some
        of the other methods in the following order - mount(), install(),
        configure(), unmount and package().

        """
        self.mount()
        self.install()
        self.configure()
        self.unmount()
        self.package()

    def print_outimage_info(self):
        print "Your new image can be found here:"
        self.outimage.sort()
        for file in self.outimage:
            print os.path.abspath(file)

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
            print "creating %s" % dst
            tar = tarfile.open(dst, "w:" + comp)

            for file in self.outimage:
                print "adding %s to %s" % (file, dst)
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

    def set_pkg_manager(self, name):
        self.pkgmgr.set_default_pkg_manager(name)

    def get_pkg_manager(self, recording_pkgs=None):
        pkgmgr_instance = self.pkgmgr.get_default_pkg_manager()
        if not pkgmgr_instance:
            raise CreatorError("No package manager available")
        return pkgmgr_instance(creator = self, recording_pkgs = recording_pkgs)

class LoopImageCreator(ImageCreator):
    """Installs a system into a loopback-mountable filesystem image.

    LoopImageCreator is a straightforward ImageCreator subclass; the system
    is installed into an ext3 filesystem on a sparse file which can be
    subsequently loopback-mounted.

    """

    def __init__(self, ks, name, fslabel = None):
        """Initialize a LoopImageCreator instance.

        This method takes the same arguments as ImageCreator.__init__() with
        the addition of:

        fslabel -- A string used as a label for any filesystems created.

        """
        ImageCreator.__init__(self, ks, name)

        self.__fslabel = None
        self.fslabel = fslabel

        self.__minsize_KB = 0
        self.__blocksize = 4096
        if self.ks:
            self.__fstype = kickstart.get_image_fstype(self.ks, "ext3")
            self.__fsopts = kickstart.get_image_fsopts(self.ks, "defaults,noatime")
        else:
            self.__fstype = None
            self.__fsopts = None

        self.__instloop = None
        self.__imgdir = None

        if self.ks:
            self.__image_size = kickstart.get_image_size(self.ks,
                                                         4096L * 1024 * 1024)
        else:
            self.__image_size = 0

        self._img_name = self.name + ".img"

    def _set_fstype(self, fstype):
        self.__fstype = fstype

    def _set_image_size(self, imgsize):
        self.__image_size = imgsize

    #
    # Properties
    #
    def __get_fslabel(self):
        if self.__fslabel is None:
            return self.name
        else:
            return self.__fslabel
    def __set_fslabel(self, val):
        if val is None:
            self.__fslabel = None
        else:
            self.__fslabel = val[:FSLABEL_MAXLEN]
    fslabel = property(__get_fslabel, __set_fslabel)
    """A string used to label any filesystems created.

    Some filesystems impose a constraint on the maximum allowed size of the
    filesystem label. In the case of ext3 it's 16 characters, but in the case
    of ISO9660 it's 32 characters.

    mke2fs silently truncates the label, but mkisofs aborts if the label is too
    long. So, for convenience sake, any string assigned to this attribute is
    silently truncated to FSLABEL_MAXLEN (32) characters.

    """

    def __get_image(self):
        if self.__imgdir is None:
            raise CreatorError("_image is not valid before calling mount()")
        return self.__imgdir + "/meego.img"
    _image = property(__get_image)
    """The location of the image file.

    This is the path to the filesystem image. Subclasses may use this path
    in order to package the image in _stage_final_image().

    Note, this directory does not exist before ImageCreator.mount() is called.

    Note also, this is a read-only attribute.

    """

    def __get_blocksize(self):
        return self.__blocksize
    def __set_blocksize(self, val):
        if self.__instloop:
            raise CreatorError("_blocksize must be set before calling mount()")
        try:
            self.__blocksize = int(val)
        except ValueError:
            raise CreatorError("'%s' is not a valid integer value "
                               "for _blocksize" % val)
    _blocksize = property(__get_blocksize, __set_blocksize)
    """The block size used by the image's filesystem.

    This is the block size used when creating the filesystem image. Subclasses
    may change this if they wish to use something other than a 4k block size.

    Note, this attribute may only be set before calling mount().

    """

    def __get_fstype(self):
        return self.__fstype
    def __set_fstype(self, val):
        if val != "ext2" and val != "ext3":
            raise CreatorError("Unknown _fstype '%s' supplied" % val)
        self.__fstype = val
    _fstype = property(__get_fstype, __set_fstype)
    """The type of filesystem used for the image.

    This is the filesystem type used when creating the filesystem image.
    Subclasses may change this if they wish to use something other ext3.

    Note, only ext2 and ext3 are currently supported.

    Note also, this attribute may only be set before calling mount().

    """

    def __get_fsopts(self):
        return self.__fsopts
    def __set_fsopts(self, val):
        self.__fsopts = val
    _fsopts = property(__get_fsopts, __set_fsopts)
    """Mount options of filesystem used for the image.

    This can be specified by --fsoptions="xxx,yyy" in part command in
    kickstart file.
    """

    #
    # Helpers for subclasses
    #
    def _resparse(self, size = None):
        """Rebuild the filesystem image to be as sparse as possible.

        This method should be used by subclasses when staging the final image
        in order to reduce the actual space taken up by the sparse image file
        to be as little as possible.

        This is done by resizing the filesystem to the minimal size (thereby
        eliminating any space taken up by deleted files) and then resizing it
        back to the supplied size.

        size -- the size in, in bytes, which the filesystem image should be
                resized to after it has been minimized; this defaults to None,
                causing the original size specified by the kickstart file to
                be used (or 4GiB if not specified in the kickstart).

        """
        return self.__instloop.resparse(size)

    def _base_on(self, base_on):
        shutil.copyfile(base_on, self._image)

    #
    # Actual implementation
    #
    def _mount_instroot(self, base_on = None):
        self.__imgdir = self._mkdtemp()

        if not base_on is None:
            self._base_on(base_on)

        if self.__fstype in ("ext2", "ext3", "ext4"):
            MyDiskMount = ExtDiskMount
        elif self.__fstype == "btrfs":
            MyDiskMount = BtrfsDiskMount

        self.__instloop = MyDiskMount(SparseLoopbackDisk(self._image, self.__image_size),
                                       self._instroot,
                                       self.__fstype,
                                       self.__blocksize,
                                       self.fslabel)

        try:
            self.__instloop.mount()
        except MountError, e:
            raise CreatorError("Failed to loopback mount '%s' : %s" %
                               (self._image, e))

    def _unmount_instroot(self):
        if not self.__instloop is None:
            self.__instloop.cleanup()

    def _stage_final_image(self):
        self._resparse()
        shutil.move(self._image, self._outdir + "/" + self._img_name)

class LiveImageCreatorBase(LoopImageCreator):
    """A base class for LiveCD image creators.

    This class serves as a base class for the architecture-specific LiveCD
    image creator subclass, LiveImageCreator.

    LiveImageCreator creates a bootable ISO containing the system image,
    bootloader, bootloader configuration, kernel and initramfs.

    """

    def __init__(self, *args):
        """Initialise a LiveImageCreator instance.

        This method takes the same arguments as ImageCreator.__init__().

        """
        LoopImageCreator.__init__(self, *args)

        self.skip_compression = False
        """Controls whether to use squashfs to compress the image."""

        self.skip_minimize = False
        """Controls whether an image minimizing snapshot should be created.

        This snapshot can be used when copying the system image from the ISO in
        order to minimize the amount of data that needs to be copied; simply,
        it makes it possible to create a version of the image's filesystem with
        no spare space.

        """

        self.actasconvertor = False
        """A flag which indicates i act as a convertor"""

        if self.ks:
            self._timeout = kickstart.get_timeout(self.ks, 10)
        else:
            self._timeout = 10
        """The bootloader timeout from kickstart."""

        if self.ks:
            self._default_kernel = kickstart.get_default_kernel(self.ks, "kernel")
        else:
            self._default_kernel = None
        """The default kernel type from kickstart."""

        self.__isodir = None

        self.__modules = ["=ata", "sym53c8xx", "aic7xxx", "=usb", "=firewire", "=mmc", "=pcmcia", "mptsas"]
        if self.ks:
            self.__modules.extend(kickstart.get_modules(self.ks))

        self._dep_checks.extend(["isohybrid", "unsquashfs", "mksquashfs", "dd", "genisoimage"])

    #
    # Hooks for subclasses
    #
    def _configure_bootloader(self, isodir):
        """Create the architecture specific booloader configuration.

        This is the hook where subclasses must create the booloader
        configuration in order to allow a bootable ISO to be built.

        isodir -- the directory where the contents of the ISO are to be staged

        """
        raise CreatorError("Bootloader configuration is arch-specific, "
                           "but not implemented for this arch!")
    def _get_menu_options(self):
        """Return a menu options string for syslinux configuration.

        """
        r = kickstart.get_menu_args(self.ks)
        return r

    def _get_kernel_options(self):
        """Return a kernel options string for bootloader configuration.

        This is the hook where subclasses may specify a set of kernel options
        which should be included in the images bootloader configuration.

        A sensible default implementation is provided.

        """
        r = kickstart.get_kernel_args(self.ks)
        if os.path.exists(self._instroot + "/usr/bin/rhgb") or \
           os.path.exists(self._instroot + "/usr/bin/plymouth"):
            r += " rhgb"
        return r

    def _get_mkisofs_options(self, isodir):
        """Return the architecture specific mkisosfs options.

        This is the hook where subclasses may specify additional arguments to
        mkisofs, e.g. to enable a bootable ISO to be built.

        By default, an empty list is returned.

        """
        return []

    #
    # Helpers for subclasses
    #
    def _has_checkisomd5(self):
        """Check whether checkisomd5 is available in the install root."""
        def exists(instroot, path):
            return os.path.exists(instroot + path)

        if (exists(self._instroot, "/usr/lib/moblin-installer-runtime/checkisomd5") or
            exists(self._instroot, "/usr/bin/checkisomd5")):
            if (os.path.exists("/usr/bin/implantisomd5") or
               os.path.exists("/usr/lib/anaconda-runtime/implantisomd5")):
                return True

        return False

    def _uncompress_squashfs(self, squashfsimg, outdir):
        """Uncompress file system from squshfs image"""
        unsquashfs = find_binary_path("unsquashfs")
        args = [unsquashfs, "-d", outdir, squashfsimg ]
        rc = subprocess.call(args)
        if (rc != 0):
            raise CreatorError("Failed to uncompress %s." % squashfsimg)
    #
    # Actual implementation
    #
    def _base_on(self, base_on):
        """Support Image Convertor"""
        if self.actasconvertor:
            if os.path.exists(base_on) and not os.path.isfile(base_on):
                ddcmd = find_binary_path("dd")
                args = [ ddcmd, "if=%s" % base_on, "of=%s" % self._image ]
                print "dd %s -> %s" % (base_on, self._image)
                rc = subprocess.call(args)
                if rc != 0:
                    raise CreatorError("Failed to dd from %s to %s" % (base_on, self._image))
                self._set_image_size(get_file_size(self._image) * 1024L * 1024L)
            if os.path.isfile(base_on):
                print "Copying file system..."
                shutil.copyfile(base_on, self._image)
                self._set_image_size(get_file_size(self._image) * 1024L * 1024L)
            return

        """helper function to extract ext3 file system from a live CD ISO"""
        isoloop = DiskMount(LoopbackDisk(base_on, 0), self._mkdtemp())

        try:
            isoloop.mount()
        except MountError, e:
            raise CreatorError("Failed to loopback mount '%s' : %s" %
                               (base_on, e))

        # legacy LiveOS filesystem layout support, remove for F9 or F10
        if os.path.exists(isoloop.mountdir + "/squashfs.img"):
            squashimg = isoloop.mountdir + "/squashfs.img"
        else:
            squashimg = isoloop.mountdir + "/LiveOS/squashfs.img"

        tmpoutdir = self._mkdtemp()
        # unsquashfs requires outdir mustn't exist
        shutil.rmtree(tmpoutdir, ignore_errors = True)
        self._uncompress_squashfs(squashimg, tmpoutdir)

        try:
            # legacy LiveOS filesystem layout support, remove for F9 or F10
            if os.path.exists(tmpoutdir + "/os.img"):
                os_image = tmpoutdir + "/os.img"
            else:
                os_image = tmpoutdir + "/LiveOS/ext3fs.img"

            if not os.path.exists(os_image):
                raise CreatorError("'%s' is not a valid live CD ISO : neither "
                                   "LiveOS/ext3fs.img nor os.img exist" %
                                   base_on)

            print "Copying file system..."
            shutil.copyfile(os_image, self._image)
            self._set_image_size(get_file_size(self._image) * 1024L * 1024L)
        finally:
            shutil.rmtree(tmpoutdir, ignore_errors = True)
            isoloop.cleanup()

    def _mount_instroot(self, base_on = None):
        LoopImageCreator._mount_instroot(self, base_on)
        self.__write_initrd_conf(self._instroot + "/etc/sysconfig/mkinitrd")

    def _unmount_instroot(self):
        try:
            os.unlink(self._instroot + "/etc/sysconfig/mkinitrd")
        except:
            pass
        LoopImageCreator._unmount_instroot(self)

    def __ensure_isodir(self):
        if self.__isodir is None:
            self.__isodir = self._mkdtemp("iso-")
        return self.__isodir

    def _get_isodir(self):
        return self.__ensure_isodir()

    def _set_isodir(self, isodir = None):
        self.__isodir = isodir

    def _create_bootconfig(self):
        """Configure the image so that it's bootable."""
        self._configure_bootloader(self.__ensure_isodir())

    def _get_post_scripts_env(self, in_chroot):
        env = LoopImageCreator._get_post_scripts_env(self, in_chroot)

        if not in_chroot:
            env["LIVE_ROOT"] = self.__ensure_isodir()

        return env

    def __write_initrd_conf(self, path):
        content = ""
        if not os.path.exists(os.path.dirname(path)):
            makedirs(os.path.dirname(path))
        f = open(path, "w")

        content += 'LIVEOS="yes"\n'
        content += 'PROBE="no"\n'
        content += 'MODULES+="squashfs ext3 ext2 vfat msdos "\n'
        content += 'MODULES+="sr_mod sd_mod ide-cd cdrom "\n'

        for module in self.__modules:
            if module == "=usb":
                content += 'MODULES+="ehci_hcd uhci_hcd ohci_hcd "\n'
                content += 'MODULES+="usb_storage usbhid "\n'
            elif module == "=firewire":
                content += 'MODULES+="firewire-sbp2 firewire-ohci "\n'
                content += 'MODULES+="sbp2 ohci1394 ieee1394 "\n'
            elif module == "=mmc":
                content += 'MODULES+="mmc_block sdhci sdhci-pci "\n'
            elif module == "=pcmcia":
                content += 'MODULES+="pata_pcmcia  "\n'
            else:
                content += 'MODULES+="' + module + ' "\n'
        f.write(content)
        f.close()

    def __create_iso(self, isodir):
        iso = self._outdir + "/" + self.name + ".iso"
        genisoimage = find_binary_path("genisoimage")
        args = [genisoimage,
                "-J", "-r",
                "-hide-rr-moved", "-hide-joliet-trans-tbl",
                "-V", self.fslabel,
                "-o", iso]

        args.extend(self._get_mkisofs_options(isodir))

        args.append(isodir)

        if subprocess.call(args) != 0:
            raise CreatorError("ISO creation failed!")

        """ It should be ok still even if you haven't isohybrid """
        isohybrid = None
        try:
            isohybrid = find_binary_path("isohybrid")
        except:
            pass

        if isohybrid:
            args = [isohybrid, "-partok", iso ]
            if subprocess.call(args) != 0:
             	raise CreatorError("Hybrid ISO creation failed!")

        self.__implant_md5sum(iso)

    def __implant_md5sum(self, iso):
        """Implant an isomd5sum."""
        if os.path.exists("/usr/bin/implantisomd5"):
            implantisomd5 = "/usr/bin/implantisomd5"
        elif os.path.exists("/usr/lib/anaconda-runtime/implantisomd5"):
            implantisomd5 = "/usr/lib/anaconda-runtime/implantisomd5"
        else:
            logging.warn("isomd5sum not installed; not setting up mediacheck")
            implantisomd5 = ""
            return

        subprocess.call([implantisomd5, iso], stdout=sys.stdout, stderr=sys.stderr)

    def _stage_final_image(self):
        try:
            makedirs(self.__ensure_isodir() + "/LiveOS")

            minimal_size = self._resparse()

            if not self.skip_minimize:
                create_image_minimizer(self.__isodir + "/LiveOS/osmin.img",
                                       self._image, minimal_size)

            if self.skip_compression:
                shutil.move(self._image, self.__isodir + "/LiveOS/ext3fs.img")
            else:
                makedirs(os.path.join(os.path.dirname(self._image), "LiveOS"))
                shutil.move(self._image,
                            os.path.join(os.path.dirname(self._image),
                                         "LiveOS", "ext3fs.img"))
                mksquashfs(os.path.dirname(self._image),
                           self.__isodir + "/LiveOS/squashfs.img")

            self.__create_iso(self.__isodir)
        finally:
            shutil.rmtree(self.__isodir, ignore_errors = True)
            self.__isodir = None

