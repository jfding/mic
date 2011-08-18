#!/usr/bin/python -tt
#
# Copyright 2008, 2009, 2010 Intel, Inc.
#
# This copyrighted material is made available to anyone wishing to use, modify,
# copy, or redistribute it subject to the terms and conditions of the GNU
# General Public License v.2.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat
# trademarks that are incorporated in the source code or documentation are not
# subject to the GNU General Public License and may only be used or replicated
# with the express permission of Red Hat, Inc.
#

from __future__ import with_statement
import os, sys
import shutil
import subprocess

import mic.utils.fs_related as fs_related
import mic.utils.misc as misc
import mic.utils.errors as errors
from mic import msger

chroot_lockfd = -1
chroot_lock = ""
BIND_MOUNTS = (
                "/proc",
                "/proc/sys/fs/binfmt_misc",
                "/sys",
                "/dev",
                "/dev/pts",
                "/dev/shm",
                "/var/lib/dbus",
                "/var/run/dbus",
                "/var/lock",
              )

def cleanup_after_chroot(targettype,imgmount,tmpdir,tmpmnt):
    if imgmount and targettype == "img":
        imgmount.cleanup()

    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors = True)

    if tmpmnt:
        shutil.rmtree(tmpmnt, ignore_errors = True)

def check_bind_mounts(chrootdir, bindmounts):
    chrootmounts = []
    for mount in bindmounts.split(";"):
        if not mount:
            continue

        srcdst = mount.split(":")
        if len(srcdst) == 1:
           srcdst.append("none")

        if not os.path.isdir(srcdst[0]):
            return False

        if srcdst[1] == "" or srcdst[1] == "none":
            srcdst[1] = None

        if srcdst[0] in BIND_MOUNTS or srcdst[0] == '/':
            continue

        if chrootdir:
            if not srcdst[1]:
                srcdst[1] = os.path.abspath(os.path.expanduser(srcdst[0]))
            else:
                srcdst[1] = os.path.abspath(os.path.expanduser(srcdst[1]))

            tmpdir = chrootdir + "/" + srcdst[1]
            if os.path.isdir(tmpdir):
                msger.warning("Warning: dir %s has existed."  % tmpdir)

    return True

def cleanup_mounts(chrootdir):
    dev_null = os.open("/dev/null", os.O_WRONLY)
    umountcmd = misc.find_binary_path("umount")
    for point in BIND_MOUNTS:
        args = [ umountcmd, "-l", chrootdir + point ]
        subprocess.call(args, stdout=dev_null, stderr=dev_null)

    abs_chrootdir = os.path.abspath(chrootdir)
    with open('/proc/mounts') as f:
        for line in f:
            if abs_chrootdir in line:
                point = line.split()[1]

                if abs_chrootdir == point:
                    continue

                args = [ umountcmd, "-l", point ]
                ret = subprocess.call(args, stdout=dev_null, stderr=dev_null)
                if ret != 0:
                    msger.warning("failed to unmount %s" % point)
                    os.close(dev_null)
                    return ret

    os.close(dev_null)
    return 0

def setup_chrootenv(chrootdir, bindmounts = None):
    global chroot_lockfd, chroot_lock

    def get_bind_mounts(chrootdir, bindmounts):
        chrootmounts = []
        if bindmounts in ("", None):
            bindmounts = ""

        for mount in bindmounts.split(";"):
            if not mount:
                continue

            srcdst = mount.split(":")
            srcdst[0] = os.path.abspath(os.path.expanduser(srcdst[0]))
            if len(srcdst) == 1:
               srcdst.append("none")

            if not os.path.isdir(srcdst[0]):
                continue

            if srcdst[0] in BIND_MOUNTS or srcdst[0] == '/':
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
        for pt in BIND_MOUNTS:
            chrootmounts.append(fs_related.BindChrootMount(pt, chrootdir, None))

        chrootmounts.append(fs_related.BindChrootMount("/", chrootdir, "/parentroot", "ro"))

        for kernel in os.listdir("/lib/modules"):
            chrootmounts.append(fs_related.BindChrootMount("/lib/modules/" + kernel, chrootdir, None, "ro"))

        return chrootmounts

    def bind_mount(chrootmounts):
        for b in chrootmounts:
            msger.info("bind_mount: %s -> %s" % (b.src, b.dest))
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
            msger.info("bind_unmount: %s -> %s" % (b.src, b.dest))
            b.unmount()

    def cleanup_resolv(chrootdir):
        fd = open(chrootdir + "/etc/resolv.conf", "w")
        fd.truncate(0)
        fd.close()

    def kill_processes(chrootdir):
        import glob
        for fp in glob.glob("/proc/*/root"):
            try:
                if os.readlink(fp) == chrootdir:
                    pid = int(fp.split("/")[2])
                    os.kill(pid, 9)
            except:
                pass

    def cleanup_mountdir(chrootdir, bindmounts):
        if bindmounts == "" or bindmounts == None:
            return
        chrootmounts = []
        for mount in bindmounts.split(";"):
            if not mount:
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
                    msger.warning("Warning: dir %s isn't empty." % tmpdir)

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

        for line in subprocess.Popen([filecmd, ftc],
                                     stdout=subprocess.PIPE,
                                     stderr=dev_null).communicate()[0].strip().splitlines():
            if 'ARM' in line:
                qemu_emulator = misc.setup_qemu_emulator(chrootdir, "arm")
                architecture_found = True
                break

            if 'Intel' in line:
                architecture_found = True
                break

        if architecture_found:
            break

    os.close(dev_null)
    if not architecture_found:
        raise errors.CreatorError("Failed to get architecture from any of the following files %s from chroot." % files_to_check)

    try:
        msger.info("Launching shell. Exit to continue.\n----------------------------------")
        globalmounts = setup_chrootenv(chrootdir, bindmounts)
        subprocess.call(execute, preexec_fn = mychroot, shell=True)

    except OSError, (err, msg):
        raise errors.CreatorError("Failed to chroot: %s" % msg)

    finally:
        cleanup_chrootenv(chrootdir, bindmounts, globalmounts)
        if qemu_emulator:
            os.unlink(chrootdir + qemu_emulator)
