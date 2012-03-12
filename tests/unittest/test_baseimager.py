#!/usr/bin/python

import os
import sys
import rpm
import glob
import shutil
import StringIO
import subprocess
import unittest
from mic import plugin as pluginmgr
from mic import conf as configmgr
from mic import msger
from mic.imager import fs

TEST_BASEIMGR_LOC = os.path.join(os.getcwd(), 'baseimgr_fixtures')
KSCONF = os.path.join(os.getcwd(), 'baseimgr_fixtures', 'test.ks')
KSBAK = os.path.join(os.getcwd(), 'baseimgr_fixtures', 'test.ks.bak')
REPOURI = os.path.join(os.getcwd(), 'baseimgr_fixtures')
CACHEDIR = os.path.join(os.getcwd(), 'baseimgr_fixtures', 'cache')
RPMLOCK_PATH = None

def suite():
    return unittest.makeSuite(BaseImgrTest)

class BaseImgrTest(unittest.TestCase):

    arch = 'i686'
    rootdir = "%s/rootdir" % os.getcwd() 
    expect_pkglist = ['A', 'ABC', 'C', 'D', 'E', 'F', 'G', 'H']

    def setUp(self):
        self.stdout = sys.stdout
        self.stream = sys.stdout
        msger.STREAM = StringIO.StringIO()
        shutil.copy2(KSCONF, KSBAK)
        with open(KSCONF, 'r') as f:
            content = f.read()
        content = content.replace('$$$$$$', "file://" + REPOURI)
        with open(KSCONF, 'w') as f:
            f.write(content)
        msger.set_loglevel('quiet')

    def tearDown(self):
        sys.stdout = self.stdout
        msger.STREAM = self.stream
        shutil.copy2(KSBAK, KSCONF)
        shutil.rmtree (self.rootdir, ignore_errors = True)
        shutil.rmtree (CACHEDIR, ignore_errors = True)
        os.unlink(KSBAK)

    def getMountList(self, pattern):
        real_mount_list = []
        dev_null = os.open("/dev/null", os.O_WRONLY)
        p = subprocess.Popen('mount', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        for entry in p.communicate()[0].split('\n'):
            if entry.find(pattern) > 0:
                real_mount_list.append(entry.split(' ')[0])
        real_mount_list.sort()
        os.close(dev_null)
        return real_mount_list

    def getInsPkgList(self, rootdir):
        installed_pkgs = []
        ts = rpm.TransactionSet (rootdir)
        hrs = ts.dbMatch()
        for pkg in hrs:
            installed_pkgs.append(pkg['name'])
        installed_pkgs.sort()
        ts.closeDB()

        return installed_pkgs

    def BaseImager(self, backend):
        global RPMLOCK_PATH

        cfgmgr = configmgr.configmgr
        creatoropts = cfgmgr.create

        creatoropts["cachedir"] = CACHEDIR
        creatoropts["outdir"] = self.rootdir
        creatoropts["arch"] = self.arch
        creatoropts['pkgmgr'] = backend
        cfgmgr._ksconf =  KSCONF
        pkgmgr = None
        for (key, pcls) in pluginmgr.PluginMgr().get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        creator = fs.FsImageCreator(creatoropts, pkgmgr)
        creator._recording_pkgs.append('name')

        creator.check_depend_tools()
        
        # Test mount interface
        creator.mount(None, creatoropts["cachedir"])
        if RPMLOCK_PATH:
            os.makedirs(RPMLOCK_PATH)
        else:
            RPMLOCK_PATH = "%s/var/lib/rpm" % creator._instroot
        exp_mount_list = ['/sys', '/proc', '/proc/sys/fs/binfmt_misc', '/dev/pts']
        exp_mount_list.sort()
        real_mount_list = self.getMountList(creator._instroot)
        self.assertEqual(real_mount_list, exp_mount_list)
        
        # Test Install interface
        creator.install()
        installed_pkgs = self.getInsPkgList(creator._instroot)
        self.assertEqual(installed_pkgs, self.expect_pkglist)

        # Test umount interface
        creator.unmount()
        real_mount_list = self.getMountList(creator._instroot)
        self.assertEqual(real_mount_list, [])
        # Test Packaging interface
        creator.package(creatoropts["outdir"])
        installed_pkgs = self.getInsPkgList("%s/%s" % (self.rootdir, creator.name))
        self.assertEqual(installed_pkgs, self.expect_pkglist)
        
        creator.cleanup()
        # Test recore_pkgs option
        pkglist = ['A.i586 0.1-1', 'ABC.i586 0.1-1', 'C.i686 0.2-1',
                   'D.i586 0.1-1', 'E.i586 0.1-1', 'F.noarch 0.1-1',
                   'G.i586 0.1-1', 'H.noarch 0.1-1']
        f = open ("%s/%s.packages" % (self.rootdir, creator.name))
        real_pkglist = f.read()
        self.assertEqual(real_pkglist, '\n'.join(pkglist))

    def testBaseImagerZypp(self):
        self.BaseImager('zypp')

    def testBaseImagerYum(self):
        self.BaseImager('yum')

if __name__ == "__main__":
    if os.getuid() != 0:
        raise SystemExit("Root permission is needed")
    unittest.main()
