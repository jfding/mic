#!/usr/bin/python -tt
#
# Copyright 2008, 2009, 2010 Intel, Inc.
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
import logging

import mic.utils.cmdln as cmdln
import mic.configmgr as configmgr
import mic.pluginmgr as pluginmgr

class Creator(cmdln.Cmdln):
    """
    ${command_list}
    ${help_list}
    ${option_list}
    """

    name = 'mic create(cr)'

    def __init__(self, *args, **kwargs):
        cmdln.Cmdln.__init__(self, *args, **kwargs)

        # load configmgr
        self.configmgr = configmgr.getConfigMgr()

        # load pluginmgr
        self.pluginmgr = pluginmgr.PluginMgr()
        self.pluginmgr.loadPlugins()
        self.plugincmds = self.pluginmgr.getImagerPlugins()

        # mix-in do_subcmd interface
        for subcmd, klass in self.plugincmds:
            if not hasattr(klass, 'do_create'):
                logging.warn("Unsurpport subcmd: %s" % subcmd)
                continue
            func = getattr(klass, 'do_create')
            setattr(self.__class__, "do_"+subcmd, func)

    def get_optparser(self):
        optparser = cmdln.CmdlnOptionParser(self)
        optparser.add_option('-d', '--debug', action='store_true', help='print debug info')
        optparser.add_option('-v', '--verbose', action='store_true', help='verbose output')
        #optparser.add_option('-o', '--outdir', type='string', action='store', dest='outdir', default=None, help='output directory')
        return optparser 

    def preoptparse(self, argv):
        pass

    def postoptparse(self):
        if self.options.verbose is True:
            logging.getLogger().setLevel(logging.INFO)
        if self.options.debug is True:
            logging.getLogger().setLevel(logging.DEBUG)

        #if self.options.outdir is not None:
        #    self.configmgr.create['outdir'] = self.options.outdir

    def main(self, argv=None):
        if argv is None:
            argv = sys.argv
        else:
            argv = argv[:] # don't modify caller's list

        self.optparser = self.get_optparser()
        if self.optparser:
            try:
                self.preoptparse(argv)
                self.options, args = self.optparser.parse_args(argv)
            except cmdln.CmdlnUserError, ex:
                msg = "%s: %s\nTry '%s help' for info.\n"\
                      % (self.name, ex, self.name)
                self.stderr.write(self._str(msg))
                self.stderr.flush()
                return 1
            except cmdln.StopOptionProcessing, ex:
                return 0
        else:
            # optparser=None means no process for opts
            self.options, args = None, argv[1:]

        self.postoptparse()

        if args:
            if os.geteuid() != 0:
                print >> sys.stderr, "You must run %s as root" % sys.argv[0]
                return 1

            return self.cmd(args)

        else:
            return self.emptyline()
