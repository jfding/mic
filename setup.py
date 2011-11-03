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

# --install-layout is recognized after 2.5
if sys.version_info[:2] > (2, 5):
    if len(sys.argv) > 1 and 'install' in sys.argv:
        dist=None
        import platform
        try:
            (dist, ver, id) = platform.linux_distribution()
        except:
            pass

        # for debian-like distros, set deb-layout py-lib 
        if dist in ('debian', 'Ubuntu'):
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

IMAGER_PLUGINS = glob.glob(os.path.join("plugins", "imager", "*.py"))
BACKEND_PLUGINS = glob.glob(os.path.join("plugins", "backend", "*.py"))

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
      data_files = [("/usr/lib/mic/plugins/imager", IMAGER_PLUGINS),
                    ("/usr/lib/mic/plugins/backend", BACKEND_PLUGINS),
                    ("/etc/mic", ["distfiles/mic.conf"])]
)

