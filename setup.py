#!/usr/bin/env python

import os, sys
from distutils.core import setup
#try:
#    import setuptools
#    # enable "setup.py develop", optional
#except ImportError:
#    pass

MOD_NAME = 'micng'

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

PACKAGES = [MOD_NAME,
            MOD_NAME + '/utils',
            MOD_NAME + '/utils/kscommands',
            MOD_NAME + '/utils/pkgmanagers',
            MOD_NAME + '/imager',
            MOD_NAME + '/pluginbase',
           ]
setup(name=MOD_NAME,
      version = version,
      description = 'New MeeGo Image Creator',
      author='Jian-feng Ding',
      author_email='jian-feng.ding@intel.com',
      url='https://meego.gitorious.org/meego-developer-tools/image-creator',
      scripts=[
          'tools/micng',
          'tools/mic-image-create',
          ],
      packages = PACKAGES,
)

