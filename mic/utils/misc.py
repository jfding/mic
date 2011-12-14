#!/usr/bin/python -tt
#
# Copyright (c) 2010, 2011 Intel Inc.
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

from __future__ import with_statement
import os
import sys
import tempfile
import re
import shutil
import glob
import hashlib
import rpmmisc

try:
    import sqlite3 as sqlite
except ImportError:
    import sqlite

try:
    from xml.etree import cElementTree
except ImportError:
    import cElementTree
xmlparse = cElementTree.parse

from errors import *
from fs_related import *
from rpmmisc import myurlgrab
from proxy import get_proxy_for
import runner

from mic import msger

def save_ksconf_file(ksconf, release="latest", arch="ia32"):
    if not os.path.exists(ksconf):
        return

    with open(ksconf) as f:
        ksc = f.read()

    if "@ARCH@" in ksc or "@BUILD_ID@" in ksc:
        ksc = ksc.replace("@ARCH@", arch)
        ksc = ksc.replace("@BUILD_ID@", release)
        fd, ksconf = tempfile.mkstemp(prefix=os.path.basename(ksconf), dir="/tmp/")
        os.write(fd, ksc)
        os.close(fd)

        msger.debug('new ks path %s' % ksconf)

    return ksconf

def check_meego_chroot(rootdir):
    if not os.path.exists(rootdir + "/etc/moblin-release") and \
       not os.path.exists(rootdir + "/etc/meego-release"):
        raise CreatorError("Directory %s is not a MeeGo/Tizen chroot env"\
                           % rootdir)

    if not os.path.exists(rootdir + "/etc/inittab") or \
       not os.path.exists(rootdir + "/etc/rc.sysinit"):
        raise CreatorError("Lack of init scripts under %s: /etc/inittab, "\
                           "/etc/rc.sysinit" % rootdir)

    if not glob.glob(rootdir + "/boot/vmlinuz-*"):
        raise CreatorError("Failed to find kernel module under %s" % rootdir)

    return

def get_image_type(path):

    def _get_extension_name(path):
        match = re.search("(?<=\.)\w+$", path)
        if match:
            return match.group(0)
        else:
            return None

    if os.path.isdir(path):
        check_meego_chroot(path)
        return "fs"

    maptab = {
              "raw":"raw",
              "vmdk":"vmdk",
              "vdi":"vdi",
              "iso":"livecd",
              "usbimg":"liveusb",
             }

    extension = _get_extension_name(path)
    if extension in maptab:
        return maptab[extension]

    fd = open(path, "rb")
    file_header = fd.read(1024)
    fd.close()
    vdi_flag = "<<< Sun VirtualBox Disk Image >>>"
    if file_header[0:len(vdi_flag)] == vdi_flag:
        return maptab["vdi"]

    output = runner.outs(['file', path])
    isoptn = re.compile(r".*ISO 9660 CD-ROM filesystem.*(bootable).*")
    usbimgptn = re.compile(r".*x86 boot sector.*active.*")
    rawptn = re.compile(r".*x86 boot sector.*")
    vmdkptn = re.compile(r".*VMware. disk image.*")
    ext3fsimgptn = re.compile(r".*Linux.*ext3 filesystem data.*")
    ext4fsimgptn = re.compile(r".*Linux.*ext4 filesystem data.*")
    btrfsimgptn = re.compile(r".*BTRFS.*")
    if isoptn.match(output):
        return maptab["iso"]
    elif usbimgptn.match(output):
        return maptab["usbimg"]
    elif rawptn.match(output):
        return maptab["raw"]
    elif vmdkptn.match(output):
        return maptab["vmdk"]
    elif ext3fsimgptn.match(output):
        return "ext3fsimg"
    elif ext4fsimgptn.match(output):
        return "ext4fsimg"
    elif btrfsimgptn.match(output):
        return "btrfsimg"
    else:
        raise CreatorError("Cannot detect the type of image: %s" % path)

def get_file_size(file):
    """ Return size in MB unit, TODO: rewrite """
    rc, duOutput  = runner.runtool(['du', "-s", "-b", "-B", "1M", file])
    if rc != 0:
        raise CreatorError("Failed to run %s" % du)

    size1 = int(duOutput.split()[0])
    rc, duOutput = runner.runtool(['du', "-s", "-B", "1M", file])
    if rc != 0:
        raise CreatorError("Failed to run %s" % du)

    size2 = int(duOutput.split()[0])
    if size1 > size2:
        return size1
    else:
        return size2

def get_filesystem_avail(fs):
    vfstat = os.statvfs(fs)
    return vfstat.f_bavail * vfstat.f_bsize

def convert_image(srcimg, srcfmt, dstimg, dstfmt):
    #convert disk format
    if dstfmt != "raw":
        raise CreatorError("Invalid destination image format: %s" % dstfmt)
    msger.debug("converting %s image to %s" % (srcimg, dstimg))
    if srcfmt == "vmdk":
        path = find_binary_path("qemu-img")
        argv = [path, "convert", "-f", "vmdk", srcimg, "-O", dstfmt,  dstimg]
    elif srcfmt == "vdi":
        path = find_binary_path("VBoxManage")
        argv = [path, "internalcommands", "converttoraw", srcimg, dstimg]
    else:
        raise CreatorError("Invalid soure image format: %s" % srcfmt)

    rc = runner.show(argv)
    if rc == 0:
        msger.debug("convert successful")
    if rc != 0:
        raise CreatorError("Unable to convert disk to %s" % dstfmt)

def uncompress_squashfs(squashfsimg, outdir):
    """Uncompress file system from squshfs image"""
    unsquashfs = find_binary_path("unsquashfs")
    args = [ unsquashfs, "-d", outdir, squashfsimg ]
    rc = runner.show(args)
    if (rc != 0):
        raise SquashfsError("Failed to uncompress %s." % squashfsimg)

def mkdtemp(dir = "/var/tmp", prefix = "mic-tmp-"):
    makedirs(dir)
    return tempfile.mkdtemp(dir = dir, prefix = prefix)

def get_temp_reponame(baseurl):
    md5obj = hashlib.md5(baseurl)
    tmpreponame = "%s" % md5obj.hexdigest()
    return tmpreponame

def get_repostrs_from_ks(ks):
    kickstart_repos = []
    for repodata in ks.handler.repo.repoList:
        repostr = ""
        if hasattr(repodata, "name") and repodata.name:
            repostr += ",name:" + repodata.name
        if hasattr(repodata, "baseurl") and repodata.baseurl:
            repostr += ",baseurl:" + repodata.baseurl
        if hasattr(repodata, "mirrorlist") and repodata.mirrorlist:
            repostr += ",mirrorlist:" + repodata.mirrorlist
        if hasattr(repodata, "includepkgs") and repodata.includepkgs:
            repostr += ",includepkgs:" + ";".join(repodata.includepkgs)
        if hasattr(repodata, "excludepkgs") and repodata.excludepkgs:
            repostr += ",excludepkgs:" + ";".join(repodata.excludepkgs)
        if hasattr(repodata, "cost") and repodata.cost:
            repostr += ",cost:%d" % repodata.cost
        if hasattr(repodata, "save") and repodata.save:
            repostr += ",save:"
        if hasattr(repodata, "proxy") and repodata.proxy:
            repostr += ",proxy:" + repodata.proxy
        if hasattr(repodata, "proxyuser") and repodata.proxy_username:
            repostr += ",proxyuser:" + repodata.proxy_username
        if  hasattr(repodata, "proxypasswd") and repodata.proxy_password:
            repostr += ",proxypasswd:" + repodata.proxy_password
        if repostr.find("name:") == -1:
            repostr = ",name:%s" % get_temp_reponame(repodata.baseurl)
        if hasattr(repodata, "debuginfo") and repodata.debuginfo:
            repostr += ",debuginfo:"
        if hasattr(repodata, "source") and repodata.source:
            repostr += ",source:"
        if  hasattr(repodata, "gpgkey") and repodata.gpgkey:
            repostr += ",gpgkey:" + repodata.gpgkey
        kickstart_repos.append(repostr[1:])
    return kickstart_repos

def get_uncompressed_data_from_url(url, filename, proxies):
    filename = myurlgrab(url, filename, proxies)
    suffix = None
    if filename.endswith(".gz"):
        suffix = ".gz"
        runner.quiet(['gunzip', "-f", filename])
    elif filename.endswith(".bz2"):
        suffix = ".bz2"
        runner.quiet(['bunzip2', "-f", filename])
    if suffix:
        filename = filename.replace(suffix, "")
    return filename

def get_metadata_from_repo(baseurl, proxies, cachedir, reponame, filename):
    url = str(baseurl + "/" + filename)
    filename_tmp = str("%s/%s/%s" % (cachedir, reponame, os.path.basename(filename)))
    return get_uncompressed_data_from_url(url,filename_tmp,proxies)

def get_metadata_from_repos(repostrs, cachedir):
    my_repo_metadata = []
    for repostr in repostrs:
        reponame = None
        baseurl = None
        proxy = None
        items = repostr.split(",")
        for item in items:
            subitems = item.split(":")
            if subitems[0] == "name":
                reponame = subitems[1]
            if subitems[0] == "baseurl":
                baseurl = item[8:]
            if subitems[0] == "proxy":
                proxy = item[6:]
            if subitems[0] in ("http", "https", "ftp", "ftps", "file"):
                baseurl = item
        if not proxy:
            proxy = get_proxy_for(baseurl)
        proxies = None
        if proxy:
           proxies = {str(proxy.split(":")[0]):str(proxy)}
        makedirs(cachedir + "/" + reponame)
        url = str(baseurl + "/repodata/repomd.xml")
        filename = str("%s/%s/repomd.xml" % (cachedir, reponame))
        repomd = myurlgrab(url, filename, proxies)
        try:
            root = xmlparse(repomd)
        except SyntaxError:
            raise CreatorError("repomd.xml syntax error.")

        ns = root.getroot().tag
        ns = ns[0:ns.rindex("}")+1]

        patterns = None
        for elm in root.getiterator("%sdata" % ns):
            if elm.attrib["type"] == "patterns":
                patterns = elm.find("%slocation" % ns).attrib['href']
                break

        comps = None
        for elm in root.getiterator("%sdata" % ns):
            if elm.attrib["type"] == "group_gz":
                comps = elm.find("%slocation" % ns).attrib['href']
                break
        if not comps:
            for elm in root.getiterator("%sdata" % ns):
                if elm.attrib["type"] == "group":
                    comps = elm.find("%slocation" % ns).attrib['href']
                    break

        primary_type = None
        for elm in root.getiterator("%sdata" % ns):
            if elm.attrib["type"] == "primary_db":
                primary_type=".sqlite"
                break

        if not primary_type:
            for elm in root.getiterator("%sdata" % ns):
                if elm.attrib["type"] == "primary":
                    primary_type=".xml"
                    break

        if not primary_type:
            continue

        primary = elm.find("%slocation" % ns).attrib['href']
        primary = get_metadata_from_repo(baseurl, proxies, cachedir, reponame, primary)

        if patterns:
            patterns = get_metadata_from_repo(baseurl, proxies, cachedir, reponame, patterns)

        if comps:
            comps = get_metadata_from_repo(baseurl, proxies, cachedir, reponame, comps)

        """ Get repo key """
        try:
            repokey = get_metadata_from_repo(baseurl, proxies, cachedir, reponame, "repodata/repomd.xml.key")
        except CreatorError:
            repokey = None
            msger.warning("\ncan't get %s/%s" % (baseurl, "repodata/repomd.xml.key"))

        my_repo_metadata.append({"name":reponame, "baseurl":baseurl, "repomd":repomd, "primary":primary, "cachedir":cachedir, "proxies":proxies, "patterns":patterns, "comps":comps, "repokey":repokey})

    return my_repo_metadata

def get_arch(repometadata):
    archlist = []
    for repo in repometadata:
        if repo["primary"].endswith(".xml"):
            root = xmlparse(repo["primary"])
            ns = root.getroot().tag
            ns = ns[0:ns.rindex("}")+1]
            for elm in root.getiterator("%spackage" % ns):
                if elm.find("%sarch" % ns).text not in ("noarch", "src"):
                    arch = elm.find("%sarch" % ns).text
                    if arch not in archlist:
                        archlist.append(arch)
        elif repo["primary"].endswith(".sqlite"):
            con = sqlite.connect(repo["primary"])
            for row in con.execute("select arch from packages where arch not in (\"src\", \"noarch\")"):
                if row[0] not in archlist:
                    archlist.append(row[0])

            con.close()

    uniq_arch = []
    for i in range(len(archlist)):
        if archlist[i] not in rpmmisc.archPolicies.keys():
            continue
        need_append = True
        j = 0
        while j < len(uniq_arch):
            if archlist[i] in rpmmisc.archPolicies[uniq_arch[j]].split(':'):
                need_append = False
                break
            if uniq_arch[j] in rpmmisc.archPolicies[archlist[i]].split(':'):
                if need_append:
                    uniq_arch[j] = archlist[i]
                    need_append = False
                else:
                    uniq_arch.remove(uniq_arch[j])
                    continue
            j += 1
        if need_append:
             uniq_arch.append(archlist[i])

    return uniq_arch, archlist

def get_package(pkg, repometadata, arch = None):
    ver = ""
    target_repo = None
    for repo in repometadata:
        if repo["primary"].endswith(".xml"):
            root = xmlparse(repo["primary"])
            ns = root.getroot().tag
            ns = ns[0:ns.rindex("}")+1]
            for elm in root.getiterator("%spackage" % ns):
                if elm.find("%sname" % ns).text == pkg:
                    if elm.find("%sarch" % ns).text != "src":
                        version = elm.find("%sversion" % ns)
                        tmpver = "%s-%s" % (version.attrib['ver'], version.attrib['rel'])
                        if tmpver > ver:
                            ver = tmpver
                            location = elm.find("%slocation" % ns)
                            pkgpath = "%s" % location.attrib['href']
                            target_repo = repo
                        break
        if repo["primary"].endswith(".sqlite"):
            con = sqlite.connect(repo["primary"])
            if not arch:
                for row in con.execute("select version, release,location_href from packages where name = \"%s\" and arch != \"src\"" % pkg):
                    tmpver = "%s-%s" % (row[0], row[1])
                    if tmpver > ver:
                        pkgpath = "%s" % row[2]
                        target_repo = repo
                    break
            else:
                for row in con.execute("select version, release,location_href from packages where name = \"%s\"" % pkg):
                    tmpver = "%s-%s" % (row[0], row[1])
                    if tmpver > ver:
                        pkgpath = "%s" % row[2]
                        target_repo = repo
                    break
            con.close()
    if target_repo:
        makedirs("%s/%s/packages" % (target_repo["cachedir"], target_repo["name"]))
        url = str(target_repo["baseurl"] + "/" + pkgpath)
        filename = str("%s/%s/packages/%s" % (target_repo["cachedir"], target_repo["name"], os.path.basename(pkgpath)))
        pkg = myurlgrab(url, filename, target_repo["proxies"])
        return pkg
    else:
        return None

def get_source_name(pkg, repometadata):

    def get_bin_name(pkg):
        m = re.match("(.*)-(.*)-(.*)\.(.*)\.rpm", pkg)
        if m:
            return m.group(1)
        return None

    def get_src_name(srpm):
        m = re.match("(.*)-(\d+.*)-(\d+\.\d+).src.rpm", srpm)
        if m:
            return m.group(1)
        return None

    ver = ""
    target_repo = None

    pkg_name = get_bin_name(pkg)
    if not pkg_name:
        return None

    for repo in repometadata:
        if repo["primary"].endswith(".xml"):
            root = xmlparse(repo["primary"])
            ns = root.getroot().tag
            ns = ns[0:ns.rindex("}")+1]
            for elm in root.getiterator("%spackage" % ns):
                if elm.find("%sname" % ns).text == pkg_name:
                    if elm.find("%sarch" % ns).text != "src":
                        version = elm.find("%sversion" % ns)
                        tmpver = "%s-%s" % (version.attrib['ver'], version.attrib['rel'])
                        if tmpver > ver:
                            ver = tmpver
                            fmt = elm.find("%sformat" % ns)
                            if fmt:
                                fns = fmt.getchildren()[0].tag
                                fns = fns[0:fns.rindex("}")+1]
                                pkgpath = fmt.find("%ssourcerpm" % fns).text
                                target_repo = repo
                        break

        if repo["primary"].endswith(".sqlite"):
            con = sqlite.connect(repo["primary"])
            for row in con.execute("select version, release, rpm_sourcerpm from packages where name = \"%s\" and arch != \"src\"" % pkg_name):
                tmpver = "%s-%s" % (row[0], row[1])
                if tmpver > ver:
                    pkgpath = "%s" % row[2]
                    target_repo = repo
                break
            con.close()
    if target_repo:
        return get_src_name(pkgpath)
    else:
        return None

def get_release_no(repometadata, distro="meego"):
    import subprocess

    cpio = find_binary_path("cpio")
    rpm2cpio = find_binary_path("rpm2cpio")
    release_pkg = get_package("%s-release" % distro, repometadata)
    if release_pkg:
        tmpdir = mkdtemp()
        oldcwd = os.getcwd()
        os.chdir(tmpdir)
        p1 = subprocess.Popen([rpm2cpio, release_pkg], stdout = subprocess.PIPE)
        p2 = subprocess.Popen([cpio, "-idv"], stdin = p1.stdout, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        p2.communicate()
        f = open("%s/etc/%s-release" % (tmpdir, distro), "r")
        content = f.read()
        f.close()
        os.chdir(oldcwd)
        shutil.rmtree(tmpdir, ignore_errors = True)
        return content.split(" ")[2]
    else:
        return "UNKNOWN"

def get_kickstarts_from_repos(repometadata):
    kickstarts = []
    for repo in repometadata:
        try:
            root = xmlparse(repo["repomd"])
        except SyntaxError:
            raise CreatorError("repomd.xml syntax error.")

        ns = root.getroot().tag
        ns = ns[0:ns.rindex("}")+1]

        for elm in root.getiterator("%sdata" % ns):
            if elm.attrib["type"] == "image-config":
                break

        if elm.attrib["type"] != "image-config":
            continue

        location = elm.find("%slocation" % ns)
        image_config = str(repo["baseurl"] + "/" + location.attrib["href"])
        filename = str("%s/%s/image-config.xml%s" % (repo["cachedir"], repo["name"], suffix))

        image_config = get_uncompressed_data_from_url(image_config,filename,repo["proxies"])

        try:
            root = xmlparse(image_config)
        except SyntaxError:
            raise CreatorError("image-config.xml syntax error.")

        for elm in root.getiterator("config"):
            path = elm.find("path").text
            path = path.replace("images-config", "image-config")
            description = elm.find("description").text
            makedirs(os.path.dirname("%s/%s/%s" % (repo["cachedir"], repo["name"], path)))
            url = path
            if "http" not in path:
                url = str(repo["baseurl"] + "/" + path)
            filename = str("%s/%s/%s" % (repo["cachedir"], repo["name"], path))
            path = myurlgrab(url, filename, repo["proxies"])
            kickstarts.append({"filename":path,"description":description})
        return kickstarts

def select_ks(ksfiles):
    msger.info("Available kickstart files:")
    i = 0
    for ks in ksfiles:
        i += 1
        msger.raw("\t%d. %s (%s)" % (i, ks["description"], os.path.basename(ks["filename"])))

    while True:
        choice = raw_input("Please input your choice and press ENTER. [1..%d] ? " % i)
        if choice.lower() == "q":
            sys.exit(1)
        if choice.isdigit():
            choice = int(choice)
            if choice >= 1 and choice <= i:
                break

    return ksfiles[choice-1]["filename"]

def get_pkglist_in_patterns(group, patterns):
    found = False
    pkglist = []
    try:
        root = xmlparse(patterns)
    except SyntaxError:
        raise SyntaxError("%s syntax error." % patterns)

    for elm in list(root.getroot()):
        ns = elm.tag
        ns = ns[0:ns.rindex("}")+1]
        name = elm.find("%sname" % ns)
        summary = elm.find("%ssummary" % ns)
        if name.text == group or summary.text == group:
            found = True
            break

    if not found:
        return pkglist

    found = False
    for requires in list(elm):
        if requires.tag.endswith("requires"):
            found = True
            break

    if not found:
        return pkglist

    for pkg in list(requires):
        pkgname = pkg.attrib["name"]
        if pkgname not in pkglist:
            pkglist.append(pkgname)

    return pkglist

def get_pkglist_in_comps(group, comps):
    found = False
    pkglist = []
    try:
        root = xmlparse(comps)
    except SyntaxError:
        raise SyntaxError("%s syntax error." % comps)

    for elm in root.getiterator("group"):
        id = elm.find("id")
        name = elm.find("name")
        if id.text == group or name.text == group:
            packagelist = elm.find("packagelist")
            found = True
            break

    if not found:
        return pkglist

    for require in elm.getiterator("packagereq"):
        if require.tag.endswith("packagereq"):
            pkgname = require.text
        if pkgname not in pkglist:
            pkglist.append(pkgname)

    return pkglist

def is_statically_linked(binary):
    return ", statically linked, " in runner.outs(['file', binary])

def setup_qemu_emulator(rootdir, arch):
    # mount binfmt_misc if it doesn't exist
    if not os.path.exists("/proc/sys/fs/binfmt_misc"):
        modprobecmd = find_binary_path("modprobe")
        runner.show([modprobecmd, "binfmt_misc"])
    if not os.path.exists("/proc/sys/fs/binfmt_misc/register"):
        mountcmd = find_binary_path("mount")
        runner.show([mountcmd, "-t", "binfmt_misc", "none", "/proc/sys/fs/binfmt_misc"])

    # qemu_emulator is a special case, we can't use find_binary_path
    # qemu emulator should be a statically-linked executable file
    qemu_emulator = "/usr/bin/qemu-arm"
    if not os.path.exists(qemu_emulator) or not is_statically_linked(qemu_emulator):
        qemu_emulator = "/usr/bin/qemu-arm-static"
    if not os.path.exists(qemu_emulator):
        raise CreatorError("Please install a statically-linked qemu-arm")

    # qemu emulator version check
    armv7_list = [arch for arch in rpmmisc.archPolicies.keys() if arch.startswith('armv7')]
    if arch in armv7_list:  # need qemu (>=0.13.0)
        qemuout = runner.outs([qemu_emulator, "-h"])
        m = re.search("version\s*([.\d]+)", qemuout)
        if m:
            qemu_version = m.group(1)
            if qemu_version < "0.13":
                raise CreatorError("Requires %s version >=0.13 for %s" % (qemu_emulator, arch))
        else:
            msger.warning("Can't get version info of %s, please make sure it's higher than 0.13.0" % qemu_emulator)

    if not os.path.exists(rootdir + "/usr/bin"):
        makedirs(rootdir + "/usr/bin")
    shutil.copy(qemu_emulator, rootdir + qemu_emulator)

    # disable selinux, selinux will block qemu emulator to run
    if os.path.exists("/usr/sbin/setenforce"):
        msger.info('Try to disable selinux')
        runner.show(["/usr/sbin/setenforce", "0"])

    node = "/proc/sys/fs/binfmt_misc/arm"
    if is_statically_linked(qemu_emulator) and os.path.exists(node):
        return qemu_emulator

    # unregister it if it has been registered and is a dynamically-linked executable
    if not is_statically_linked(qemu_emulator) and os.path.exists(node):
        qemu_unregister_string = "-1\n"
        fd = open("/proc/sys/fs/binfmt_misc/arm", "w")
        fd.write(qemu_unregister_string)
        fd.close()

    # register qemu emulator for interpreting other arch executable file
    if not os.path.exists(node):
        qemu_arm_string = ":arm:M::\\x7fELF\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28\\x00:\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfa\\xff\\xff\\xff:%s:\n" % qemu_emulator
        fd = open("/proc/sys/fs/binfmt_misc/register", "w")
        fd.write(qemu_arm_string)
        fd.close()

    return qemu_emulator

def SrcpkgsDownload(pkgs, repometadata, instroot, cachedir):
    def get_source_repometadata(repometadata):
        src_repometadata=[]
        for repo in repometadata:
            if repo["name"].endswith("-source"):
                src_repometadata.append(repo)
        if src_repometadata:
            return src_repometadata
        return None

    def get_src_name(srpm):
        m = re.match("(.*)-(\d+.*)-(\d+\.\d+).src.rpm", srpm)
        if m:
            return m.group(1)
        return None

    src_repometadata = get_source_repometadata(repometadata)

    if not src_repometadata:
        msger.warning("No source repo found")
        return None

    src_pkgs = []
    lpkgs_dict = {}
    lpkgs_path = []
    for repo in src_repometadata:
        cachepath = "%s/%s/packages/*.src.rpm" %(cachedir, repo["name"])
        lpkgs_path += glob.glob(cachepath)

    for lpkg in lpkgs_path:
        lpkg_name = get_src_name(os.path.basename(lpkg))
        lpkgs_dict[lpkg_name] = lpkg
    localpkgs = lpkgs_dict.keys()

    cached_count = 0
    destdir = instroot+'/usr/src/SRPMS'
    if not os.path.exists(destdir):
        os.makedirs(destdir)

    srcpkgset = set()
    for _pkg in pkgs:
        srcpkg_name = get_source_name(_pkg, repometadata)
        if not srcpkg_name:
            continue
        srcpkgset.add(srcpkg_name)

    for pkg in list(srcpkgset):
        if pkg in localpkgs:
            cached_count += 1
            shutil.copy(lpkgs_dict[pkg], destdir)
            src_pkgs.append(os.path.basename(lpkgs_dict[pkg]))
        else:
            src_pkg = get_package(pkg, src_repometadata, 'src')
            if src_pkg:
                shutil.copy(src_pkg, destdir)
                src_pkgs.append(src_pkg)
    msger.info("%d source packages gotten from cache" %cached_count)

    return src_pkgs

def strip_end(text, suffix):
    if not text.endswith(suffix):
        return text
    return text[:-len(suffix)]
