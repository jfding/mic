#!/usr/bin/python

import os
import sys
import StringIO
import unittest
from mic.utils import runner

def suite():
    return unittest.makeSuite(RunnerTest)

class RunnerTest(unittest.TestCase):

    def setUp(self):
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        sys.stdout = StringIO.StringIO()
        sys.stderr = StringIO.StringIO()

    def tearDown(self):
        sys.stdout = self.stdout
        sys.stderr = self.stderr

    def testRuntoolCatch0(self):
        (rc, out) = runner.runtool("echo hello", catch=0)
        self.assertEqual(0, rc)
        self.assertEqual('', out)
        (rc, out) = runner.runtool("echo hello >&2", catch=0)
        self.assertEqual(0, rc)
        self.assertEqual('', out)

    def testRuntoolCatch1(self):
        (rc, out) = runner.runtool("echo hello", catch=1)
        self.assertEqual(0, rc)
        self.assertEqual("hello\n", out)

    def testRuntoolCatch2(self):
        (rc, out) = runner.runtool("echo hello >&2", catch=2)
        self.assertEqual(0, rc)
        self.assertEqual("hello\n", out)

    def testRuntoolCatch3(self):
        (rc, out) = runner.runtool("echo hello", catch=3)
        self.assertEqual(0, rc)
        self.assertEqual("hello\n", out)
        (rc, out) = runner.runtool("echo hello >&2", catch=2)
        self.assertEqual(0, rc)
        self.assertEqual("hello\n", out)

if __name__ == "__main__":
    unittest.main()

