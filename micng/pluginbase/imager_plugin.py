#!/usr/bin/python

class ImagerPlugin(object):
    plugin_type = "imager"
    def do_create(self):
        pass

    def do_chroot(self):
        pass

    def do_pack(self):
        pass

    def do_unpack(self):
        pass

#[a, b]: a is for subcmd name, b is for plugin class 
mic_plugin = ["", None]
