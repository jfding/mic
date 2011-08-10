#!/usr/bin/python -t
import os
import sys
import logging

DEFAULT_PLUGIN_LOCATION="/usr/lib/micng/plugins"
DEFINED_PLGUIN_TYPES=["imager", "backend", "hook"]
STRING_PLUGIN_MARK="mic_plugin"
STRING_PTYPE_MARK="plugin_type"

class PluginMgr(object):
    def __init__(self, plugin_dirs=[]):
        self.plugin_locations = []
        self.plugin_sets = {}
        self.plugin_types = DEFINED_PLGUIN_TYPES
        # initial plugin directory
        self.addPluginDir(DEFAULT_PLUGIN_LOCATION)
        for directory in plugin_dirs:
            self.addPluginDir(os.path.expanduser(directory))
        # intial plugin sets
        for plugintype in self.plugin_types:
            self.plugin_sets[plugintype] = []
    
    def addPluginDir(self, plugin_dir=None):
        if not os.path.exists(plugin_dir):
            logging.debug("Directory already exists: %s" % plugin_dir)
            return
        if not os.path.isdir(plugin_dir):
            logging.debug("Not a directory: %s" % plugin_dir)
            return
        if not (plugin_dir in self.plugin_locations):
            self.plugin_locations.append(plugin_dir)

    def pluginCheck(self, pymod):
        if not hasattr(pymod, STRING_PLUGIN_MARK):
            logging.debug("Not a valid plugin: %s" % pymod.__file__)
            logging.debug("Please check whether %s given" % STRING_PLUGIN_MARK)
            return False
        plclass = getattr(pymod, STRING_PLUGIN_MARK)[1]
        if not hasattr(plclass, STRING_PTYPE_MARK):
            logging.debug("Not a valid plugin: %s" % pymod.__file__)
            logging.debug("Please check whether %s given" % STRING_PTYPE_MARK)
            return False
        pltype = getattr(plclass, STRING_PTYPE_MARK)
        if not (pltype in self.plugin_types):
            logging.debug("Unsupported plugin type in %s: %s" % (pymod.__file__, plugintype))
            return False
        return True

    def importModule(self, dir_path, plugin_filename):
        if plugin_filename.endswith(".pyc"):
            return
        if not plugin_filename.endswith(".py"):
            logging.debug("Not a python file: %s" % os.path.join(dir_path, plugin_filename))
            return
        if plugin_filename == "__init__.py":
            logging.debug("Unsupported python file: %s" % os.path.join(dir_path, plugin_filename))
            return
        modname = os.path.splitext(plugin_filename)[0]
        if sys.modules.has_key(modname):
            pymod = sys.modules[modname]
            logging.debug("Module %s already exists: %s" % (modname, pymod.__file__))
        else:
            pymod = __import__(modname)
            pymod.__file__ = os.path.join(dir_path, plugin_filename)
        if not self.pluginCheck(pymod):
            logging.warn("Failed to check plugin: %s" % os.path.join(dir_path, plugin_filename))
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
            logging.warn("Failed to get plugin category: %s" % categ)
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
        for key in self.plugin_sets.keys():
            sys.stdout.write("plugin type (%s) :::\n" % key)
            for item in self.plugin_sets[key]:
                sys.stdout.write("%-6s: %s\n" % (item[0], item[1]))

    def getPluginType(self, plugin_str):
        pass

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    pluginmgr = PluginMgr()
    pluginmgr.loadPlugins()
    pluginmgr.listAllPlugins()
    
