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

    def addRepository(self):
        pass

def get_plugins(typen):
    ps = ImagerPlugin.get_plugins()
    if typen in ps:
        return ps[typen]
    else:
        return None

__all__ = ['ImagerPlugin', 'BackendPlugin', 'get_plugins']
