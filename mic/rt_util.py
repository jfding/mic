#!/usr/bin/python -tt
#
# Copyright (c) 2009, 2010, 2011 Intel, Inc.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; version 2 of the License
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 59
# Temple Place - Suite 330, Boston, MA 02111-1307, USA.

from __future__ import with_statement
import os
import sys
import re
import shutil
import subprocess

from mic import bootstrap, msger
from mic.conf import configmgr
from mic.utils import errors, proxy
from mic.utils.fs_related import find_binary_path, makedirs
from mic.chroot import setup_chrootenv, cleanup_chrootenv

expath = lambda p: os.path.abspath(os.path.expanduser(p))

def bootstrap_mic(argv=None):


    def mychroot():
        os.chroot(rootdir)
        os.chdir(cwd)

    # by default, sys.argv is used to run mic in bootstrap
    if not argv:
        argv = sys.argv
    if argv[0] not in ('/usr/bin/mic', 'mic'):
        argv[0] = '/usr/bin/mic'

    cropts = configmgr.create
    bsopts = configmgr.bootstrap
    distro = bsopts['distro_name'].lower()
    if distro not in bsopts:
        msger.info("Use native running for distro don't support bootstrap")
        return

    rootdir = bsopts['rootdir']
    pkglist = bsopts[distro]
    cwd = os.getcwd()

    # create bootstrap and run mic in bootstrap
    bsenv = bootstrap.Bootstrap(rootdir, distro)
    try:
        msger.info("Creating %s bootstrap ..." % distro)
        bsenv.create(cropts['repomd'], pkglist)
        sync_mic(rootdir)

        msger.info("Start mic in bootstrap: %s\n" % rootdir)
        bindmounts = get_bindmounts(cropts)
        bsenv.run(argv, cwd, bindmounts)

    except errors.BootstrapError, err:
        msger.warning('\n%s' % err)
        if msger.ask("Switch to native mode and continue?"):
            return
        else:
            raise errors.BootstrapError("Failed to create bootstrap: %s" % err)
    except RuntimeError, err:
        raise errors.BootstrapError("Failed to create bootstrap: %s" % err)
    finally:
        bsenv.cleanup()

    sys.exit(0)

def get_bindmounts(cropts):
    binddirs =  [
                  os.getcwd(),
                  cropts['tmpdir'],
                  cropts['cachedir'],
                  cropts['outdir'],
                  cropts['local_pkgs_path'],
                ]
    bindfiles = [
                  cropts['logfile'],
                  configmgr._ksconf,
                ]

    bindlist = map(expath, filter(None, binddirs))
    bindlist += map(os.path.dirname, map(expath, filter(None, bindfiles)))
    bindlist = sorted(set(bindlist))
    bindmounts = ';'.join(bindlist)
    return bindmounts


def get_mic_binpath():
    try:
        fp = find_binary_path('mic')
    except:
        raise errors.BootstrapError("Can't find mic binary in host OS")
    return fp

def get_mic_modpath():
    try:
        import mic
    except ImportError:
        raise errors.BootstrapError("Can't find mic module in host OS")
    path = os.path.abspath(mic.__file__)
    return os.path.dirname(path)

def get_mic_libpath():
    # TBD: so far mic lib path is hard coded
    return "/usr/lib/mic"

# the hard code path is prepared for bootstrap
def sync_mic(bootstrap, binpth = '/usr/bin/mic',
             libpth='/usr/lib',
             pylib = '/usr/lib/python2.7/site-packages',
             conf = '/etc/mic/mic.conf'):
    _path = lambda p: os.path.join(bootstrap, p.lstrip('/'))

    micpaths = {
                 'binpth': get_mic_binpath(),
                 'libpth': get_mic_libpath(),
                 'pylib': get_mic_modpath(),
                 'conf': '/etc/mic/mic.conf',
               }

    for key, value in micpaths.items():
        try:
            safecopy(value, _path(eval(key)), False, ["*.pyc", "*.pyo"])
        except (OSError, IOError), err:
            raise errors.BootstrapError(err)

    # clean stuff:
    # yum backend, not available in bootstrap;
    # bootstrap.conf, disable bootstrap mode inside bootstrap
    clrpaths = [os.path.join(libpth, 'plugins/backend/yumpkgmgr.py'),
                os.path.join(libpth, 'plugins/backend/yumpkgmgr.pyc'),
                '/etc/mic/bootstrap.conf',
               ]

    for pth in clrpaths:
        try:
            os.unlink(_path(pth)) 
        except:
            pass

    # use default zypp backend
    conf_str = file(_path(conf)).read()
    conf_str = re.sub("pkgmgr\s*=\s*yum", "pkgmgr=zypp", conf_str)
    with open(_path(conf), 'w') as wf:
        wf.write(conf_str)

    # correct python interpreter
    mic_cont = file(_path(binpth)).read()
    mic_cont = "#!/usr/bin/python\n" + mic_cont
    with open(_path(binpth), 'w') as wf:
        wf.write(mic_cont)

def safecopy(src, dst, symlinks=False, ignore_ptns=[]):
    if os.path.isdir(src):
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)

        src = src.rstrip('/')
        # check common prefix to ignore copying itself
        if dst.startswith(src + '/'):
            ignore_ptns += os.path.basename(src)

        try:
            ignores = shutil.ignore_patterns(*ignore_ptns)
            shutil.copytree(src, dst, symlinks, ignores)
        except OSError, IOError:
            shutil.rmtree(dst, ignore_errors=True)
            raise

    else:
        try:
            if not os.path.isdir(dst):
                makedirs(os.path.dirname(dst))

            shutil.copy2(src, dst)
        except:
            raise
