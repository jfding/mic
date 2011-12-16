#!/usr/bin/python
import os 
import sys
import subprocess, re, shutil, glob
import gettext

_ = gettext.lgettext
COLOR_BLACK = "\033[00m"
COLOR_RED = "\033[1;31m"

PRESCRIPTS = """
patch -s < ks.p
patch -s < conf.p
sudo mv /etc/mic/mic.conf /etc/mic/orig.conf
sudo mv test.conf /etc/mic/mic.conf 
"""
POSTSCRIPTS = """
sudo mv -f /etc/mic/orig.conf /etc/mic/mic.conf
"""

def PrepEnv(cases_dir, case, work_env):
    """prepare working env"""
    for one in glob.glob(os.path.join(cases_dir, 'base', '*')):
        shutil.copy(one, work_env)
    for other in glob.glob(os.path.join(cases_dir, 'test-'+case, '*')):
        shutil.copy(other, work_env)
 
def ImgCheck(work_env):
    """check image generate"""
    genImage = False
    for root, dirs, files in os.walk(work_env):
        for name in files:
            #add raw check support and  XXX.tar file check support
            m = re.match(r'.*\.(img|raw|iso|usbimg|tar)', name) or re.match(r'system-release',name)
            if m:
                genImage = True
                break
    return genImage

def RunandCheck(object, work_env):
    """run mic-image-creator command and check something"""
    ret = False  
  
    cwd = os.getcwd()
    os.chdir(work_env)
    os.system(PRESCRIPTS)
    
    #set value of "expect"
    expect = None
    if "expect" in os.listdir(work_env):
        exp_f = open('expect', 'r')
        exp = exp_f.read()
        if len(exp) > 0:
            expect = exp.strip()
    #set cmdline    
    opt_f = open('options','r')
    args = opt_f.read().strip()+' test.ks'
    
    print args
    proc = subprocess.Popen(args,stdout = sys.stdout ,stderr=subprocess.PIPE,shell=True)
    errorinfo = proc.communicate()[1]
    #check    
    if expect:
        if errorinfo.find(expect) != -1:#FIXME
            ret =True
    else:
        proc.wait()
        ret = ImgCheck(work_env)
    os.system(POSTSCRIPTS)    
    os.chdir(cwd)
    
    try:
        object.assertTrue(ret)
    except object.failureException:
        raise object.failureException(_("%s%s%s") %(COLOR_RED,errorinfo,COLOR_BLACK))    
