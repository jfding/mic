#!/usr/bin/python

import os
import sys
import shutil
import tarfile
import StringIO
import unittest
from mic import chroot

TEST_CHROOT_LOC = os.path.join(os.getcwd(), 'chroot_fixtures')
TEST_CHROOT_TAR = os.path.join(TEST_CHROOT_LOC, 'minchroot.tar.gz')
TEST_CHROOT_DIR = os.path.join(TEST_CHROOT_LOC, 'minchroot')

def suite():
    return unittest.makeSuite(ChrootTest)

class ChrootTest(unittest.TestCase):

    def setUp(self):
        tar = tarfile.open(TEST_CHROOT_TAR, "r:gz")
        tar.extractall(path=TEST_CHROOT_LOC)
        self.chrootdir = TEST_CHROOT_DIR
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        sys.stdout = StringIO.StringIO()
        sys.stderr = StringIO.StringIO()

    def tearDown(self):
        sys.stdout = self.stdout
        sys.stderr = self.stderr
        shutil.rmtree(TEST_CHROOT_DIR, ignore_errors=True)

    def testChroot(self):
        try:
            chroot.chroot(TEST_CHROOT_DIR, None, 'exit')
        except Exception, e:
            raise self.failureException(e)

if __name__ == "__main__":
    unittest.main()

