#!/usr/bin/python

import os
from micng.utils.errors import *

class pkgManager:
    def __init__(self):
        self.managers = {}
        self.default_pkg_manager = None

    def register_pkg_manager(self, name, manager):
#        print "Registering package manager: %s" % name
        if not self.managers.has_key(name):
            self.managers[name] = manager
        
    def unregister_pkg_manager(self, name):
        if self.managers.has_key(name):
            del self.managers[name]

    def set_default_pkg_manager(self, name):
        if self.managers.has_key(name):
            self.default_pkg_manager = self.managers[name]
            print "Use package manager %s" % name

    def get_default_pkg_manager(self):
        if self.default_pkg_manager:
            return self.default_pkg_manager
        else:
            if self.managers.has_key("zypp"):
                print "Use package manager zypp"
                return self.managers["zypp"]
            elif self.managers.has_key("yum"):
                print "Use package manager yum"
                return self.managers["yum"]
            else:
                keys = self.managers.keys()
                if keys:
                    print "Use package manager %s" % keys[0]
                    return self.managers[keys[0]]
                else:
                    return None

    def load_pkg_managers(self):
        mydir = os.path.dirname(os.path.realpath(__file__))
        for file in os.listdir(mydir):
            if os.path.isfile(mydir + "/" + file) and file.endswith(".py") and file != "__init__.py":
                pkgmgrmod = file[:file.rfind(".py")]
                try:
                    exec("import micng.utils.pkgmanagers.%s as %s " % (pkgmgrmod, pkgmgrmod))
                    exec("pkgmgr = %s._pkgmgr" % pkgmgrmod)
                    self.register_pkg_manager(pkgmgr[0], pkgmgr[1])
                except:
                    continue
        if not self.managers.keys():
            raise CreatorError("No packag manager available")
