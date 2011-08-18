#!/usr/bin/python -tt
# vim: ai ts=4 sts=4 et sw=4

#    Copyright (c) 2009 Intel Corporation
#
#    This program is free software; you can redistribute it and/or modify it
#    under the terms of the GNU General Public License as published by the Free
#    Software Foundation; version 2 of the License
#
#    This program is distributed in the hope that it will be useful, but
#    WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
#    or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
#    for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc., 59
#    Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os,sys
import re

__ALL__ = ['set_mode', 'info', 'warning', 'error', 'ask']

# COLORs in ANSI
INFO_COLOR = 32 # green
WARN_COLOR = 33 # yellow
ERR_COLOR  = 31 # red
ASK_COLOR  = 34 # blue

PREFIX_RE = re.compile('^<(.*?)>\s*(.*)')

INTERACTIVE = True

def _color_print(head, color, msg = None, stream = sys.stdout):

    colored = True
    if not stream.isatty():
        colored = False
    elif os.getenv('ANSI_COLORS_DISABLED') is not None:
        colored = False

    if colored:
        head = '\033[%dm%s:\033[0m' %(color, head)
    else:
        head += ':'

    if msg:
        stream.write('%s %s\n' % (head, msg))
    else:
        stream.write('%s ' % head)

def _color_perror(head, color, msg):
    _color_print(head, color, msg, sys.stderr)

def _split_msg(head, msg):
    if msg.startswith('\n'):
        msg = msg.lstrip()
        head = '\n' + head

    m = PREFIX_RE.match(msg)
    if m:
        head += ' <%s>' % m.group(1)
        msg = m.group(2)
    return head, msg

def set_mode(interactive):
    global INTERACTIVE
    if interactive:
        INTERACTIVE = True
    else:
        INTERACTIVE = False

def info(msg):
    head, msg = _split_msg('Info', msg)
    _color_print(head, INFO_COLOR, msg)

def warning(msg):
    head, msg = _split_msg('Warning', msg)
    _color_perror(head, WARN_COLOR, msg)

def error(msg):
    head, msg = _split_msg('Error', msg)
    _color_perror(head, ERR_COLOR, msg)
    sys.exit(1)

def ask(msg, default=True):
    _color_print('Q', ASK_COLOR, '')
    try:
        if default:
            msg += '(Y/n) '
        else:
            msg += '(y/N) '
        if INTERACTIVE:
            repl = raw_input(msg)
            if repl.lower() == 'y':
                return True
            elif repl.lower() == 'n':
                return False
            else:
                return default

        else:
            sys.stdout.write('%s ' % msg)
            if default:
                sys.stdout.write('Y\n')
            else:
                sys.stdout.write('N\n')
            return default
    except KeyboardInterrupt:
        sys.stdout.write('\n')
        sys.exit(2)
