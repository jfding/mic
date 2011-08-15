#!/usr/bin/python -tt
#
# Yi Yang <yi.y.yang@intel.com>
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
from pykickstart.base import *
from pykickstart.errors import *
from pykickstart.options import *
from pykickstart.commands.repo import *

class Moblin_RepoData(F8_RepoData):
    def __init__(self, baseurl="", mirrorlist="", name="", priority=None,
                 includepkgs=[], excludepkgs=[], save=False, proxy=None,
                 proxy_username=None, proxy_password=None, debuginfo=False, source=False, gpgkey=None, disable=False):
        F8_RepoData.__init__(self, baseurl=baseurl, mirrorlist=mirrorlist,
                             name=name,  includepkgs=includepkgs,
                             excludepkgs=excludepkgs)
        self.save = save
        self.proxy = proxy
        self.proxy_username = proxy_username
        self.proxy_password = proxy_password
        self.debuginfo = debuginfo
        self.disable = disable
        self.source = source
        self.gpgkey = gpgkey

    def _getArgsAsStr(self):
        retval = F8_RepoData._getArgsAsStr(self)

        if self.save:
            retval += " --save"
        if self.proxy:
            retval += " --proxy=%s" % self.proxy
        if self.proxy_username:
            retval += " --proxyuser=%s" % self.proxy_username
        if self.proxy_password:
            retval += " --proxypasswd=%s" % self.proxy_password
        if self.debuginfo:
            retval += " --debuginfo"
        if self.source:
            retval += " --source"
        if self.gpgkey:
            retval += " --gpgkey=%s" % self.gpgkey
        if self.disable:
            retval += " --disable"

        return retval

class Moblin_Repo(F8_Repo):
    def __init__(self, writePriority=0, repoList=None):
        F8_Repo.__init__(self, writePriority, repoList)

    def __str__(self):
        retval = ""
        for repo in self.repoList:
            retval += repo.__str__()

        return retval

    def _getParser(self):
        def list_cb (option, opt_str, value, parser):
            for d in value.split(','):
                parser.values.ensure_value(option.dest, []).append(d)

        op = F8_Repo._getParser(self)
        op.add_option("--save", action="store_true", dest="save",
                      default=False)
        op.add_option("--proxy", type="string", action="store", dest="proxy",
                      default=None, nargs=1)
        op.add_option("--proxyuser", type="string", action="store", dest="proxy_username",
                      default=None, nargs=1)
        op.add_option("--proxypasswd", type="string", action="store", dest="proxy_password",
                      default=None, nargs=1)
        op.add_option("--debuginfo", action="store_true", dest="debuginfo",
                      default=False)
        op.add_option("--source", action="store_true", dest="source",
                      default=False)
        op.add_option("--disable", action="store_true", dest="disable",
                      default=False)
        op.add_option("--gpgkey", type="string", action="store", dest="gpgkey",
                      default=None, nargs=1)
        return op
