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

import os
from subprocess import *

from mic import msger

def runtool(cmdln_or_args, catch=1):
    """ wrapper for most of the subprocess calls
    input:
        cmdln_or_args: can be both args and cmdln str (shell=True)
        catch: 0, quitely run
               1, only STDOUT
               2, only STDERR
               3, both STDOUT and STDERR
    return:
        (rc, output)
        if catch==0: the output will always None
    """

    if catch not in (0, 1, 2, 3):
        # invalid catch selection, will cause exception, that's good
        return None

    if isinstance(cmdln_or_args, list):
        args = cmdln_or_args
    else:
        import shlex
        args = shlex.split(cmdln_or_args)

    if catch != 3:
        dev_null = os.open("/dev/null", os.O_WRONLY)

    if catch == 0:
        sout = dev_null
        serr = dev_null
    elif catch == 1:
        sout = PIPE
        serr = dev_null
    elif catch == 2:
        sout = dev_null
        serr = PIPE
    elif catch == 3:
        sout = PIPE
        serr = PIPE

    try:
        p = Popen(args, stdout=sout, stderr=serr)
        out = p.communicate()[0]
    except OSError, e:
        if e.errno == 2:
            # [Errno 2] No such file or directory
            msger.error('Cannot run command: %s, lost dependency?' % args[0])
        else:
            raise # relay
    finally:
        if catch != 3:
            dev_null = os.open("/dev/null", os.O_WRONLY)

    return (p.returncode, out)

def show(cmdln_or_args):
    # show all the message using msger.verbose

    rc, out = runtool(cmdln_or_args, catch=3)

    if isinstance(cmdln_or_args, list):
        cmd = ' '.join(cmdln_or_args)
    else:
        cmd = cmdln_or_args

    msg =  'running command: "%s"' % cmd
    if out: out = out.strip()
    if out:
        msg += ', with output::'
        msg += '\n  +----------------'
        for line in out.splitlines():
            msg += '\n  | %s' % line
        msg += '\n  +----------------'

    msger.verbose(msg)
    return rc

def outs(cmdln_or_args):
    # get the outputs of tools
    return runtool(cmdln_or_args, catch=1)[1].strip()

def quiet(cmdln_or_args):
    return runtool(cmdln_or_args, catch=0)[0]

