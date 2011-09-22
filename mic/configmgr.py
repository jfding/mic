#!/usr/bin/python -tt
#
# Copyright 2011 Intel, Inc.
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

from mic import kickstart
from mic import msger
from mic.utils import misc
from mic.utils import errors

DEFAULT_GSITECONF='/etc/mic/mic.conf'

DEFAULT_OUTDIR='.'
DEFAULT_TMPDIR='/var/tmp/mic'
DEFAULT_CACHEDIR='/var/tmp/mic/cache'

DEFAULT_CREATE = {
    "tmpdir": DEFAULT_TMPDIR,
    "cachedir": DEFAULT_CACHEDIR,
    "outdir": DEFAULT_OUTDIR,
    "arch": "i586",
    "pkgmgr": "yum",
    "name": "output",
    "ksfile": None,
    "ks": None,
    "repomd": None,
    "local_pkgs_path": None,
    "release": None,
}

class ConfigMgr(object):
    def __init__(self, ksconf=None, siteconf=None):
        # reset config options
        self.reset()

        # initial options from siteconf
        self._siteconf = siteconf
        if not self.__siteconf:
            self._siteconf = DEFAULT_GSITECONF

    def reset(self):
        self.common = {}
        self.create = {}
        self.convert = {}
        self.chroot = {}
        self.__ksconf = None
        self.__siteconf = None

        # initial create
        for key in DEFAULT_CREATE.keys():
            self.create[key] = DEFAULT_CREATE[key]

    def __set_siteconf(self, siteconf):
        try:
            self.__siteconf = siteconf
            self.parse_siteconf(siteconf)
        except ConfigParser.Error, error:
            raise errors.ConfigError("%s" % error)
    def __get_siteconf(self):
        return self.__siteconf
    _siteconf = property(__get_siteconf, __set_siteconf)

    def __set_ksconf(self, ksconf):
        if not os.path.isfile(ksconf):
            msger.error('Cannot find ks file: %s' % ksconf)

        self.__ksconf = ksconf
        self.parse_kickstart(ksconf)
    def __get_ksconf(self):
        return self.__ksconf
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

        ks = kickstart.read_kickstart(ksconf)

        self.create['ks'] = ks
        self.create['name'] = os.path.splitext(os.path.basename(ksconf))[0]

        msger.info("Retrieving repo metadata:")
        ksrepos = misc.get_repostrs_from_ks(ks)
        self.create['repomd'] = misc.get_metadata_from_repos(ksrepos, self.create['cachedir'])
        msger.raw(" DONE")

def getConfigMgr():
    return configmgr

configmgr = ConfigMgr()
