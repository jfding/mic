#!/usr/bin/python -t

import os
import micng.utils as utils

DEFAULT_OUTDIR='.'
DEFAULT_TMPDIR='/tmp'
DEFAULT_CACHE='/var/tmp'
DEFAULT_GSITECONF='/etc/micng/micng.conf'
DEFAULT_USITECONF='~/.micng.conf'

class ConfigMgr(object):
    def __init__(self, siteconf=None, ksfile=None):
        self.outdir = DEFAULT_OUTDIR
        self.tmpdir = DEFAULT_TMPDIR
        self.cache = DEFAULT_CACHE
        self.siteconf = siteconf
        self.name = 'meego'
        self.ksfile = ksfile
        self.kickstart = None
        self.ksrepos = None
        self.repometadata = None
        self.init_siteconf(self.siteconf)
        self.init_kickstart(self.ksfile)

    def init_siteconf(self, siteconf = None):
        from ConfigParser import SafeConfigParser
        siteconf_parser = SafeConfigParser()
        siteconf_files = [DEFAULT_GSITECONF, DEFAULT_USITECONF]

        if siteconf:
            self.siteconf = siteconf
            siteconf_files = [self.siteconf]
        siteconf_parser.read(siteconf_files)

        for option in siteconf_parser.options('main'):
            value = siteconf_parser.get('main', option)
            setattr(self, option, value)

    def init_kickstart(self, ksfile=None):
        if not ksfile:
            return
        self.ksfile = ksfile
        try:
            self.kickstart = utils.kickstart.read_kickstart(self.ksfile)
            self.ksrepos = utils.misc.get_repostrs_from_ks(self.kickstart)
            print "retrieving repo metadata..."
            self.repometadata = utils.misc.get_metadata_from_repos(self.ksrepos, self.cache)
        except OSError, e:
            raise Exception("failed to create image: %s" % e)
        except Exception, e:
            raise Exception("unable to load kickstart file '%s': %s" % (self.ksfile, e))


    def setProperty(self, name, value):
        if not hasattr(self, name):
            return None
        #print ">>", name, value
        if name == 'ksfile':
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

configmgr = ConfigMgr()

def getConfigMgr():
    return configmgr

def setProperty(cinfo, name):
    if not isinstance(cinfo, ConfigMgr):
        return None
    if not hasattr(cinfo, name):
        return None

def getProperty(cinfo, name):
    if not isinstance(cinfo, ConfigMgr):
        return None
    if not hasattr(cinfo, name):
        return None
