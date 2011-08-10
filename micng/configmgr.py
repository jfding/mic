#!/usr/bin/python -t

import os
import sys
import logging
import micng.utils as utils

DEFAULT_OUTDIR='.'
DEFAULT_TMPDIR='/var/tmp'
DEFAULT_CACHEDIR='/var/cache'
DEFAULT_GSITECONF='/etc/micng/micng.conf'
#DEFAULT_USITECONF='~/.micng.conf'

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
            logging.debug("Not exists file: %s" % DEFAULT_GSITECONF)
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
        except OSError, e:
            raise Exception("failed to create image: %s" % e)
        except Exception, e:
            raise Exception("unable to load kickstart file '%s': %s" % (self.ksconf, e))


    def setProperty(self, name, value):
        if not hasattr(self, name):
            return None
        #print ">>", name, value
        if name == 'ksconf':
            self.init_kickstart(value)
            return True
        if name == 'siteconf':
            self.init_siteconf(value)
            return True
        return setattr(self, name, value)

    def getProperty(self, name):
        if not hasattr(self, name):
            return None
        return getattr(self, name)

    def setCategoryProperty(self, category, name, value):
        if not hasattr(self, category):
            raise Exception("Error to parse %s", category)
        categ = getattr(self, category)
        categ[name] = value

    def getCategoryProperty(self, category, name):
        if not hasattr(self, category):
            raise Exception("Error to parse %s", category)
        categ = getattr(self, category)
        return categ[name]

    def getCreateOption(self, name):
        if not self.create.has_key(name):
            raise Exception("Attribute Error: not such attribe %s" % name)
        return self.create[name]

    def getConvertOption(self, name):
        if not self.convert.has_key(name):
            raise Exception("Attribute Error: not such attribe %s" % name)
        return self.convert[name]

    def getChrootOption(self, name):
        if not self.chroot.has_key(name):
            raise Exception("Attribute Error: not such attribe %s" % name)
        return self.chroot[name]

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
#configmgr.dumpAllConfig()

