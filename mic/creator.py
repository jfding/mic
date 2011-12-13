#!/usr/bin/python -tt
#
# Copyright (c) 2011 Intel, Inc.
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
from optparse import SUPPRESS_HELP

from mic import pluginmgr, msger
from mic.utils import cmdln, errors, rpmmisc
from conf import configmgr

class Creator(cmdln.Cmdln):
    """${name}: create an image

    Usage:
        ${name} SUBCOMMAND [OPTS] [ARGS..]

    ${command_list}
    ${option_list}
    """

    name = 'mic create(cr)'

    def __init__(self, *args, **kwargs):
        cmdln.Cmdln.__init__(self, *args, **kwargs)

        # get cmds from pluginmgr
        self.plugincmds = pluginmgr.PluginMgr().get_plugins('imager')

        # mix-in do_subcmd interface
        for subcmd, klass in self.plugincmds.iteritems():
            if not hasattr(klass, 'do_create'):
                msger.warning("Unsurpport subcmd: %s" % subcmd)
                continue

            func = getattr(klass, 'do_create')
            setattr(self.__class__, "do_"+subcmd, func)

    def get_optparser(self):
        optparser = cmdln.CmdlnOptionParser(self)
        optparser.add_option('-d', '--debug', action='store_true', dest='debug', help=SUPPRESS_HELP)
        optparser.add_option('-v', '--verbose', action='store_true', dest='verbose', help=SUPPRESS_HELP)
        optparser.add_option('', '--logfile', type='string', dest='logfile', default=None, help='Path of logfile')
        optparser.add_option('-c', '--config', type='string', dest='config', default=None, help='Specify config file for mic')
        optparser.add_option('-k', '--cachedir', type='string', action='store', dest='cachedir', default=None, help='Cache directory to store the downloaded')
        optparser.add_option('-o', '--outdir', type='string', action='store', dest='outdir', default=None, help='Output directory')
        optparser.add_option('-A', '--arch', type='string', dest='arch', default=None, help='Specify repo architecture')
        optparser.add_option('', '--release', type='string', dest='release', default=None, metavar='RID', help='Generate a release of RID with all necessary files, when @BUILD_ID@ is contained in kickstart file, it will be replaced by RID')
        optparser.add_option("", "--record-pkgs", type="string", dest="record_pkgs", default=None,
                             help='Record the info of installed packages, multiple values can be specified which joined by ",", valid values: "name", "content", "license"')
        optparser.add_option('', '--pkgmgr', type='string', dest='pkgmgr', default=None, help='Specify backend package manager')
        optparser.add_option('', '--local-pkgs-path', type='string', dest='local_pkgs_path', default=None, help='Path for local pkgs(rpms) to be installed')
        return optparser

    def preoptparse(self, argv):
        optparser = self.get_optparser()

        largs = []
        rargs = []
        while argv:
            arg = argv.pop(0)

            if arg in ('-h', '--help'):
                rargs.append(arg)

            elif optparser.has_option(arg):
                largs.append(arg)

                if optparser.get_option(arg).takes_value():
                    try:
                        largs.append(argv.pop(0))
                    except IndexError:
                        raise errors.Usage("%s option requires an argument" % arg)

            else:
                if arg.startswith("--"):
                    if "=" in arg:
                        opt = arg.split("=")[0]
                    else:
                        opt = None
                elif arg.startswith("-") and len(arg) > 2:
                    opt = arg[0:2]
                else:
                    opt = None

                if opt and optparser.has_option(opt):
                    largs.append(arg)
                else:
                    rargs.append(arg)

        return largs + rargs

    def postoptparse(self):
        if self.options.verbose:
            msger.set_loglevel('verbose')
        if self.options.debug:
            msger.set_loglevel('debug')

        if self.options.logfile:
            msger.set_interactive(False)
            msger.set_logfile(self.options.logfile)
            configmgr.create['logfile'] = self.options.logfile

        if self.options.config:
            configmgr.reset()
            configmgr._siteconf = self.options.config

        if self.options.outdir is not None:
            configmgr.create['outdir'] = self.options.outdir
        if self.options.cachedir is not None:
            configmgr.create['cachedir'] = self.options.cachedir
        if self.options.local_pkgs_path is not None:
            configmgr.create['local_pkgs_path'] = self.options.local_pkgs_path

        if self.options.release:
            configmgr.create['release'] = self.options.release

        if self.options.record_pkgs:
            configmgr.create['record_pkgs'] = []
            for infotype in self.options.record_pkgs.split(','):
                if infotype not in ('name', 'content', 'license'):
                    raise errors.Usage('Invalid pkg recording: %s, valid ones: "name", "content", "license"' % infotype)

                configmgr.create['record_pkgs'].append(infotype)

        if self.options.arch is not None:
            supported_arch = sorted(rpmmisc.archPolicies.keys(), reverse=True)
            if self.options.arch in supported_arch:
                configmgr.create['arch'] = self.options.arch
            else:
                raise errors.Usage('Invalid architecture: "%s".\n' \
                                   '  Supported architectures are: \n' \
                                   '  %s\n' % (self.options.arch, ', '.join(supported_arch)))

        if self.options.pkgmgr is not None:
            configmgr.create['pkgmgr'] = self.options.pkgmgr

    def main(self, argv=None):
        if argv is None:
            argv = sys.argv
        else:
            argv = argv[:] # don't modify caller's list

        self.optparser = self.get_optparser()
        if self.optparser:
            try:
                argv = self.preoptparse(argv)
                self.options, args = self.optparser.parse_args(argv)

            except cmdln.CmdlnUserError, ex:
                msg = "%s: %s\nTry '%s help' for info.\n"\
                      % (self.name, ex, self.name)
                msger.error(msg)

            except cmdln.StopOptionProcessing, ex:
                return 0
        else:
            # optparser=None means no process for opts
            self.options, args = None, argv[1:]

        self.postoptparse()

        if not args:
            return self.emptyline()

        if os.geteuid() != 0:
            msger.error('Root permission is required to continue, abort')

        return self.cmd(args)

