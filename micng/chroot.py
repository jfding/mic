#/usr/bin/python -t
import os
import sys
import glob
import shutil
import shlex
import subprocess
import micng.utils.fs_related as fs_related
import micng.utils.misc as misc
import micng.utils.errors as errors

def cleanup_after_chroot(targettype,imgmount,tmpdir,tmpmnt):
    if imgmount and targettype == "img":
        imgmount.cleanup()
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors = True)
    if tmpmnt:
        shutil.rmtree(tmpmnt, ignore_errors = True)

def check_bind_mounts(chrootdir, bindmounts):
    chrootmounts = []
    mounts = bindmounts.split(";")
    for mount in mounts:
        if mount == "":
            continue
        srcdst = mount.split(":")
        if len(srcdst) == 1:
           srcdst.append("none")
        if not os.path.isdir(srcdst[0]):
            return False
        if srcdst[1] == "" or srcdst[1] == "none":
            srcdst[1] = None
        if srcdst[0] in ("/proc", "/proc/sys/fs/binfmt_misc", "/", "/sys", "/dev", "/dev/pts", "/dev/shm", "/var/lib/dbus", "/var/run/dbus", "/var/lock"):
            continue
        if chrootdir:
            if not srcdst[1]:
                srcdst[1] = os.path.abspath(os.path.expanduser(srcdst[0]))
            else:
                srcdst[1] = os.path.abspath(os.path.expanduser(srcdst[1]))
            tmpdir = chrootdir + "/" + srcdst[1]
            if os.path.isdir(tmpdir):
                print "Warning: dir %s has existed."  % tmpdir
    return True

def cleanup_mounts(chrootdir):
    checkpoints = ["/proc/sys/fs/binfmt_misc", "/proc", "/sys", "/dev/pts", "/dev/shm", "/dev", "/var/lib/dbus", "/var/run/dbus", "/var/lock"]
    dev_null = os.open("/dev/null", os.O_WRONLY)
    umountcmd = misc.find_binary_path("umount")
    for point in checkpoints:
        print point
        args = [ umountcmd, "-l", chrootdir + point ]
        subprocess.call(args, stdout=dev_null, stderr=dev_null)
    catcmd = misc.find_binary_path("cat")
    args = [ catcmd, "/proc/mounts" ]
    proc_mounts = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=dev_null)
    outputs = proc_mounts.communicate()[0].strip().split("\n")
    for line in outputs:
        if line.find(os.path.abspath(chrootdir)) >= 0:
            if os.path.abspath(chrootdir) == line.split()[1]:
                continue
            point = line.split()[1]
            print point
            args = [ umountcmd, "-l", point ]
            ret = subprocess.call(args, stdout=dev_null, stderr=dev_null)
            if ret != 0:
                print "ERROR: failed to unmount %s" % point
                os.close(dev_null)
                return ret
    os.close(dev_null)
    return 0

def setup_chrootenv(chrootdir, bindmounts = None):##move to mic/utils/misc
    global chroot_lockfd, chroot_lock
    def get_bind_mounts(chrootdir, bindmounts):
        chrootmounts = []
        if bindmounts in ("", None):
            bindmounts = ""
        mounts = bindmounts.split(";")
        for mount in mounts:
            if mount == "":
                continue
            srcdst = mount.split(":")
            srcdst[0] = os.path.abspath(os.path.expanduser(srcdst[0]))
            if len(srcdst) == 1:
               srcdst.append("none")
            if not os.path.isdir(srcdst[0]):
                continue
            if srcdst[0] in ("/proc", "/proc/sys/fs/binfmt_misc", "/", "/sys", "/dev", "/dev/pts", "/dev/shm", "/var/lib/dbus", "/var/run/dbus", "/var/lock"):
                pwarning("%s will be mounted by default." % srcdst[0])
                continue
            if srcdst[1] == "" or srcdst[1] == "none":
                srcdst[1] = None
            else:
                srcdst[1] = os.path.abspath(os.path.expanduser(srcdst[1]))
                if os.path.isdir(chrootdir + "/" + srcdst[1]):
                    pwarning("%s has existed in %s , skip it." % (srcdst[1], chrootdir))
                    continue
            chrootmounts.append(fs_related.BindChrootMount(srcdst[0], chrootdir, srcdst[1]))
    
        """Default bind mounts"""
        chrootmounts.append(fs_related.BindChrootMount("/proc", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/proc/sys/fs/binfmt_misc", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/sys", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/dev", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/dev/pts", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/dev/shm", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/var/lib/dbus", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/var/run/dbus", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/var/lock", chrootdir, None))
        chrootmounts.append(fs_related.BindChrootMount("/", chrootdir, "/parentroot", "ro"))
        for kernel in os.listdir("/lib/modules"):
            chrootmounts.append(fs_related.BindChrootMount("/lib/modules/" + kernel, chrootdir, None, "ro"))
    
        return chrootmounts

    def bind_mount(chrootmounts):
        for b in chrootmounts:
            print "bind_mount: %s -> %s" % (b.src, b.dest)
            b.mount()

    def setup_resolv(chrootdir):
        shutil.copyfile("/etc/resolv.conf", chrootdir + "/etc/resolv.conf")

    globalmounts = get_bind_mounts(chrootdir, bindmounts)
    bind_mount(globalmounts)
    setup_resolv(chrootdir)
    mtab = "/etc/mtab"
    dstmtab = chrootdir + mtab
    if not os.path.islink(dstmtab):
        shutil.copyfile(mtab, dstmtab)
    chroot_lock = os.path.join(chrootdir, ".chroot.lock")
    chroot_lockfd = open(chroot_lock, "w")
    return globalmounts    

def cleanup_chrootenv(chrootdir, bindmounts = None, globalmounts = []):
    global chroot_lockfd, chroot_lock
    def bind_unmount(chrootmounts):
        chrootmounts.reverse()
        for b in chrootmounts:
            print "bind_unmount: %s -> %s" % (b.src, b.dest)
            b.unmount()

    def cleanup_resolv(chrootdir):
        fd = open(chrootdir + "/etc/resolv.conf", "w")
        fd.truncate(0)
        fd.close()

    def kill_processes(chrootdir):
        for file in glob.glob("/proc/*/root"):
            try:
                if os.readlink(file) == chrootdir:
                    pid = int(file.split("/")[2])
                    os.kill(pid, 9)
            except:
                pass

    def cleanup_mountdir(chrootdir, bindmounts):
        if bindmounts == "" or bindmounts == None:
            return
        chrootmounts = []
        mounts = bindmounts.split(";")
        for mount in mounts:
            if mount == "":
                continue
            srcdst = mount.split(":")
            if len(srcdst) == 1:
               srcdst.append("none")
            if srcdst[1] == "" or srcdst[1] == "none":
                srcdst[1] = srcdst[0]
            srcdst[1] = os.path.abspath(os.path.expanduser(srcdst[1]))
            tmpdir = chrootdir + "/" + srcdst[1]
            if os.path.isdir(tmpdir):
                if len(os.listdir(tmpdir)) == 0:
                    shutil.rmtree(tmpdir, ignore_errors = True)
                else:
                    print "Warning: dir %s isn't empty." % tmpdir
    
    chroot_lockfd.close()
    bind_unmount(globalmounts)
    if not fs_related.my_fuser(chroot_lock):
        tmpdir = chrootdir + "/parentroot"
        if len(os.listdir(tmpdir)) == 0:
            shutil.rmtree(tmpdir, ignore_errors = True)
        cleanup_resolv(chrootdir)
        if os.path.exists(chrootdir + "/etc/mtab"):
            os.unlink(chrootdir + "/etc/mtab")
        kill_processes(chrootdir)
    cleanup_mountdir(chrootdir, bindmounts)

def chroot(chrootdir, bindmounts = None, execute = "/bin/bash"):
    def mychroot():
        os.chroot(chrootdir)
        os.chdir("/")

    dev_null = os.open("/dev/null", os.O_WRONLY)
    files_to_check = ["/bin/bash", "/sbin/init"]
    
    architecture_found = False

    """ Register statically-linked qemu-arm if it is an ARM fs """
    qemu_emulator = None

    for ftc in files_to_check:
        ftc = "%s/%s" % (chrootdir,ftc)
        
        # Return code of 'file' is "almost always" 0 based on some man pages
        # so we need to check the file existance first.
        if not os.path.exists(ftc):
            continue

        filecmd = misc.find_binary_path("file")
        initp1 = subprocess.Popen([filecmd, ftc], stdout=subprocess.PIPE, stderr=dev_null)
        fileOutput = initp1.communicate()[0].strip().split("\n")
        
        for i in range(len(fileOutput)):
            if fileOutput[i].find("ARM") > 0:
                qemu_emulator = misc.setup_qemu_emulator(chrootdir, "arm")
                architecture_found = True
                break
            if fileOutput[i].find("Intel") > 0:
                architecture_found = True
                break
                
        if architecture_found:
            break
                
    os.close(dev_null)
    if not architecture_found:
        raise errors.CreatorError("Failed to get architecture from any of the following files %s from chroot." % files_to_check)

    try:
        print "Launching shell. Exit to continue."
        print "----------------------------------"
        globalmounts = setup_chrootenv(chrootdir, bindmounts)
        args = shlex.split(execute)
        subprocess.call(args, preexec_fn = mychroot)
    except OSError, (err, msg):
        raise errors.CreatorError("Failed to chroot: %s" % msg)
    finally:
        cleanup_chrootenv(chrootdir, bindmounts, globalmounts)
        if qemu_emulator:
            os.unlink(chrootdir + qemu_emulator)        
