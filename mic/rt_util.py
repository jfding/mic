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

import os, sys
import string
import shutil
import re

from mic import bootstrap
from mic import msger
from mic.conf import configmgr
from mic.utils import errors
import mic.utils.misc as misc
from mic.utils.proxy import get_proxy_for

BOOTSTRAP_URL="http://download.tizen.org/tools/micbootstrap"

def runmic_in_runtime(runmode, opts, ksfile, argv=None):
    dist = misc.get_distro()[0]
    if not runmode or not dist or "MeeGo" == dist:
        return

    if not argv:
        argv = sys.argv
    else:
        argv = argv[:]

    if runmode == 'bootstrap':
        msger.info("Use bootstrap runtime environment")
        name = "micbootstrap"
        try:
            repostrs = configmgr.bootstraps[name]
        except:
            repostrs = "name:%s,baseurl:%s," (name, BOOTSTRAP_URL)
            proxy = get_proxy_for(BOOTSTRAP_URL)
            if proxy:
                repostrs += "proxy:%s" % proxy

        repolist = []
        if not name:
            # use ks repo to create bootstrap
            # so far it can't be effective for mic not in repo
            #name = os.path.basename(ksfile)
            #repostrs = misc.get_repostrs_from_ks(opts['ks'])
            #for item in repostrs:
            #    repolist.append(convert_repostr(item))
            msger.info("cannot find valid bootstrap, please check the config")
            msger.info("Back to native running")
            return
        else:
            for reponame, repostr in repostrs.items():
                repolist.append(convert_repostr(repostr))
        runmic_in_bootstrap(name, argv, opts, ksfile, repolist)
    else:
        raise errors.RuntimeError('Invalid runmode: %s ' % runmode)

    sys.exit(0)

def compare_rpmversion(ver1, ver2):
    return ver1.split('.')[0] == ver2.split('.')[0] and \
        ver1.split('.')[1] == ver2.split('.')[1]

def convert_repostr(repostr):
    repo = {}
    for item in repostr.split(','):
        loc = item.find(':')
        opt = item[0:loc]
        if opt in ('name', 'baseurl', 'mirrolist', 'proxy', \
            'proxy_username', 'proxy_password', 'debuginfo', \
            'source', 'gpgkey', 'disable'):
            if len(item) > loc:
                repo[opt] = item[loc+1:]
            else:
                repo[opt] = None
    return repo

def select_bootstrap(repomd, cachedir, bootstrapdir):
    cfgmgr = configmgr
    lvl = msger.get_loglevel()
    msger.set_loglevel('quiet')
    repo_rpmver = misc.get_rpmver_in_repo(repomd)
    if not repo_rpmver:
        msger.set_loglevel(lvl)
        return (None, None)

    # Check avaliable bootstrap
    bootstrap_env = bootstrap.Bootstrap(homedir = bootstrapdir)
    for bs in bootstrap_env.list():
        if compare_rpmversion(repo_rpmver, bs['rpm']):
            return (bs['name'], {})

    for bsname, bsrepo in cfgmgr.bootstraps.items():
        repolist = []
        for repo in bsrepo.keys():
            repolist.append(bsrepo[repo])

        rpmver = None
        try:
            repomd = misc.get_metadata_from_repos(repolist, cachedir)
            rpmver = misc.get_rpmver_in_repo(repomd)
        except errors.CreatorError, e:
            msger.set_loglevel(lvl)
            raise

        if not rpmver:
            continue
        if compare_rpmversion(repo_rpmver, rpmver):
            msger.set_loglevel(lvl)
            return (bsname, bsrepo)
    msger.set_loglevel(lvl)
    return (None, None)

def runmic_in_bootstrap(name, argv, opts, ksfile, repolist):
    bootstrap_env = bootstrap.Bootstrap(homedir = opts['bootstrapdir'])
    bootstrap_lst = bootstrap_env.bootstraps
    setattr(bootstrap_env, 'rootdir', name)
    if not bootstrap_lst or not name in bootstrap_lst:
        msger.info("Creating bootstrap %s under %s" % \
                   (name, bootstrap_env.homedir))
        bootstrap_env.create(name, repolist)

    msger.info("Use bootstrap: %s" % bootstrap_env.rootdir)
    # copy mic
    msger.info("Sync native mic to bootstrap")
    copy_mic(bootstrap_env.rootdir)

    # bind mounts , opts['cachedir'], opts['tmpdir']
    cwd = os.getcwd()
    lst = [cwd, opts['outdir']]
    if ksfile:
        ksfp = os.path.abspath(os.path.expanduser(ksfile))
        lst.append(os.path.dirname(ksfp))
    if opts['logfile']:
        logfile = os.path.abspath(os.path.expanduser(opts['logfile']))
        lst.append(os.path.dirname(logfile))
    if opts['local_pkgs_path']:
        lppdir = os.path.abspath(os.path.expanduser(opts['local_pkgs_path']))
        lst.append(lppdir)

    # TBD local repo

    # make unique and remain the original order
    lst = sorted(set(lst), key=lst.index)

    bindmounts = ';'.join(map(lambda p: os.path.abspath(os.path.expanduser(p)),
                              lst))

    msger.info("Start mic command in bootstrap")
    bootstrap_env.run(name, argv, cwd, bindmounts)

def get_mic_modpath():
    try:
        import mic
    except ImportError:
        raise errors.BootstrapError('Can\'t find mic module in host OS.')
    else:
        path = os.path.abspath(mic.__file__)
        return os.path.dirname(path)

def get_mic_binpath():
    # FIXME: please use mic.find_binary_path()
    path = os.environ['PATH']
    paths = string.split(path, os.pathsep)
    for pth in paths:
        fn = os.path.join(pth, 'mic')
        if os.path.isfile(fn):
            return fn

    msger.warning("Can't find mic command")
    # FIXME: how to handle unfound case?

def get_mic_libpath():
    # so far mic lib path is hard coded
    # TBD
    return "/usr/lib/mic"

# the hard code path is prepared for bootstrap
def copy_mic(bootstrap_pth, bin_pth = '/usr/bin', lib_pth='/usr/lib', \
             pylib_pth = '/usr/lib/python2.7/site-packages'):
    # copy python lib files
    mic_pylib = get_mic_modpath()
    bs_mic_pylib = bootstrap_pth + os.path.join(pylib_pth, 'mic')
    if os.path.commonprefix([mic_pylib, bs_mic_pylib]) == mic_pylib:
        raise errors.BootstrapError('Invalid Bootstrap: %s' % bootstrap_pth)
    shutil.rmtree(bs_mic_pylib, ignore_errors = True)
    shutil.copytree(mic_pylib, bs_mic_pylib)
    clean_files(".*\.py[co]$", bs_mic_pylib)

    # copy lib files
    mic_libpth = get_mic_libpath()
    bs_mic_libpth = bootstrap_pth + os.path.join(lib_pth, 'mic')
    if os.path.commonprefix([mic_libpth, bs_mic_libpth]) == mic_libpth:
        raise errors.BootstrapError('Invalid Bootstrap: %s' % bootstrap_pth)
    shutil.rmtree(bs_mic_libpth, ignore_errors = True)
    shutil.copytree(mic_libpth, bs_mic_libpth)
    os.system('cp -af %s %s' % (mic_libpth, os.path.dirname(bs_mic_libpth)))

    # copy bin files
    mic_binpth = get_mic_binpath()
    bs_mic_binpth = bootstrap_pth + os.path.join(bin_pth, 'mic')
    shutil.rmtree(bs_mic_binpth, ignore_errors = True)
    shutil.copy2(mic_binpth, bs_mic_binpth)

    # copy mic.conf
    mic_cfgpth = '/etc/mic/mic.conf'
    bs_mic_cfgpth = bootstrap_pth + mic_cfgpth
    if not os.path.exists(os.path.dirname(bs_mic_cfgpth)):
        os.makedirs(os.path.dirname(bs_mic_cfgpth))
    shutil.copy2(mic_cfgpth, bs_mic_cfgpth)

    # remove yum backend
    try:
        yumpth = "/usr/lib/mic/plugins/backend/yumpkgmgr.py"
        os.unlink(bootstrap_pth + yumpth)
    except:
        pass

def clean_files(pattern, dir):
    if not os.path.exists(dir):
        return
    for f in os.listdir(dir):
        entry = os.path.join(dir, f)
        if os.path.isdir(entry):
            clean_files(pattern, entry)
        elif re.match(pattern, entry):
            os.unlink(entry)
