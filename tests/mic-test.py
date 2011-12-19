#!/usr/bin/python
import unittest
import os, sys, glob, tempfile, shutil
from testbase import *

class MICTest(unittest.TestCase):
    cases_dir = "mic_cases"
    if os.path.isdir(cases_dir):
        for case in glob.glob(os.path.join(cases_dir,'test-*')):
            case = os.path.basename(case)[5:]
            method = """
def test_%s(self):
    self._testTemplate("%s")
""" % (case, case)
            exec method in locals()
   
    def setUp(self):
        self.work_env = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.work_env, ignore_errors = True)
            
    def _testTemplate(self, case):
        """test function"""
        PrepEnv(self.cases_dir, case, self.work_env)
        RunandCheck(self, self.work_env)
                               
def MICtestsuite():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    alltests = unittest.TestSuite(suite)
    return alltests       

if __name__ == '__main__':
    if os.getuid() != 0:
        raise SystemExit("Root permission is needed")

    suite = MICtestsuite()
    unittest.TextTestRunner(verbosity=2).run(suite)
