#!/usr/bin/python

import os
import sys
import shutil
import StringIO

from mic import conf, msger
from pykickstart.parser import KickstartParser
import unittest2 as unittest

SITECONF = os.path.join(os.getcwd(), 'configmgr_fixtures', 'mic.conf')
KSCONF = os.path.join(os.getcwd(), 'configmgr_fixtures', 'test.ks')
KSBAK = os.path.join(os.getcwd(), 'configmgr_fixtures', 'test.ks.bak')
REPOURI = os.path.join(os.getcwd(), 'configmgr_fixtures', 'packages')
CACHEDIR = os.path.join(os.getcwd(), 'configmgr_fixtures', 'cache')

def suite():
    return unittest.makeSuite(ConfigMgrTest)

class ConfigMgrTest(unittest.TestCase):

    def setUp(self):
        self.configmgr = conf.ConfigMgr(siteconf=SITECONF)
        shutil.copy2(KSCONF, KSBAK)
        with open(KSCONF, 'r') as f:
            content = f.read()
        content = content.replace('$$$$$$', "file://" + REPOURI)
        with open(KSCONF, 'w') as f:
            f.write(content)
        if not os.path.exists(CACHEDIR):
            os.makedirs(CACHEDIR)
        self.configmgr.create['cachedir'] = CACHEDIR
        self.level = msger.get_loglevel()
        msger.set_loglevel('quiet')

    def tearDown(self):
        msger.set_loglevel(self.level)
        shutil.copy2(KSBAK, KSCONF)
        os.unlink(KSBAK)
        shutil.rmtree(CACHEDIR, ignore_errors = True)

#    def testCommonSection(self):
#        self.assertEqual(self.configmgr.common['test'], 'test')

    def testCreateSection(self):
        #self.assertEqual(self.configmgr.create['local_pkgs_path'], '/opt/cache')
        self.assertEqual(self.configmgr.create['pkgmgr'], 'yum')

#    def testChrootSection(self):
#        self.assertEqual(self.configmgr.chroot['test2'], 'test2')

#    def testConvertSection(self):
#        self.assertEqual(self.configmgr.convert['test3'], 'test3')

    def testKickstartConfig(self):
        cachedir = self.configmgr.create['cachedir']
        repomd = [{'baseurl': 'file://%s' % REPOURI ,
             'cachedir': '%s' % cachedir,
             'comps': None,
             'name': 'test',
             'patterns': None,
             'primary': '%s/test/primary.sqlite' % cachedir,
             'proxies': None,
             'repokey': None,
             'repomd': '%s/test/repomd.xml' % cachedir}]
        self.configmgr._ksconf = KSCONF
        self.assertTrue(isinstance(self.configmgr.create['ks'], KickstartParser))
        self.assertEqual(self.configmgr.create['name'], 'test')
        self.assertDictEqual(repomd[0], self.configmgr.create['repomd'][0])
        self.assertEqual(self.configmgr.create['arch'], 'i686')

if __name__ == "__main__":
    unittest.main()
