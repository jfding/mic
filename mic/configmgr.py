#!/usr/bin/python -tt
#
# Copyright (c) 2011 Intel, Inc.
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

import os, sys
import ConfigParser

from mic import kickstart
from mic import msger
from mic.utils import misc, runner
from mic.utils import errors

DEFAULT_GSITECONF = '/etc/mic/mic.conf'

DEFAULT_OUTDIR = '.'
DEFAULT_TMPDIR = '/var/tmp/mic'
DEFAULT_CACHEDIR = DEFAULT_TMPDIR + '/cache'

DEFAULT_CREATE = {
    "tmpdir": DEFAULT_TMPDIR,
    "cachedir": DEFAULT_CACHEDIR,
    "outdir": DEFAULT_OUTDIR,
    "arch": None,
    "pkgmgr": "yum",
    "name": "output",
    "ksfile": None,
    "ks": None,
    "repomd": None,
    "local_pkgs_path": None,
    "release": None,
    "logfile": None,
    "record_pkgs": [],
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

    def selinux_check(self, arch, ks):
        """ If a user needs to use btrfs or creates ARM image, selinux must be disabled at start """

        paths = ["/usr/sbin/getenforce",
                 "/usr/bin/getenforce",
                 "/sbin/getenforce",
                 "/bin/getenforce",
                 "/usr/local/sbin/getenforce",
                 "/usr/locla/bin/getenforce"
                ]

        for path in paths:
            if os.path.exists(path):
                selinux_status = runner.outs([path])
                if  arch and arch.startswith("arm") and selinux_status == "Enforcing":
                    raise errors.ConfigError("Can't create arm image if selinux is enabled, please disbale it and try again")

                use_btrfs = False
                parts = ks.handler.partition.partitions
                for part in ks.handler.partition.partitions:
                    if part.fstype == "btrfs":
                        use_btrfs = True
                        break

                if use_btrfs and selinux_status == "Enforcing":
                    raise errors.ConfigError("Can't create image useing btrfs filesystem if selinux is enabled, please disbale it and try again")

                break

    def parse_kickstart(self, ksconf=None):
        if not ksconf:
            return

        ks = kickstart.read_kickstart(ksconf)

        self.create['ks'] = ks
        self.create['name'] = os.path.splitext(os.path.basename(ksconf))[0]

        self.selinux_check (self.create['arch'], ks)

        msger.info("Retrieving repo metadata:")
        ksrepos = misc.get_repostrs_from_ks(ks)
        self.create['repomd'] = misc.get_metadata_from_repos(ksrepos, self.create['cachedir'])
        msger.raw(" DONE")

        target_archlist = misc.get_arch(self.create['repomd'])
        if self.create['arch']:
            if self.create['arch'] not in target_archlist:
                raise errors.ConfigError("Invalid arch %s for repository. Valid arches: %s"\
                                         % (self.create['arch'], ', '.join(target_archlist)))
        else:
            if len(target_archlist) == 1:
                self.create['arch'] = str(target_archlist[0])
                msger.info("\nUse detected arch %s." % target_archlist[0])
            else:
                raise errors.ConfigError("Please specify a valid arch, "\
                                         "your choise can be: " % ', '.join(target_archlist))

        kickstart.resolve_groups(self.create, self.create['repomd'])

def getConfigMgr():
    return configmgr

configmgr = ConfigMgr()
