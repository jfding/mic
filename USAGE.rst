=====
 mic
=====

-----------------------------------------------
mic Means Image Creator for Linux distributions
-----------------------------------------------
:Date:           2012-03-02
:Copyright:      GPLv2
:Version:        0.1
:Manual section: 1
:Manual group:   System

SYNOPSIS
========

| mic create SUBCOMMAND <ksfile> [OPTION]
| mic chroot [OPTION] <imgfile>
| mic convert [OPTION] <imgfile> <format>

DESCRIPTION
===========
The tools `mic` is used to create and manipulate images for Linux distributions.
It is composed of three subcommand: `create`, `convert`, `chroot`. 

USAGE
=====

create
------
This command is used to create various images, including live CD, live USB, 
loop, raw.

Usage:

 | mic create(cr) SUBCOMMAND <ksfile> [OPTION]

Subcommands:

 | help(?)      give detailed help on a specific sub-command
 | fs           create fs image, which is also chroot directory
 | livecd       create live CD image, used for CD booting
 | liveusb      create live USB image, used for USB booting
 | loop         create loop image, including multi-partitions
 | raw          create raw image, containing multi-partitions

Options:

  -h, --help  show the help message
  --logfile=LOGFILE  specify the path of logfile, save the output to logfile LOGFILE
  -c CONFIG, --config=CONFIG  specify configure file for mic, default is /etc/mic/mic.conf
  -k CACHEDIR, --cachedir=CACHEDIR  cache directory used to store the downloaded files and packages
  -o OUTDIR, --outdir=OUTDIR  directory used to locate the output image and files
  -A ARCH, --arch=ARCH  specify repo architecture, genarally mic would detect the architecture, if existed more than one architecture, mic would give hint to you
  --local-pkgs-path=LOCAL_PKGS_PATH  specify the path for local rpm packages, which would be stored your own rpm packages
  --pkgmgr=PKGMGR  specify backend package mananger, currently yum and zypp available
  --record-pkgs=RECORD_PKGS  record the info of installed packages, multiple values can be specified which joined by ",", valid values: "name", "content", "license"
  --pack-to=PACK_TO   pack the images together into the specified achive, extension supported: .zip, .tar, .tar.gz, .tar.bz2, etc. by default, .tar will be used
  --release=RID  generate a release of RID with all necessary files, when @BUILD_ID@ is contained in kickstart file, it will be replaced by RID. sample values: "latest", "tizen_20120101.1"
  --copy-kernel  copy kernel files from image /boot directory to the image output directory

Options for fs image:
  --include-src  generate a image with source rpms included; to enable it, user should specify the source repo in the ks file

Options for loop image:
  --shrink       whether to shrink loop images to minimal size
  --compress-image=COMPRESS_IMAGE compress all loop images with 'gz' or 'bz2'
  --compress-disk-image=COMPRESS_DISK_IMAGE same with --compress-image

Options for raw image:
  --compress-image=COMPRESS_IMAGE compress all raw images with 'gz' or 'bz2'
  --compress-disk-image=COMPRESS_DISK_IMAGE same with --compress-image

Examples:

 | mic create loop tizen.ks
 | mic create livecd tizen.ks --release=latest
 | mic cr fs tizen.ks --local-pkgs-path=localrpm

chroot
------
This command is used to chroot inside the image, it's a great enhancement of chroot command in linux system.

Usage:

 | mic chroot(ch) <imgfile>

Options:

  -h, --help  show the help message
  -s SAVETO, --saveto=SAVETO  save the unpacked image to specified directory SAVETO

Examples:

 | mic chroot loop.img
 | mic chroot tizen.iso
 | mic ch -s tizenfs tizen.usbimg

convert
-------
This command is used for converting an image to another format.

Usage:

 | mic convert(cv) <imagefile> <destformat>

Options:

   -h, --help  show the help message
   -S, --shell  launch interactive shell before packing the new image in the converting

Examples:

 | mic convert tizen.iso liveusb
 | mic convert tizen.usbimg livecd
 | mic cv --shell tizen.iso liveusb

Advanced Usage
==============
The advanced usage is just for bootstrap, please skip it if you don't care about it.

The major purpose to use bootstrap is that some important packages (like rpm) are customized
a lot in the repo which you want to create image, and mic must use the customized rpm to 
create images, or the images can't be boot. So mic will create a bootstrap using the repo
in the ks file at first, then create the image via chrooting, which can make mic using the
chroot environment with the customized rpm.

Now mic will use bootstrap to create image by default, and to meet your requirement, you can
also change the setting for bootstrap (/etc/mic/bootstrap.conf):
[main]
distro_name = tizen  # which distro will be used for creating bootstrap
rootdir = /var/tmp/mic-bootstrap  # which dir will be located when creating bootstrap
enable = true # whether to enable the bootstrap mode

[tizen] # the supported distro for creating bootstrap
optional:  # which packages will be optional when creating bootstrap for this distro
packages:  # which packages will be required when creating bootstrap for this distro

KNOWN ISSUES
============
Bug of latest syslinux package
------------------------------
In some new Linux distributions, the "syslinux" package in their official
software repositories is the version 4.04. It will cause segment fault for
a fatal bug, and mic will failed with syslinux installation errors.

The solution is to install the patched "syslinux" package in MeeGo or Tizen's
tools repos, until the official released one being fixed.

Failed to create btrfs image in openSUSE
----------------------------------------
When creating btrfs image in openSUSE, it would hang up with showing image kernel 
panic. This issue impact all openSUSE distributions: 12.1, 11.4, 11.3, etc 

REPORTING BUGS
==============
The source code is tracked in github.com:

    https://github.com/jfding/mic

Please report issues for bugs or feature requests.
