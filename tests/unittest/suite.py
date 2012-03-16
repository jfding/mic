import os
import sys
import unittest
import test_configmgr
import test_pluginmgr
import test_baseimager
import test_msger
import test_runner
import test_chroot

if os.getuid() != 0:
    raise SystemExit("Root permission is needed")

suite = unittest.TestSuite()
suite.addTests(test_pluginmgr.suite())
suite.addTests(test_configmgr.suite())
suite.addTests(test_baseimager.suite())
suite.addTests(test_msger.suite())
suite.addTests(test_runner.suite())
suite.addTests(test_chroot.suite())
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
