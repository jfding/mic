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

import os, sys, re
import rpm
import subprocess
import logging

class RPMInstallCallback:
    """ Command line callback class for callbacks from the RPM library.
    """

    def __init__(self, ts, output=1):
        self.output = output
        self.callbackfilehandles = {}
        self.total_actions = 0
        self.total_installed = 0
        self.installed_pkg_names = []
        self.total_removed = 0
        self.mark = "+"
        self.marks = 40
        self.lastmsg = None
        self.tsInfo = None # this needs to be set for anything else to work
        self.ts = ts
        self.logString = []

    def _dopkgtup(self, hdr):
        tmpepoch = hdr['epoch']
        if tmpepoch is None: epoch = '0'
        else: epoch = str(tmpepoch)

        return (hdr['name'], hdr['arch'], epoch, hdr['version'], hdr['release'])

    def _makeHandle(self, hdr):
        handle = '%s:%s.%s-%s-%s' % (hdr['epoch'], hdr['name'], hdr['version'],
          hdr['release'], hdr['arch'])

        return handle

    def _localprint(self, msg):
        if self.output:
            print msg

    def _makefmt(self, percent, progress = True):
        l = len(str(self.total_actions))
        size = "%s.%s" % (l, l)
        fmt_done = "[%" + size + "s/%" + size + "s]"
        done = fmt_done % (self.total_installed + self.total_removed,
                           self.total_actions)
        marks = self.marks - (2 * l)
        width = "%s.%s" % (marks, marks)
        fmt_bar = "%-" + width + "s"
        if progress:
            bar = fmt_bar % (self.mark * int(marks * (percent / 100.0)), )
            fmt = "\r  %-10.10s: " + bar + " " + done
        else:
            bar = fmt_bar % (self.mark * marks, )
            fmt = "  %-10.10s: "  + bar + " " + done
        return fmt

    def _logPkgString(self, hdr):
        """return nice representation of the package for the log"""
        (n,a,e,v,r) = self._dopkgtup(hdr)
        if e == '0':
            pkg = '%s.%s %s-%s' % (n, a, v, r)
        else:
            pkg = '%s.%s %s:%s-%s' % (n, a, e, v, r)

        return pkg

    def callback(self, what, bytes, total, h, user):
        if what == rpm.RPMCALLBACK_TRANS_START:
            if bytes == 6:
                self.total_actions = total

        elif what == rpm.RPMCALLBACK_TRANS_PROGRESS:
            pass

        elif what == rpm.RPMCALLBACK_TRANS_STOP:
            pass

        elif what == rpm.RPMCALLBACK_INST_OPEN_FILE:
            self.lastmsg = None
            hdr = None
            if h is not None:
                rpmloc = h
                hdr = readRpmHeader(self.ts, h)
                handle = self._makeHandle(hdr)
                fd = os.open(rpmloc, os.O_RDONLY)
                self.callbackfilehandles[handle]=fd
                self.total_installed += 1
                self.installed_pkg_names.append(hdr['name'])
                return fd
            else:
                self._localprint("No header - huh?")

        elif what == rpm.RPMCALLBACK_INST_CLOSE_FILE:
            hdr = None
            if h is not None:
                rpmloc = h
                hdr = readRpmHeader(self.ts, h)
                handle = self._makeHandle(hdr)
                os.close(self.callbackfilehandles[handle])
                fd = 0

                # log stuff
                #pkgtup = self._dopkgtup(hdr)
                self.logString.append(self._logPkgString(hdr))

        elif what == rpm.RPMCALLBACK_INST_PROGRESS:
            if h is not None:
                percent = (self.total_installed*100L)/self.total_actions
                if self.output and (sys.stdout.isatty() or self.total_installed == self.total_actions):
                    fmt = self._makefmt(percent)
                    msg = fmt % ("Installing")
                    if msg != self.lastmsg:
                        sys.stdout.write(msg)
                        sys.stdout.flush()
                        self.lastmsg = msg
                        if self.total_installed == self.total_actions:
                             sys.stdout.write("\n")
                             logging.info('\n'.join(self.logString))

        elif what == rpm.RPMCALLBACK_UNINST_START:
            pass

        elif what == rpm.RPMCALLBACK_UNINST_PROGRESS:
            pass

        elif what == rpm.RPMCALLBACK_UNINST_STOP:
            self.total_removed += 1

        elif what == rpm.RPMCALLBACK_REPACKAGE_START:
            pass
        elif what == rpm.RPMCALLBACK_REPACKAGE_STOP:
            pass
        elif what == rpm.RPMCALLBACK_REPACKAGE_PROGRESS:
            pass

def readRpmHeader(ts, filename):
    """ Read an rpm header. """

    fd = os.open(filename, os.O_RDONLY)
    h = ts.hdrFromFdno(fd)
    os.close(fd)
    return h

def splitFilename(filename):
    """ Pass in a standard style rpm fullname

        Return a name, version, release, epoch, arch, e.g.::
            foo-1.0-1.i386.rpm returns foo, 1.0, 1, i386
            1:bar-9-123a.ia64.rpm returns bar, 9, 123a, 1, ia64
    """

    if filename[-4:] == '.rpm':
        filename = filename[:-4]

    archIndex = filename.rfind('.')
    arch = filename[archIndex+1:]

    relIndex = filename[:archIndex].rfind('-')
    rel = filename[relIndex+1:archIndex]

    verIndex = filename[:relIndex].rfind('-')
    ver = filename[verIndex+1:relIndex]

    epochIndex = filename.find(':')
    if epochIndex == -1:
        epoch = ''
    else:
        epoch = filename[:epochIndex]

    name = filename[epochIndex + 1:verIndex]
    return name, ver, rel, epoch, arch

def getCanonX86Arch(arch):
    #
    if arch == "i586":
        f = open("/proc/cpuinfo", "r")
        lines = f.readlines()
        f.close()
        for line in lines:
            if line.startswith("model name") and line.find("Geode(TM)") != -1:
                return "geode"
        return arch
    # only athlon vs i686 isn't handled with uname currently
    if arch != "i686":
        return arch

    # if we're i686 and AuthenticAMD, then we should be an athlon
    f = open("/proc/cpuinfo", "r")
    lines = f.readlines()
    f.close()
    for line in lines:
        if line.startswith("vendor") and line.find("AuthenticAMD") != -1:
            return "athlon"
        # i686 doesn't guarantee cmov, but we depend on it
        elif line.startswith("flags") and line.find("cmov") == -1:
            return "i586"

    return arch

def getCanonX86_64Arch(arch):
    if arch != "x86_64":
        return arch

    vendor = None
    f = open("/proc/cpuinfo", "r")
    lines = f.readlines()
    f.close()
    for line in lines:
        if line.startswith("vendor_id"):
            vendor = line.split(':')[1]
            break
    if vendor is None:
        return arch

    if vendor.find("Authentic AMD") != -1 or vendor.find("AuthenticAMD") != -1:
        return "amd64"
    if vendor.find("GenuineIntel") != -1:
        return "ia32e"
    return arch

def getCanonArch():
    arch = os.uname()[4]

    if (len(arch) == 4 and arch[0] == "i" and arch[2:4] == "86"):
        return getCanonX86Arch(arch)

    if arch == "x86_64":
        return getCanonX86_64Arch(arch)

    return arch

# dict mapping arch -> ( multicompat, best personality, biarch personality )
multilibArches = {
                   "x86_64":  ( "athlon", "x86_64", "athlon" ),
                   "sparc64v": ( "sparc", "sparcv9v", "sparc64v" ),
                   "sparc64": ( "sparc", "sparcv9", "sparc64" ),
                   "ppc64":   ( "ppc", "ppc", "ppc64" ),
                   "s390x":   ( "s390", "s390x", "s390" ),
                 }

arches = {
    # ia32
    "athlon": "i686",
    "i686": "i586",
    "geode": "i586",
    "i586": "i486",
    "i486": "i386",
    "i386": "noarch",

    # amd64
    "x86_64": "athlon",
    "amd64": "x86_64",
    "ia32e": "x86_64",

    # ppc
    "ppc64pseries": "ppc64",
    "ppc64iseries": "ppc64",
    "ppc64": "ppc",
    "ppc": "noarch",

    # s390{,x}
    "s390x": "s390",
    "s390": "noarch",

    # sparc
    "sparc64v": "sparc64",
    "sparc64v": "sparcv9v",
    "sparc64": "sparcv9",
    "sparcv9v": "sparcv9",
    "sparcv9": "sparcv8",
    "sparcv8": "sparc",
    "sparc": "noarch",

    # alpha
    "alphaev7":   "alphaev68",
    "alphaev68":  "alphaev67",
    "alphaev67":  "alphaev6",
    "alphaev6":   "alphapca56",
    "alphapca56": "alphaev56",
    "alphaev56":  "alphaev5",
    "alphaev5":   "alphaev45",
    "alphaev45":  "alphaev4",
    "alphaev4":   "alpha",
    "alpha":      "noarch",

    # arm
    "armv7nhl": "armv7hl",
    "armv7hl": "noarch",
    "armv7l": "armv6l",
    "armv6l": "armv5tejl",
    "armv5tejl": "armv5tel",
    "armv5tel": "noarch",

    # super-h
    "sh4a": "sh4",
    "sh4": "noarch",
    "sh3": "noarch",

    #itanium
    "ia64": "noarch",
    }

def isMultiLibArch(arch=None):
    """returns true if arch is a multilib arch, false if not"""
    if arch is None:
        arch = canonArch

    if not arches.has_key(arch): # or we could check if it is noarch
        return 0

    if multilibArches.has_key(arch):
        return 1

    if multilibArches.has_key(arches[arch]):
        return 1

    return 0

def getBaseArch():
    myarch = getCanonArch()
    if not arches.has_key(myarch):
        return myarch

    if isMultiLibArch(arch=myarch):
        if multilibArches.has_key(myarch):
            return myarch
        else:
            return arches[myarch]

    if arches.has_key(myarch):
        basearch = myarch
        value = arches[basearch]
        while value != 'noarch':
            basearch = value
            value = arches[basearch]

        return basearch

def checkRpmIntegrity(bin_rpm, package):
    argv = [bin_rpm, "--checksig", "--nogpg", package]
    dev_null = os.open("/dev/null", os.O_WRONLY)
    try:
        ret = subprocess.call(argv, stdout = dev_null, stderr = dev_null)
    finally:
        os.close(dev_null)

    return ret

def checkSig(ts, package):
    """ Takes a transaction set and a package, check it's sigs,
        return 0 if they are all fine
        return 1 if the gpg key can't be found
        return 2 if the header is in someway damaged
        return 3 if the key is not trusted
        return 4 if the pkg is not gpg or pgp signed
    """

    value = 0
    currentflags = ts.setVSFlags(0)
    fdno = os.open(package, os.O_RDONLY)
    try:
        hdr = ts.hdrFromFdno(fdno)

    except rpm.error, e:
        if str(e) == "public key not availaiable":
            value = 1
        if str(e) == "public key not available":
            value = 1
        if str(e) == "public key not trusted":
            value = 3
        if str(e) == "error reading package header":
            value = 2
    else:
        error, siginfo = getSigInfo(hdr)
        if error == 101:
            os.close(fdno)
            del hdr
            value = 4
        else:
            del hdr

    try:
        os.close(fdno)
    except OSError:
        pass

    ts.setVSFlags(currentflags) # put things back like they were before
    return value

def getSigInfo(hdr):
    """ checks signature from an hdr hand back signature information and/or
        an error code
    """

    import locale
    locale.setlocale(locale.LC_ALL, 'C')

    string = '%|DSAHEADER?{%{DSAHEADER:pgpsig}}:{%|RSAHEADER?{%{RSAHEADER:pgpsig}}:{%|SIGGPG?{%{SIGGPG:pgpsig}}:{%|SIGPGP?{%{SIGPGP:pgpsig}}:{(none)}|}|}|}|'
    siginfo = hdr.sprintf(string)
    if siginfo != '(none)':
        error = 0
        sigtype, sigdate, sigid = siginfo.split(',')
    else:
        error = 101
        sigtype = 'MD5'
        sigdate = 'None'
        sigid = 'None'

    infotuple = (sigtype, sigdate, sigid)
    return error, infotuple
