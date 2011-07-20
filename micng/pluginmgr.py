#!/usr/bin/python
import os
import sys
import micng.pluginbase.base_plugin as bp

class PluginMgr(object):
    def __init__(self, dirlist = []):
        self.plugin_place = ["/usr/lib/micng/plugins"] + dirlist
        self.plugins = {}
    
    def loadPlugins(self):
        for pdir in map(os.path.abspath, self.plugin_place):
            for pitem in os.walk(pdir):
                sys.path.append(pitem[0])
                for pf in pitem[2]:
                    if not pf.endswith(".py"):
                        continue

                    pmod =  __import__(os.path.splitext(pf)[0])
                    if hasattr(pmod, "mic_plugin"):
                        pname, pcls = pmod.mic_plugin
                        ptmp = (pname, pcls)
                        if hasattr(pcls, "plugin_type"):
                            if pcls.plugin_type not in self.plugins.keys():
                                self.plugins[pcls.plugin_type] = [ptmp]
                            else:
                                self.plugins[pcls.plugin_type].append(ptmp)
                                     
    def getPluginByCateg(self, categ = None):
        if categ is None:
            return self.plugins
        else:
            return self.plugins[categ]                            
