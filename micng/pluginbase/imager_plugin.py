#!/usr/bin/python
from micng.pluginbase.base_plugin import PluginBase
import micng.configmgr as configmgr
import micng.utils.misc as misc
import micng.utils.errors as errors

class ImagerPlugin(PluginBase):
    plugin_type = "imager"
    def __init__(self, configinfo=None):
        if not configinfo:
            self.configinfo = configmgr.getConfigInfo()
            return 
        self.configinfo = configinfo
        """ Initialize package managers """
        self.pkgmgr = pkgmanagers.pkgManager()#fix in next step
        self.pkgmgr.load_pkg_managers()#fix in next steps

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
        self._img_compression_method = None

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

    """inner function"""
    def __ensure_builddir(self):
        if not self.__builddir is None:
            return

        try:
            self.__builddir = tempfile.mkdtemp(dir = self.tmpdir,
                                               prefix = "imgcreate-")
        except OSError, (err, msg):
            raise CreatorError("Failed create build directory in %s: %s" %
                               (self.tmpdir, msg))

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

    def _mktemp(self, prefix = "tmp-"):
        """Create a temporary file.

        This method simply calls __mkstemp() and closes the returned file
        descriptor.

        The absolute path to the temporary file is returned.

        Note, this method should only be called after mount() has been called.

        prefix -- a prefix which should be used when creating the file;
                  defaults to "tmp-".

        """
        def __mkstemp(prefix = "tmp-"):
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
        
        (f, path) = __mkstemp(prefix)
        os.close(f)
        return path

    def _get_fstab(self):
        """Return the desired contents of /etc/fstab.

        This is the hook where subclasses may specify the contents of
        /etc/fstab by returning a string containing the desired contents.

        A sensible default implementation is provided.

        """
        def __get_fstab_special():
            s = "devpts     /dev/pts  devpts  gid=5,mode=620   0 0\n"
            s += "tmpfs      /dev/shm  tmpfs   defaults         0 0\n"
            s += "proc       /proc     proc    defaults         0 0\n"
            s += "sysfs      /sys      sysfs   defaults         0 0\n"
            return s
            
        s =  "/dev/root  /         %s    %s 0 0\n" % (self._fstype, "defaults,noatime" if not self._fsopts else self._fsopts)
        s += __get_fstab_special()
        return s

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
        
    def _chroot(self):
        """Chroot into the install root.

        This method may be used by subclasses when executing programs inside
        the install root e.g.

          subprocess.call(["/bin/ls"], preexec_fn = self.chroot)

        """
        os.chroot(self._instroot)
        os.chdir("/")

    def _stage_final_image(self):
        """Stage the final system image in _outdir.

        This is the hook where subclasses should place the image in _outdir
        so that package() can copy it to the requested destination directory.

        By default, this moves the install root into _outdir.

        """
        shutil.move(self._instroot, self._outdir + "/" + self.name)

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

    def do_mount(self, base_on = None, cachedir = None):
        """Setup the target filesystem in preparation for an install.

        This interface should setup the filesystem which other functions will
        install into and configure.
        """
        def __get_cachedir(cachedir = None):
            if self.cachedir:
                return self.cachedir
    
            self.__ensure_builddir()
            if cachedir:
                self.cachedir = cachedir
            else:
                self.cachedir = self.__builddir + "/yum-cache"
            makedirs(self.cachedir)
            return self.cachedir

        def __do_bindmounts():
            """Mount various system directories onto _instroot.
    
            This method is called by mount(), but may also be used by subclasses
            in order to re-mount the bindmounts after modifying the underlying
            filesystem.
    
            """
            for b in self.__bindmounts:
                b.mount()
        
        def __create_minimal_dev():
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
        
        def __write_fstab():
            fstab = open(self._instroot + "/etc/fstab", "w")
            fstab.write(self._get_fstab())
            fstab.close()
        
        self.__ensure_builddir()

        makedirs(self._instroot)
        makedirs(self._outdir)

        self.do_mount_instroot(base_on)

        for d in ("/dev/pts", "/etc", "/boot", "/var/log", "/var/cache/yum", "/sys", "/proc", "/usr/bin"):
            makedirs(self._instroot + d)

        if self.target_arch and self.target_arch.startswith("arm"):
            self.qemu_emulator = setup_qemu_emulator(self._instroot, self.target_arch)

        __get_cachedir(cachedir)

        # bind mount system directories into _instroot
        for (f, dest) in [("/sys", None), ("/proc", None), ("/proc/sys/fs/binfmt_misc", None),
                          ("/dev/pts", None),
                          (__get_cachedir(), "/var/cache/yum")]:
            self.__bindmounts.append(BindChrootMount(f, self._instroot, dest))

        __do_bindmounts()

        __create_minimal_dev()

        if os.path.exists(self._instroot + "/etc/mtab"):
            os.unlink(self._instroot + "/etc/mtab")
        os.symlink("../proc/mounts", self._instroot + "/etc/mtab")

        __write_fstab()

        # get size of available space in 'instroot' fs
        self._root_fs_avail = get_filesystem_avail(self._instroot)

    def do_umount(self):
        """Unmounts the target filesystem.

        It should detache the system from the install root.
        """
        def __undo_bindmounts():
            """Unmount the bind-mounted system directories from _instroot.
    
            This method is usually only called by unmount(), but may also be used
            by subclasses in order to gain access to the filesystem obscured by
            the bindmounts - e.g. in order to create device nodes on the image
            filesystem.
    
            """
            self.__bindmounts.reverse()
            for b in self.__bindmounts:
                b.unmount()

        try:
            mtab = self._instroot + "/etc/mtab"
            if not os.path.islink(mtab):
                os.unlink(self._instroot + "/etc/mtab")
            if self.qemu_emulator:
                os.unlink(self._instroot + self.qemu_emulator)
        except OSError:
            pass

        __undo_bindmounts()

        """ Clean up yum garbage """
        try:
            instroot_pdir = os.path.dirname(self._instroot + self._instroot)
            if os.path.exists(instroot_pdir):
                shutil.rmtree(instroot_pdir, ignore_errors = True)
            yumcachedir = self._instroot + "/var/cache/yum"
            if os.path.exists(yumcachedir):
                shutil.rmtree(yumcachedir, ignore_errors = True)
            yumlibdir = self._instroot + "/var/lib/yum"
            if os.path.exists(yumlibdir):
                shutil.rmtree(yumlibdir, ignore_errors = True)
        except OSError:
            pass

        self.do_umount_instroot()

    def do_cleanup(self):
        """Unmounts the target filesystem and deletes temporary files.

        This interface deletes any temporary files and directories that were created
        on the host system while building the image.
        """
        if not self.__builddir:
            return

        self.do_umount()

        shutil.rmtree(self.__builddir, ignore_errors = True)
        self.__builddir = None

    def do_install(self, repo_urls={}):
        """Install packages into the install root.

        This interface installs the packages listed in the supplied kickstart
        into the install root. By default, the packages are installed from the
        repository URLs specified in the kickstart.
        """
        def __sanity_check():
            """Ensure that the config we've been given is sane."""
            if not (kickstart.get_packages(self.ks) or
                    kickstart.get_groups(self.ks)):
                raise CreatorError("No packages or groups specified")
    
            kickstart.convert_method_to_repo(self.ks)
    
            if not kickstart.get_repos(self.ks):
                raise CreatorError("No repositories specified")
            
        def __select_packages(pkg_manager):
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
    
        def __select_groups(pkg_manager):
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
    
        def __deselect_packages(pkg_manager):
            for pkg in self._excluded_pkgs:
                pkg_manager.deselectPackage(pkg)
    
        def __localinst_packages(pkg_manager):
            for rpm_path in self._get_local_packages():
                pkg_manager.installLocal(rpm_path)

        # initialize pkg list to install
        if self.ks:
            __sanity_check()

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
        #fix in next step pkg_manager
        pkg_manager = self.get_pkg_manager(keep_record)
        pkg_manager.setup(yum_conf, self._instroot)

        for repo in kickstart.get_repos(self.ks, repo_urls):
            (name, baseurl, mirrorlist, inc, exc, proxy, proxy_username, proxy_password, debuginfo, source, gpgkey, disable) = repo

            try:
                yr = pkg_manager.addRepository(name, baseurl, mirrorlist, proxy, proxy_username, proxy_password, inc, exc)
                if inc:
                    yr.includepkgs = inc
                if exc:
                    yr.exclude = exc
            except CreatorError, e:
                raise CreatorError("%s" % (e,))

        if kickstart.exclude_docs(self.ks):
            rpm.addMacro("_excludedocs", "1")
        rpm.addMacro("__file_context_path", "%{nil}")
        if kickstart.inst_langs(self.ks) != None:
            rpm.addMacro("_install_langs", kickstart.inst_langs(self.ks))

        try:
            __select_packages(pkg_manager)
            __select_groups(pkg_manager)
            __deselect_packages(pkg_manager)
            __localinst_packages(pkg_manager)

            BOOT_SAFEGUARD = 256L * 1024 * 1024 # 256M
            checksize = self._root_fs_avail
            if checksize:
                checksize -= BOOT_SAFEGUARD
            if self.target_arch:
                pkg_manager._add_prob_flags(rpm.RPMPROB_FILTER_IGNOREARCH)

            try:
                save_env = os.environ["LC_ALL"]
            except KeyError:
                save_env = None
            os.environ["LC_ALL"] = 'C'
            pkg_manager.runInstall(checksize)
            if save_env:
                os.environ["LC_ALL"] = save_env
            else:
                os.unsetenv("LC_ALL")
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

    def do_configure(self, repodata = None):
        """Configure the system image according to the kickstart.

        This interface applies the (e.g. keyboard or network) configuration
        specified in the kickstart and executes the kickstart %post scripts.

        If neccessary, it also prepares the image to be bootable by e.g.
        creating an initrd and bootloader configuration.
        """
        def __save_repo_keys(repodata):
            if not repodata:
                return None
            gpgkeydir = "/etc/pki/rpm-gpg"
            makedirs(self._instroot + gpgkeydir)
            for repo in repodata:
                if repo["repokey"]:
                    repokey = gpgkeydir + "/RPM-GPG-KEY-%s" %  repo["name"]
                    shutil.copy(repo["repokey"], self._instroot + repokey)

        def __run_post_scripts():
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
            __save_repo_keys(repodata)
            kickstart.MoblinRepoConfig(self._instroot).apply(ksh.repo, repodata)
        except:
            print "Failed to apply configuration to image"
            raise

        self._create_bootconfig()
        __run_post_scripts()


    def do_package(self, destdir = "."):
        """Prepares the created image for final delivery.

        This interface merely copies the install root to the supplied destination
        directory,
        """
        def __do_genchecksum(self, image_name):
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
        
        self._stage_final_image()

        if self._img_compression_method:
            if not self._img_name:
                raise CreatorError("Image name not set.")
            rc = None
            img_location = os.path.join(self._outdir,self._img_name)

            print "Compressing %s with %s. Please wait..." % (img_location, self._img_compression_method)
            if self._img_compression_method == "bz2":
                bzip2 = find_binary_path('bzip2')
                rc = subprocess.call([bzip2, "-f", img_location])
                if rc:
                    raise CreatorError("Failed to compress image %s with %s." % (img_location, self._img_compression_method))
                for bootimg in glob.glob(os.path.dirname(img_location) + "/*-boot.bin"):
                    print "Compressing %s with bzip2. Please wait..." % bootimg
                    rc = subprocess.call([bzip2, "-f", bootimg])
                    if rc:
                        raise CreatorError("Failed to compress image %s with %s." % (bootimg, self._img_compression_method))
            elif self._img_compression_method == "tar.bz2":
                dst = "%s.tar.bz2" % (img_location)

                tar = tarfile.open(dst, "w:bz2")
                # Add files to tarball and remove originals after packaging
                tar.add(img_location, self._img_name)
                os.unlink(img_location)
                for bootimg in glob.glob(os.path.dirname(img_location) + "/*-boot.bin"):
                    tar.add(bootimg,os.path.basename(bootimg))
                    os.unlink(bootimg)
                tar.close()

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
            __do_genchecksum(os.path.join(destdir, f))

    def do_create(self):
        """ Temporary solution to create image in one single interface """
        self.do_mount()
        self.do_install()
        self.do_configure()
        self.do_umount()
        self.do_package()

    def _base_on(self, base_on):
        """Support Image Convertor, unpack the source image for building the instroot directory.
        
            Subclass need a actual implementation.
        """
        shutil.copyfile(base_on, self._image)

    def _mount_srcimg(self, srcimg):
        """Mount source image.
    
           This method may be used by subclasses to mount source image for Chroot,
           There is no default implementation. 
           e.g.
           "livecd":
               imgcreate.DiskMount(imgcreate.LoopbackDisk(self.img, 0), self.imgmnt)
        """
        pass

    def _umount_srcimg(self, srcimg):
        """Umount source image.
    
           This method may be used by subclasses to umount source image for Chroot,
           e.g. umount a raw image. There is no default implementation.
        """
        pass
