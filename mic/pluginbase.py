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

from mic import msger

class _Plugin(object):
    class __metaclass__(type):
        def __init__(cls, name, bases, attrs):
            if not hasattr(cls, 'plugins'):
                cls.plugins = {}

            elif 'mic_plugin_type' in attrs:
                    if attrs['mic_plugin_type'] not in cls.plugins:
                        cls.plugins[attrs['mic_plugin_type']] = {}

            elif hasattr(cls, 'mic_plugin_type') and 'name' in attrs:
                    cls.plugins[cls.mic_plugin_type][attrs['name']] = cls

        def show_plugins(cls):
            for cls in cls.plugins[cls.mic_plugin_type]:
                print cls

        def get_plugins(cls):
            return cls.plugins

class ImagerPlugin(_Plugin):
    mic_plugin_type = "imager"

    def do_create(self):
        pass

    def do_chroot(self):
        pass

    def do_pack(self):
        pass

    def do_unpack(self):
        pass

class BackendPlugin(_Plugin):
    mic_plugin_type="backend"

    # suppress the verbose rpm warnings
    if msger.get_loglevel() != 'debug':
        import rpm
        rpm.setVerbosity(rpm.RPMLOG_ERR)

    def addRepository(self):
        pass

def get_plugins(typen):
    ps = ImagerPlugin.get_plugins()
    if typen in ps:
        return ps[typen]
    else:
        return None

__all__ = ['ImagerPlugin', 'BackendPlugin', 'get_plugins']
