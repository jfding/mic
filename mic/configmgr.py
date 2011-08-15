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
import logging
import mic.utils as utils

DEFAULT_GSITECONF='/etc/mic/mic.conf'

DEFAULT_OUTDIR='.'
DEFAULT_TMPDIR='/var/tmp'
DEFAULT_CACHEDIR='/var/cache'

class ConfigMgr(object):
    def __init__(self, siteconf=None, ksconf=None):
        self.common = {}
        self.create = {}
        self.convert = {}
        self.chroot = {}

        self.siteconf = siteconf
        self.ksconf = ksconf

        self.create["tmpdir"] = DEFAULT_TMPDIR
        self.create["cachedir"] = DEFAULT_CACHEDIR
        self.create["outdir"] = DEFAULT_OUTDIR

        self.init_siteconf(self.siteconf)
        self.init_kickstart(self.ksconf)

    def init_siteconf(self, siteconf = None):
        from ConfigParser import SafeConfigParser
        siteconf_parser = SafeConfigParser()
        siteconf_files = [DEFAULT_GSITECONF]

        if not os.path.exists(DEFAULT_GSITECONF):
            logging.debug("No default config file: %s" % DEFAULT_GSITECONF)
            return

        if siteconf:
            self.siteconf = siteconf
            siteconf_files = [self.siteconf]
        siteconf_parser.read(siteconf_files)

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

    def init_kickstart(self, ksconf=None):
        if not ksconf:
            self.create['ks'] = None
            self.create['repomd'] = None
            return

        self.ksconf = ksconf
        try:
            self.kickstart = utils.kickstart.read_kickstart(self.ksconf)
            self.ksrepos = utils.misc.get_repostrs_from_ks(self.kickstart)
            print "retrieving repo metadata..."
            self.repometadata = utils.misc.get_metadata_from_repos(self.ksrepos, self.create['cachedir'])
            self.create['ks'] = self.kickstart
            self.create['repomd'] = self.repometadata
            self.create['name'] = os.path.splitext(os.path.basename(ksconf))[0]
        except OSError, e:
            raise Exception("failed to create image: %s" % e)
        except Exception, e:
            raise Exception("unable to load kickstart file '%s': %s" % (self.ksconf, e))

    def setProperty(self, key, value):
        if not hasattr(self, key):
            return None

        if key == 'ksconf':
            self.init_kickstart(value)
            return True

        if key == 'siteconf':
            self.init_siteconf(value)
            return True

        return setattr(self, key, value)

    def getProperty(self, key):
        if not hasattr(self, key):
            return None

        return getattr(self, key)

    def setCategoryProperty(self, category, key, value):
        if not hasattr(self, category):
            raise Exception("Error to parse %s", category)
        categ = getattr(self, category)
        categ[key] = value

    def getCategoryProperty(self, category, key):
        if not hasattr(self, category):
            raise Exception("Error to parse %s", category)
        categ = getattr(self, category)
        return categ[key]

    def getCreateOption(self, key):
        if not self.create.has_key(key):
            raise Exception("Attribute Error: not such attribe %s" % key)
        return self.create[key]

    def getConvertOption(self, key):
        if not self.convert.has_key(key):
            raise Exception("Attribute Error: not such attribe %s" % key)
        return self.convert[key]

    def getChrootOption(self, key):
        if not self.chroot.has_key(key):
            raise Exception("Attribute Error: not such attribe %s" % key)
        return self.chroot[key]

    def dumpAllConfig(self):
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
