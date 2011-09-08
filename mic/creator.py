#!/usr/bin/python -tt
#
# Copyright 2011 Intel, Inc.
#
# This copyrighted material is made available to anyone wishing to use, modify,
# copy, or redistribute it subject to the terms and conditions of the GNU
# General Public License v.2.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat
# trademarks that are incorporated in the source code or documentation are not
# subject to the GNU General Public License and may only be used or replicated
# with the express permission of Red Hat, Inc.
#

import os, sys
from optparse import SUPPRESS_HELP

from mic import configmgr, pluginmgr, msger
from mic.utils import cmdln, errors

class Creator(cmdln.Cmdln):
    """${name}: create an image

    usage:
        ${name} SUBCOMMAND [OPTS] [ARGS..]

    ${command_list}
    ${option_list}
    """

    name = 'mic create(cr)'

    def __init__(self, *args, **kwargs):
        cmdln.Cmdln.__init__(self, *args, **kwargs)

        # load configmgr
        self.configmgr = configmgr.getConfigMgr()

        # load pluginmgr
        self.pluginmgr = pluginmgr.PluginMgr()
        self.plugincmds = self.pluginmgr.get_plugins('imager')

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
        optparser.add_option('-o', '--outdir', type='string', action='store', dest='outdir', default=None, help='output directory')
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

        if self.options.outdir is not None:
            self.configmgr.create['outdir'] = self.options.outdir
        if self.options.local_pkgs_path is not None:
            self.configmgr.create['local_pkgs_path'] = self.options.local_pkgs_path

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

