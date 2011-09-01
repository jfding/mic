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
from mic import msger
from mic import pluginbase

DEFAULT_PLUGIN_LOCATION = "/usr/lib/mic/plugins"

PLUGIN_TYPES = ["imager", "backend"] # TODO  "hook"

class PluginMgr(object):
    plugin_dirs = {}

    # make the manager class as singleton
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(PluginMgr, cls).__new__(cls, *args, **kwargs)

        return cls._instance

    def __init__(self, plugin_dirs=[]):

        # default plugin directory
        for pt in PLUGIN_TYPES:
            self._add_plugindir(os.path.join(DEFAULT_PLUGIN_LOCATION, pt))

        for dir in plugin_dirs:
            self._add_plugindir(dir)

        # load all the plugins
        self._load_all()

    def _add_plugindir(self, dir):
        dir = os.path.abspath(os.path.expanduser(dir))

        if not os.path.isdir(dir):
            msger.warning("Plugin dir is not a directory or does not exist: %s" % dir)
            return

        if dir not in self.plugin_dirs:
            self.plugin_dirs[dir] = False
            # the value True/False means "loaded"

    def _load_all(self):
        for (pdir, loaded) in self.plugin_dirs.iteritems():
            if loaded: continue

            sys.path.insert(0, pdir)
            for mod in [x[:-3] for x in os.listdir(pdir) if x.endswith(".py")]:
                if mod and mod != '__init__':
                    if mod in sys.modules:
                        msger.debug("Module %s already exists, skip" % mod)
                    else:
                        pymod = __import__(mod)
                        self.plugin_dirs[pdir] = True
                        msger.debug("Plugin module %s:%s importing" % (mod, pymod.__file__))

            del(sys.path[0])

    def get_plugins(self, ptype):
        """ the return value is dict of name:class pairs """
        return pluginbase.get_plugins(ptype)
