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

import os, sys
import ConfigParser
import mic.utils as utils
import mic.utils.errors as errors
from mic import kickstart
from mic import msger

DEFAULT_GSITECONF='/etc/mic/mic.conf'

DEFAULT_OUTDIR='.'
DEFAULT_TMPDIR='/var/tmp'
DEFAULT_CACHEDIR='/var/cache'

DEFAULT_CREATE = {
    "tmpdir": DEFAULT_TMPDIR,
    "cachedir": DEFAULT_CACHEDIR,
    "outdir": DEFAULT_OUTDIR,
    "arch": None,
    "pkgmgr": "zypp",
    "name": "output",
    "ksfile": None,
    "ks": None,
    "repomd": None,
}

class ConfigMgr(object):
    def __init__(self, ksconf=None, siteconf=None):
        self.common = {}
        self.create = {}
        self.convert = {}
        self.chroot = {}
        self.ksconf = None
        self.siteconf = None

        # initial create
        for key in DEFAULT_CREATE.keys():
            self.create[key] = DEFAULT_CREATE[key]

        # initial options from siteconf
        self._siteconf = siteconf
        if not self.siteconf:
            self._siteconf = DEFAULT_GSITECONF

        self._ksconf = ksconf

    def __set_siteconf(self, siteconf):
        try:
            self.siteconf = siteconf
            self.parse_siteconf(siteconf)
        except ConfigParser.Error, error:
            raise errors.ConfigError("%s" % error)
    def __get_siteconf(self):
        return self.siteconf
    _siteconf = property(__get_siteconf, __set_siteconf)

    def __set_ksconf(self, ksconf):
        self.ksconf = ksconf
        self.parse_kickstart(ksconf)
    def __get_ksconf(self):
        return self.ksconf
    _ksconf = property(__get_ksconf, __set_ksconf)

    def parse_siteconf(self, siteconf = None):
        if not siteconf:
            return

        from ConfigParser import SafeConfigParser
        siteconf_parser = SafeConfigParser()
        if not os.path.exists(siteconf):
            raise errors.ConfigError("Failed to find config file: %s" % siteconf)
        siteconf_parser.read(siteconf)

        for option in siteconf_parser.options('common'):
            value = siteconf_parser.get('common', option)
            self.common[option] = value

        for option in siteconf_parser.options('create'):
            value = siteconf_parser.get('create', option)
            self.create[option] = value

        for option in siteconf_parser.options('convert'):
            value = siteconf_parser.get('convert', option)
            self.convert[option] = value

        for option in siteconf_parser.options('chroot'):
            value = siteconf_parser.get('chroot', option)
            self.chroot[option] = value

    def parse_kickstart(self, ksconf=None):
        if not ksconf:
            return

        try:
            ks = kickstart.read_kickstart(ksconf)
            ksrepos = utils.misc.get_repostrs_from_ks(ks)
            msger.info("Retrieving repo metadata:")
            repometadata = utils.misc.get_metadata_from_repos(ksrepos, self.create['cachedir'])
            msger.raw(" DONE")

            self.create['ks'] = ks
            self.create['repomd'] = repometadata
            self.create['name'] = os.path.splitext(os.path.basename(ksconf))[0]
        except Exception, e:
            raise errors.KsError("Unable to load kickstart file '%s': %s" % (ksconf, e))

    def setProperty(self, key, value):
        if not hasattr(self, key):
            return False

        if key == 'ksconf':
            self._ksconf = value
            return True

        if key == 'siteconf':
            self._siteconf = value
            return True

        return setattr(self, key, value)

    def getProperty(self, key):
        if not hasattr(self, key):
            return None

        return getattr(self, key)

    def setCategoryProperty(self, category, key, value):
        if not hasattr(self, category):
            raise errors.ConfigError("Error to parse %s", category)
        categ = getattr(self, category)
        categ[key] = value

    def getCategoryProperty(self, category, key):
        if not hasattr(self, category):
            raise errors.ConfigError("Error to parse %s", category)
        categ = getattr(self, category)
        return categ[key]

    def getCreateOption(self, key):
        if not self.create.has_key(key):
            raise errors.ConfigError("Attribute Error: not such attribe %s" % key)
        return self.create[key]

    def getConvertOption(self, key):
        if not self.convert.has_key(key):
            raise errors.ConfigError("Attribute Error: not such attribe %s" % key)
        return self.convert[key]

    def getChrootOption(self, key):
        if not self.chroot.has_key(key):
            raise errors.ConfigError("Attribute Error: not such attribe %s" % key)
        return self.chroot[key]

    def dumpAllConfig(self):
        # just for debug
        sys.stdout.write("create options:\n")
        for key in self.create.keys():
            sys.stdout.write("%-8s= %s\n" % (key, self.create[key]))
        sys.stdout.write("convert options:\n")
        for key in self.convert.keys():
            sys.stdout.write("%-8s= %s\n" % (key, self.ccnvert[key]))
        sys.stdout.write("chroot options:\n")
        for key in self.chroot.keys():
            sys.stdout.write("%-8s= %s\n" % (key, self.chroot[key]))

def getConfigMgr():
    return configmgr

configmgr = ConfigMgr()
