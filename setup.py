#!/usr/bin/env python

import os, sys
import glob
from distutils.core import setup
try:
    import setuptools
    # enable "setup.py develop", optional
except ImportError:
    pass

MOD_NAME = 'mic'

version_path = 'VERSION'
if not os.path.isfile(version_path):
    print 'No VERSION file in topdir, abort'
    sys.exit(1)

try:
    # first line should be the version number
    version = open(version_path).readline().strip()
    if not version:
        print 'VERSION file is invalid, abort'
        sys.exit(1)

    ver_file = open('%s/__version__.py' % MOD_NAME, 'w')
    ver_file.write("VERSION = \"%s\"\n" % version)
    ver_file.close()
except IOError:
    print 'WARNING: Cannot write version number file'
    pass

if sys.version_info[:2] > (2, 5):
    if len(sys.argv) > 1 and 'install' in sys.argv:
        lsbcmd = None
        if os.path.exists('/usr/bin/lsb_release'):
            lsbcmd = '/usr/bin/lsb_release'
        elif os.path.exists('/bin/lsb_release'):
            lsbcmd = '/bin/lsb_release'

        if lsbcmd:
            import subprocess
            res = subprocess.Popen([lsbcmd, '-i'],
                                   stdout=subprocess.PIPE
                                  ).communicate()[0]
            if 'Debian' in res or 'Ubuntu' in res:
                sys.argv.append('--install-layout=deb')

PACKAGES = [MOD_NAME,
            MOD_NAME + '/utils',
            MOD_NAME + '/imager',
            MOD_NAME + '/kickstart',
            MOD_NAME + '/kickstart/custom_commands',
            MOD_NAME + '/3rdparty/pykickstart',
            MOD_NAME + '/3rdparty/pykickstart/commands',
            MOD_NAME + '/3rdparty/pykickstart/handlers',
            MOD_NAME + '/3rdparty/pykickstart/urlgrabber',
           ]

setup(name=MOD_NAME,
      version = version,
      description = 'New MeeGo Image Creator',
      author='Jian-feng Ding',
      author_email='jian-feng.ding@intel.com',
      url='https://meego.gitorious.org/meego-developer-tools/image-creator',
      scripts=[
          'tools/mic',
          ],
      packages = PACKAGES,
      data_files = [("/usr/lib/mic/plugins/imager", ["plugins/imager/fs_plugin.py",
                                                     "plugins/imager/livecd_plugin.py",
                                                     "plugins/imager/liveusb_plugin.py",
                                                     "plugins/imager/loop_plugin.py",
                                                     "plugins/imager/raw_plugin.py",
                                                    ]),
                    ("/usr/lib/mic/plugins/backend", ["plugins/backend/zypppkgmgr.py",
                                                      "plugins/backend/yumpkgmgr.py",
                                                     ]),
                    ("/etc/mic", ["distfiles/mic.conf"])]
)

