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
from mic import msger

DEFAULT_PLUGIN_LOCATION = "/usr/lib/mic/plugins"

PLGUIN_TYPES = ["imager", "backend", "hook"]

STRING_PLUGIN_MARK = "mic_plugin"
STRING_PTYPE_MARK = "plugin_type"

class PluginMgr(object):
    def __init__(self, plugin_dirs=[]):
        self.plugin_locations = []
        self.plugin_sets = {}
        self.plugin_types = PLGUIN_TYPES

        # initial plugin directory
        self.addPluginDir(DEFAULT_PLUGIN_LOCATION)
        for directory in plugin_dirs:
            self.addPluginDir(os.path.expanduser(directory))

        # intial plugin sets
        for plugintype in self.plugin_types:
            self.plugin_sets[plugintype] = []

    def addPluginDir(self, plugin_dir):
        if not os.path.isdir(plugin_dir):
            msger.debug("Plugin dir is not a directory or does not exist: %s" % plugin_dir)
            return

        if plugin_dir not in self.plugin_locations:
            self.plugin_locations.append(plugin_dir)

    def pluginCheck(self, pymod):
        if not hasattr(pymod, STRING_PLUGIN_MARK):
            msger.debug("Not a valid plugin: %s" % pymod.__file__)
            msger.debug("Please check whether %s given" % STRING_PLUGIN_MARK)
            return False

        plclass = getattr(pymod, STRING_PLUGIN_MARK)[1]
        if not hasattr(plclass, STRING_PTYPE_MARK):
            msger.debug("Not a valid plugin: %s" % pymod.__file__)
            msger.debug("Please check whether %s given" % STRING_PTYPE_MARK)
            return False

        pltype = getattr(plclass, STRING_PTYPE_MARK)
        if not (pltype in self.plugin_types):
            msger.debug("Unsupported plugin type in %s: %s" % (pymod.__file__, plugintype))
            return False

        return True

    def importModule(self, dir_path, plugin_filename):
        if plugin_filename.endswith(".pyc"):
            return

        if not plugin_filename.endswith(".py"):
            msger.debug("Not a python file: %s" % os.path.join(dir_path, plugin_filename))
            return

        if plugin_filename == ".py":
            msger.debug("Empty module name: %s" % os.path.join(dir_path, plugin_filename))
            return

        if plugin_filename == "__init__.py":
            msger.debug("Unsupported python file: %s" % os.path.join(dir_path, plugin_filename))
            return

        modname = os.path.splitext(plugin_filename)[0]
        if sys.modules.has_key(modname):
            pymod = sys.modules[modname]
            msger.debug("Module %s already exists: %s" % (modname, pymod.__file__))

        else:
            pymod = __import__(modname)
            pymod.__file__ = os.path.join(dir_path, plugin_filename)
            msger.debug("Plugin module %s:%s importing" % (modname, pymod.__file__))

        if not self.pluginCheck(pymod):
            msger.warning("Failed to check plugin: %s" % os.path.join(dir_path, plugin_filename))
            return

        (pname, pcls) = pymod.__dict__[STRING_PLUGIN_MARK]
        plugintype = getattr(pcls, STRING_PTYPE_MARK)
        self.plugin_sets[plugintype].append((pname, pcls))

    def loadPlugins(self):
        for pdir in map(os.path.abspath, self.plugin_locations):
            for pitem in os.walk(pdir):
                sys.path.insert(0, pitem[0])
                for pf in pitem[2]:
                    self.importModule(pitem[0], pf)
                del(sys.path[0])

    def getPluginByCateg(self, categ = None):
        if not (categ in self.plugin_types):
            msger.warning("Failed to get plugin category: %s" % categ)
            return None
        else:
            return self.plugin_sets[categ]

    def getImagerPlugins(self):
        return self.plugin_sets['imager']

    def getBackendPlugins(self):
        return self.plugin_sets['backend']

    def getHookPlugins(self):
        return self.plugin_sets['hook']

    def listAllPlugins(self):
        # just for debug
        for key in self.plugin_sets.keys():
            msger.debug("plugin type (%s) :::\n" % key)
            for item in self.plugin_sets[key]:
                msger.debug("%-6s: %s\n" % (item[0], item[1]))

    def getPluginType(self, plugin_str):
        pass

if __name__ == "__main__":
    msger.set_loglevel('debug')

    pluginmgr = PluginMgr()
    pluginmgr.loadPlugins()
    pluginmgr.listAllPlugins()
