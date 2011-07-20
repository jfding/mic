#
# misc.py : miscellaneous utilities
#
# Copyright 2010, Intel Inc.
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
import subprocess
import logging
import tempfile
import re
import shutil
import glob
import xml.dom.minidom
import hashlib
import urlparse
import locale
import codecs

try:
    import sqlite3 as sqlite
except ImportError:
    import sqlite
import _sqlitecache

try:
    from xml.etree import cElementTree
except ImportError:
    import cElementTree
xmlparse = cElementTree.parse

from errors import *
from fs_related import *


def setlocale():
    try:
        locale.setlocale(locale.LC_ALL,'')
    except locale.Error:
        os.environ['LC_ALL'] = 'C'
        locale.setlocale(locale.LC_ALL,'C')
    sys.stdout = codecs.getwriter(locale.getpreferredencoding())(sys.stdout)
    sys.stdout.errors = 'replace'

def get_extension_name(path):
    match = re.search("(?<=\.)\w+$", path)
    if match:
        return match.group(0)
    else:
        return None

def get_image_type(path):
    if os.path.isdir(path):
        if ismeego(path):
            return "fs"
        return None
    maptab = {"raw":"raw", "vmdk":"vmdk", "vdi":"vdi", "iso":"livecd", "usbimg":"liveusb"}
    extension = get_extension_name(path)
    if extension in ("raw", "vmdk", "vdi", "iso", "usbimg"):
        return maptab[extension]

    fd = open(path, "rb")
    file_header = fd.read(1024)
    fd.close()
    vdi_flag = "<<< Sun VirtualBox Disk Image >>>"
    if file_header[0:len(vdi_flag)] == vdi_flag:
        return maptab["vdi"]

    dev_null = os.open("/dev/null", os.O_WRONLY)
    filecmd = find_binary_path("file")
    args = [ filecmd, path ]
    file = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=dev_null)
    output = file.communicate()[0]
    os.close(dev_null)
    isoptn = re.compile(r".*ISO 9660 CD-ROM filesystem.*(bootable).*")
    usbimgptn = re.compile(r".*x86 boot sector.*active.*")
    rawptn = re.compile(r".*x86 boot sector.*")
    vmdkptn = re.compile(r".*VMware. disk image.*")
    ext3fsimgptn = re.compile(r".*Linux.*ext3 filesystem data.*")
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
    else:
        return None

def get_file_size(file):
    """Return size in MB unit"""
    du = find_binary_path("du")
    dev_null = os.open("/dev/null", os.O_WRONLY)
    duProc = subprocess.Popen([du, "-s", "-b", "-B", "1M", file],
                               stdout=subprocess.PIPE, stderr=dev_null)
    duOutput = duProc.communicate()[0]
    if duProc.returncode:
        raise CreatorError("Failed to run %s" % du)

    size1 = int(duOutput.split()[0])
    duProc = subprocess.Popen([du, "-s", "-B", "1M", file],
                               stdout=subprocess.PIPE, stderr=dev_null)
    duOutput = duProc.communicate()[0]
    if duProc.returncode:
        raise CreatorError("Failed to run %s" % du)

    size2 = int(duOutput.split()[0])
    os.close(dev_null)
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
    logging.debug("converting %s image to %s" % (srcimg, dstimg))
    if srcfmt == "vmdk":
        path = find_binary_path("qemu-img")
        argv = [path, "convert", "-f", "vmdk", srcimg, "-O", dstfmt,  dstimg]
    elif srcfmt == "vdi":
        path = find_binary_path("VBoxManage")
        argv = [path, "internalcommands", "converttoraw", srcimg, dstimg]
    else:
        raise CreatorError("Invalid soure image format: %s" % srcfmt)

    rc = subprocess.call(argv)
    if rc == 0:
        logging.debug("convert successful")
    if rc != 0:
        raise CreatorError("Unable to convert disk to %s" % dstfmt)

def myxcopytree(src, dst):
    dev_null = os.open("/dev/null", os.O_WRONLY)
    dirnames = os.listdir(src)
    copycmd = find_binary_path("cp")
    for dir in dirnames:
        args = [ copycmd, "-af", src + "/" + dir, dst ]
        subprocess.call(args, stdout=dev_null, stderr=dev_null)
    os.close(dev_null)
    ignores = ["dev/fd", "dev/stdin", "dev/stdout", "dev/stderr", "etc/mtab"]
    for exclude in ignores:
        if os.path.exists(dst + "/" + exclude):
            os.unlink(dst + "/" + exclude)

def uncompress_squashfs(squashfsimg, outdir):
    """Uncompress file system from squshfs image"""
    unsquashfs = find_binary_path("unsquashfs")
    args = [ unsquashfs, "-d", outdir, squashfsimg ]
    rc = subprocess.call(args)
    if (rc != 0):
        raise SquashfsError("Failed to uncompress %s." % squashfsimg)

def mkdtemp(dir = "/var/tmp", prefix = "mic-tmp-"):
    makedirs(dir)
    return tempfile.mkdtemp(dir = dir, prefix = prefix)

def ismeego(rootdir):
    ret = False
    if (os.path.exists(rootdir + "/etc/moblin-release") \
       or os.path.exists(rootdir + "/etc/meego-release")) \
       and os.path.exists(rootdir + "/etc/inittab") \
       and os.path.exists(rootdir + "/etc/rc.sysinit") \
       and glob.glob(rootdir + "/boot/vmlinuz-*"):
        ret = True

    return ret


def is_meego_bootstrap(rootdir):
    ret = False
    if (os.path.exists(rootdir + "/etc/moblin-release") \
       or os.path.exists(rootdir + "/etc/meego-release")) \
       and os.path.exists(rootdir + "/usr/bin/python") \
       and os.path.exists(rootdir + "/usr/bin/mic-image-creator"):
        ret = True

    return ret


_my_proxies = {}
_my_noproxy = None
_my_noproxy_list = []

def set_proxy_environ():
    global _my_noproxy, _my_proxies
    if not _my_proxies:
        return
    for key in _my_proxies.keys():
        os.environ[key + "_proxy"] = _my_proxies[key]
    if not _my_noproxy:
        return
    os.environ["no_proxy"] = _my_noproxy

def unset_proxy_environ():
   if os.environ.has_key("http_proxy"):
       del os.environ["http_proxy"]
   if os.environ.has_key("https_proxy"):
       del os.environ["https_proxy"]
   if os.environ.has_key("ftp_proxy"):
       del os.environ["ftp_proxy"]
   if os.environ.has_key("all_proxy"):
       del os.environ["all_proxy"]
   if os.environ.has_key("no_proxy"):
       del os.environ["no_proxy"]
   if os.environ.has_key("HTTP_PROXY"):
       del os.environ["HTTP_PROXY"]
   if os.environ.has_key("HTTPS_PROXY"):
       del os.environ["HTTPS_PROXY"]
   if os.environ.has_key("FTP_PROXY"):
       del os.environ["FTP_PROXY"]
   if os.environ.has_key("ALL_PROXY"):
       del os.environ["ALL_PROXY"]
   if os.environ.has_key("NO_PROXY"):
       del os.environ["NO_PROXY"]

def _set_proxies(proxy = None, no_proxy = None):
    """Return a dictionary of scheme -> proxy server URL mappings."""
    global _my_noproxy, _my_proxies
    _my_proxies = {}
    _my_noproxy = None
    proxies = []
    if proxy:
       proxies.append(("http_proxy", proxy))
    if no_proxy:
       proxies.append(("no_proxy", no_proxy))

    """Get proxy settings from environment variables if not provided"""
    if not proxy and not no_proxy:
       proxies = os.environ.items()

       """ Remove proxy env variables, urllib2 can't handle them correctly """
       unset_proxy_environ()

    for name, value in proxies:
        name = name.lower()
        if value and name[-6:] == '_proxy':
            if name[0:2] != "no":
                _my_proxies[name[:-6]] = value
            else:
                _my_noproxy = value

def ip_to_int(ip):
    ipint=0
    shift=24
    for dec in ip.split("."):
        ipint |= int(dec) << shift
        shift -= 8
    return ipint

def int_to_ip(val):
    ipaddr=""
    shift=0
    for i in range(4):
        dec = val >> shift
        dec &= 0xff
        ipaddr = ".%d%s" % (dec, ipaddr)
        shift += 8
    return ipaddr[1:]

def isip(host):
    if host.replace(".", "").isdigit():
        return True
    return False

def set_noproxy_list():
    global _my_noproxy, _my_noproxy_list
    _my_noproxy_list = []
    if not _my_noproxy:
        return
    for item in _my_noproxy.split(","):
        item = item.strip()
        if not item:
            continue
        if item[0] != '.' and item.find("/") == -1:
            """ Need to match it """
            _my_noproxy_list.append({"match":0,"needle":item})
        elif item[0] == '.':
            """ Need to match at tail """
            _my_noproxy_list.append({"match":1,"needle":item})
        elif item.find("/") > 3:
            """ IP/MASK, need to match at head """
            needle = item[0:item.find("/")].strip()
            ip = ip_to_int(needle)
            netmask = 0
            mask = item[item.find("/")+1:].strip()

            if mask.isdigit():
                netmask = int(mask)
                netmask = ~((1<<(32-netmask)) - 1)
                ip &= netmask
            else:
                shift=24
                netmask=0
                for dec in mask.split("."):
                    netmask |= int(dec) << shift
                    shift -= 8
                ip &= netmask
            _my_noproxy_list.append({"match":2,"needle":ip,"netmask":netmask})

def isnoproxy(url):
    (scheme, host, path, parm, query, frag) = urlparse.urlparse(url)
    if '@' in host:
        user_pass, host = host.split('@', 1)
    if ':' in host:
        host, port = host.split(':', 1)
    hostisip = isip(host)
    for item in _my_noproxy_list:
        if hostisip and item["match"] <= 1:
            continue
        if item["match"] == 2 and hostisip:
            if (ip_to_int(host) & item["netmask"]) == item["needle"]:
                return True
        if item["match"] == 0:
            if host == item["needle"]:
                return True
        if item["match"] == 1:
            if host.rfind(item["needle"]) > 0:
                return True
    return False

def set_proxies(proxy = None, no_proxy = None):
    _set_proxies(proxy, no_proxy)
    set_noproxy_list()

def get_proxy(url):
    if url[0:4] == "file" or isnoproxy(url):
        return None
    type = url[0:url.index(":")]
    proxy = None
    if _my_proxies.has_key(type):
        proxy = _my_proxies[type]
    elif _my_proxies.has_key("http"):
        proxy = _my_proxies["http"]
    else:
        proxy = None
    return proxy

def remap_repostr(repostr, siteconf):
    items = repostr.split(",")
    name = None
    baseurl = None
    for item in items:
        subitems = item.split(":")
        if subitems[0] == "name":
            name = subitems[1]
        if subitems[0] == "baseurl":
            baseurl = item[8:]
    if not baseurl:
        baseurl = repostr

    for section in siteconf._sections:
        if section != "main":
            if not siteconf.has_option(section, "enabled") or siteconf.get(section, "enabled") == "0":
                continue
            if siteconf.has_option(section, "equalto"):
                equalto = siteconf.get(section, "equalto")
                if (name and equalto == name) or (baseurl and equalto == baseurl):
                    remap_baseurl = siteconf.get(section, "baseurl")
                    repostr = repostr.replace(baseurl, remap_baseurl)
                    return repostr

    return repostr


def get_temp_reponame(baseurl):
    md5obj = hashlib.md5(baseurl)
    tmpreponame = "%s" % md5obj.hexdigest()
    return tmpreponame

def get_repostr(repo, siteconf = None):
    if siteconf:
        repo = remap_repostr(repo, siteconf)
    keys = ("baseurl", "mirrorlist", "name", "cost", "includepkgs", "excludepkgs", "proxy", "save", "proxyuser", "proxypasswd", "debuginfo", "source", "gpgkey")
    repostr = "repo"
    items = repo.split(",")
    if len(items) == 1:
        subitems = items[0].split(":")
        if len(subitems) == 1:
            url = subitems[0]
            repostr += " --baseurl=%s" % url
        elif subitems[0] == "baseurl":
            url = items[0][8:]
            repostr += " --baseurl=%s" % url
        elif subitems[0] in ("http", "ftp", "https", "ftps", "file"):
            url = items[0]
            repostr += " --baseurl=%s" % url
        else:
            raise ValueError("Invalid repo string")
        if url.find("://") == -1 \
           or url[0:url.index("://")] not in ("http", "ftp", "https", "ftps", "file") \
           or url.find("/", url.index("://")+3) == -1:
            raise ValueError("Invalid repo string")
    else:
        if repo.find("baseurl:") == -1 and repo.find("mirrorlist:") == -1:
            raise ValueError("Invalid repo string")
        url = None
        for item in items:
            if not item:
                continue
            subitems = item.split(":")
            if subitems[0] in keys:
                if subitems[0] in ("baseurl", "mirrorlist"):
                    url = item[len(subitems[0])+1:]
                if subitems[0] in ("save", "debuginfo", "source"):
                    repostr += " --%s" % subitems[0]
                elif subitems[0] in ("includepkgs", "excludepkgs"):
                    repostr += " --%s=%s" % (subitems[0], item[len(subitems[0])+1:].replace(";", ","))
                else:
                    repostr += " --%s=%s" % (subitems[0], item[len(subitems[0])+1:])
            else:
                raise ValueError("Invalid repo string")
    if url.find("://") != -1 \
       and url[0:url.index("://")] in ("http", "ftp", "https", "ftps", "file") \
       and url.find("/", url.index("://")+3) != -1:
        if repostr.find("--proxy=") == -1:
            proxy = get_proxy(url)
            if proxy:
                repostr += " --proxy=%s" % proxy
    else:
        raise ValueError("Invalid repo string")

    if repostr.find("--name=") == -1:
        repostr += " --name=%s" % get_temp_reponame(url)

    return repostr

DEFAULT_SITECONF_GLOBAL="/etc/mic2/mic2.conf"
DEFAULT_SITECONF_USER="~/.mic2.conf"

def read_siteconf(siteconf = None):
    from ConfigParser import SafeConfigParser

    my_siteconf_parser = SafeConfigParser()
    if not siteconf:
        global_siteconf = DEFAULT_SITECONF_GLOBAL
        if os.path.isfile(global_siteconf):
            my_siteconf_parser.read(global_siteconf)

        local_siteconf = os.path.expanduser(DEFAULT_SITECONF_USER)
        if os.path.isfile(local_siteconf):
            my_siteconf_parser.read(local_siteconf)
    else:
        my_siteconf_parser.read(siteconf)

    if not my_siteconf_parser.sections():
        return None
    else:
        return my_siteconf_parser

def output_siteconf(siteconf):
    output = ""
    if not siteconf:
        return output

    for section in siteconf.sections():
        output += "[%s]\n" % section
        for option in siteconf.options(section):
            output += "%s=%s\n" % (option, siteconf.get(section, option))
        output += "\n\n"

    print output
    return output

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

def get_repostrs_from_siteconf(siteconf):
    site_repos = []
    if not siteconf:
        return site_repos

    for section in siteconf._sections:
        if section != "main":
            repostr = ""
            if siteconf.has_option(section, "enabled") \
               and siteconf.get(section, "enabled") == "1" \
               and (not siteconf.has_option(section, "equalto") or not siteconf.get(section, "equalto")):
                if siteconf.has_option(section, "name") and siteconf.get(section, "name"):
                    repostr += ",name:%s" % siteconf.get(section, "name")
                if siteconf.has_option(section, "baseurl") and siteconf.get(section, "baseurl"):
                    repostr += ",baseurl:%s" % siteconf.get(section, "baseurl")
                if siteconf.has_option(section, "mirrorlist") and siteconf.get(section, "mirrorlist"):
                    repostr += ",mirrorlist:%s" % siteconf.get(section, "mirrorlist")
                if siteconf.has_option(section, "includepkgs") and siteconf.get(section, "includepkgs"):
                    repostr += ",includepkgs:%s" % siteconf.get(section, "includepkgs").replace(",", ";")
                if siteconf.has_option(section, "excludepkgs") and siteconf.get(section, "excludepkgs"):
                    repostr += ",excludepkgs:%s" % siteconf.get(section, "excludepkgs").replace(",", ";")
                if siteconf.has_option(section, "cost") and siteconf.get(section, "cost"):
                    repostr += ",cost:%s" % siteconf.get(section, "cost")
                if siteconf.has_option(section, "save") and siteconf.get(section, "save"):
                    repostr += ",save:"
                if siteconf.has_option(section, "proxy") and siteconf.get(section, "proxy"):
                    repostr += ",proxy:%s" % siteconf.get(section, "proxy")
                if siteconf.has_option(section, "proxy_username") and siteconf.get(section, "proxy_username"):
                    repostr += ",proxyuser:%s" % siteconf.get(section, "proxy_username")
                if siteconf.has_option(section, "proxy_password") and siteconf.get(section, "proxy_password"):
                    repostr += ",proxypasswd:%s" % siteconf.get(section, "proxy_password")
            if repostr != "":
                if repostr.find("name:") == -1:
                    repostr = ",name:%s" % get_temp_reponame()
                site_repos.append(repostr[1:])
    return site_repos

def get_uncompressed_data_from_url(url, filename, proxies):
    filename = myurlgrab(url, filename, proxies)
    suffix = None
    if filename.endswith(".gz"):
        suffix = ".gz"
        gunzip = find_binary_path('gunzip')
        subprocess.call([gunzip, "-f", filename])
    elif filename.endswith(".bz2"):
        suffix = ".bz2"
        bunzip2 = find_binary_path('bunzip2')
        subprocess.call([bunzip2, "-f", filename])
    if suffix:
        filename = filename.replace(suffix, "")
    return filename

def get_metadata_from_repo(baseurl, proxies, cachedir, reponame, filename):
    url = str(baseurl + "/" + filename)
    filename_tmp = str("%s/%s/%s" % (cachedir, reponame, os.path.basename(filename)))
    return get_uncompressed_data_from_url(url,filename_tmp,proxies)

def get_metadata_from_repos(repostrs, cachedir):
    if not cachedir:
        CreatorError("No cache dir defined.")

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
            proxy = get_proxy(baseurl)
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
            print "Warning: can't get %s/%s" % (baseurl, "repodata/repomd.xml.key")

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
    return archlist


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
    print "Available kickstart files:"
    i = 0
    for ks in ksfiles:
        i += 1
        print "\t%d. %s (%s)" % (i, ks["description"], os.path.basename(ks["filename"]))
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
    ret = False
    dev_null = os.open("/dev/null", os.O_WRONLY)
    filecmd = find_binary_path("file")
    args = [ filecmd, binary ]
    file = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=dev_null)
    output = file.communicate()[0]
    os.close(dev_null)
    if output.find(", statically linked, ") > 0:
        ret = True
    return ret

def setup_qemu_emulator(rootdir, arch):
    # mount binfmt_misc if it doesn't exist
    if not os.path.exists("/proc/sys/fs/binfmt_misc"):
        modprobecmd = find_binary_path("modprobe")
        subprocess.call([modprobecmd, "binfmt_misc"])
    if not os.path.exists("/proc/sys/fs/binfmt_misc/register"):
        mountcmd = find_binary_path("mount")
        subprocess.call([mountcmd, "-t", "binfmt_misc", "none", "/proc/sys/fs/binfmt_misc"])

    # qemu_emulator is a special case, we can't use find_binary_path
    # qemu emulator should be a statically-linked executable file
    qemu_emulator = "/usr/bin/qemu-arm"
    if not os.path.exists(qemu_emulator) or not is_statically_linked(qemu_emulator):
        qemu_emulator = "/usr/bin/qemu-arm-static"
    if not os.path.exists(qemu_emulator):
        raise CreatorError("Please install a statically-linked qemu-arm")
    if not os.path.exists(rootdir + "/usr/bin"):
        makedirs(rootdir + "/usr/bin")
    shutil.copy(qemu_emulator, rootdir + qemu_emulator)

    # disable selinux, selinux will block qemu emulator to run
    if os.path.exists("/usr/sbin/setenforce"):
        subprocess.call(["/usr/sbin/setenforce", "0"])

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

def create_release(config, destdir, name, outimages, release):
    """ TODO: This functionality should really be in creator.py inside the
    ImageCreator class. """

    # For virtual machine images, we have a subdir for it, this is unnecessary
    # for release
    thatsubdir = None
    for i in range(len(outimages)):
        file = outimages[i]
        if not os.path.isdir(file) and os.path.dirname(file) != destdir:
            thatsubdir = os.path.dirname(file)
            newfile = os.path.join(destdir, os.path.basename(file))
            shutil.move(file, newfile)
            outimages[i] = newfile
    if thatsubdir:
        shutil.rmtree(thatsubdir, ignore_errors = True)

    """ Create release directory and files """
    os.system ("cp %s %s/%s.ks" % (config, destdir, name))
    # When building a release we want to make sure the .ks 
    # file generates the same build even when --release= is not used.
    fd = open(config, "r")
    kscont = fd.read()
    fd.close()
    kscont = kscont.replace("@BUILD_ID@",release)
    fd = open("%s/%s.ks" % (destdir,name), "w")
    fd.write(kscont)
    fd.close()
    outimages.append("%s/%s.ks" % (destdir,name))

    # Using system + mv, because of * in filename.
    os.system ("mv %s/*-pkgs.txt %s/%s.packages" % (destdir, destdir, name))
    outimages.append("%s/%s.packages" % (destdir,name))

    d = os.listdir(destdir)
    for f in d:
        if f.endswith(".iso"):
            ff = f.replace(".iso", ".img")
            os.rename("%s/%s" %(destdir, f ), "%s/%s" %(destdir, ff))
            outimages.append("%s/%s" %(destdir, ff))
        elif f.endswith(".usbimg"):
            ff = f.replace(".usbimg", ".img")
            os.rename("%s/%s" %(destdir, f ), "%s/%s" %(destdir, ff))
            outimages.append("%s/%s" %(destdir, ff))

    fd = open(destdir + "/MANIFEST", "w")
    d = os.listdir(destdir)
    for f in d:
        if f == "MANIFEST":
            continue
        if os.path.exists("/usr/bin/md5sum"):
            p = subprocess.Popen(["/usr/bin/md5sum", "-b", "%s/%s" %(destdir, f )],
                             stdout=subprocess.PIPE)
            (md5sum, errorstr) = p.communicate()
            if p.returncode != 0:
                logging.warning("Can't generate md5sum for image %s/%s" %(destdir, f ))
            else:
                md5sum = md5sum.split(" ")[0]
                fd.write(md5sum+" "+f+"\n")

    outimages.append("%s/MANIFEST" % destdir)
    fd.close()

    """ Update the file list. """
    updated_list = []
    for file in outimages:
        if os.path.exists("%s" % file):
            updated_list.append(file)

    return updated_list

def get_local_distro():
    print "Local linux distribution:"
    for file in glob.glob("/etc/*-release"):
        fd = open(file, "r")
        content = fd.read()
        fd.close()
        print content
    if os.path.exists("/etc/issue"):
        fd = open("/etc/issue", "r")
        content = fd.read()
        fd.close()
        print content
    print "Local Kernel version: " + os.uname()[2]

def check_mic_installation(argv):
    creator_name = os.path.basename(argv[0])
    if os.path.exists("/usr/local/bin/" + creator_name) \
        and os.path.exists("/usr/bin/" + creator_name):
        raise CreatorError("There are two mic2 installations existing, this will result in some unpredictable errors, the reason is installation path of mic2 binary is different from  installation path of mic2 source on debian-based distros, please remove one of them to ensure it can work normally.")

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
        print "No source repo found"
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
            return None
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
    print '--------------------------------------------------'
    print "%d source packages gotten from cache" %cached_count

    return src_pkgs

def add_optparser(arg):
    def decorate(f):
        if not hasattr(f, "optparser"):
            f.optparser = arg
        return f
    return decorate
