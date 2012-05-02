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

# --install-layout is recognized after 2.5
if sys.version_info[:2] > (2, 5):
    if len(sys.argv) > 1 and 'install' in sys.argv:
        try:
            import platform
            (dist, ver, id) = platform.linux_distribution()

            # for debian-like distros, mods will be installed to
            # ${PYTHONLIB}/dist-packages
            if dist in ('debian', 'Ubuntu'):
                sys.argv.append('--install-layout=deb')
        except:
            pass

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

# the following code to do a simple parse for '--prefix' opts
prefix = sys.prefix
is_next = False
for arg in sys.argv:
    if is_next:
        prefix = arg
        break
    if '--prefix=' in arg:
        prefix = arg[9:]
        break
    elif '--prefix' == arg:
        is_next = True

# get the installation path of mic.conf
prefix = os.path.abspath(os.path.expanduser(prefix)).rstrip('/')
if prefix.lstrip('/') == 'usr':
    etc_prefix = '/etc'
else:
    etc_prefix = os.path.join(prefix, 'etc')

conffile = 'distfiles/mic.conf'
if os.path.isfile('%s/mic/mic.conf' % etc_prefix):
    conffile += '.new'

# apply prefix to mic.conf.in to generate actual mic.conf
conf_str = file('distfiles/mic.conf.in').read()
conf_str = conf_str.replace('@PREFIX@', prefix)
with file(conffile, 'w') as wf:
    wf.write(conf_str)

try:
    os.environ['PREFIX'] = prefix
    setup(name=MOD_NAME,
          version = version,
          description = 'Image Creator for Linux Distributions',
          author='Jian-feng Ding, Qiang Zhang, Gui Chen',
          author_email='jian-feng.ding@intel.com, qiang.z.zhang@intel.com, gui.chen@intel.com',
          url='https://github.com/jfding/mic',
          scripts=[
              'tools/mic',
              ],
          packages = PACKAGES,
          data_files = [("%s/lib/mic/plugins/imager" % prefix, IMAGER_PLUGINS),
                        ("%s/lib/mic/plugins/backend" % prefix, BACKEND_PLUGINS),
                        ("%s/mic" % etc_prefix, [conffile])]
    )
finally:
    # remove dynamic file distfiles/mic.conf
    os.unlink(conffile)

