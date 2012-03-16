#!/usr/bin/python

import os
import sys
import StringIO
import unittest
from mic import msger

def suite():
    return unittest.makeSuite(MsgerTest)

class MsgerTest(unittest.TestCase):

    def setUp(self):
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        sys.stdout = StringIO.StringIO()
        sys.stderr = StringIO.StringIO()
        msger.set_loglevel('normal')
        self.loglevel = msger.LOG_LEVEL

    def tearDown(self):
        msger.LOG_LEVEL = self.loglevel
        sys.stdout = self.stdout
        sys.stderr = self.stderr

    def testRaw(self):
        excepted = "hello\n"
        msger.raw("hello")
        self.assertEqual(excepted, sys.stdout.getvalue())

    def testInfo(self):
        excepted = "Info: hello\n"
        msger.info("hello")
        self.assertEqual(excepted, sys.stdout.getvalue())

    def testWarning(self):
        excepted = "Warning: hello\n"
        msger.warning("hello")
        self.assertEqual(excepted, sys.stderr.getvalue())

    def testVerbose(self):
        excepted = "Verbose: hello\n"
        msger.verbose("hello")
        self.assertEqual("", sys.stdout.getvalue())
        msger.set_loglevel("verbose")
        msger.verbose("hello")
        self.assertEqual(excepted, sys.stdout.getvalue())

    def testDebug(self):
        excepted = "Debug: hello\n"
        msger.debug("hello")
        self.assertEqual("", sys.stdout.getvalue())
        msger.set_loglevel("debug")
        msger.debug("hello")
        self.assertEqual(excepted, sys.stderr.getvalue())

    def testLogstderr(self):
        excepted = "hello\n"
        cwd = os.getcwd()
        msger.enable_logstderr(cwd + "/__tmp_err.log")
        print >>sys.stderr, "hello"
        msger.disable_logstderr()
        self.assertEqual(excepted, sys.stderr.getvalue())

    def testLoglevel(self):
        # test default value
        self.assertEqual("normal", msger.get_loglevel())
        # test no effect value
        msger.set_loglevel("zzzzzz")
        self.assertEqual("normal", msger.get_loglevel())
        # test effect value
        msger.set_loglevel("verbose")
        self.assertEqual("verbose", msger.get_loglevel())
        msger.set_loglevel("debug")
        self.assertEqual("debug", msger.get_loglevel())
        msger.set_loglevel("quiet")
        self.assertEqual("quiet", msger.get_loglevel())

if __name__ == "__main__":
    unittest.main()

