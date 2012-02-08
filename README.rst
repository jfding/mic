=====
 mic
=====
-------------------------------------
image creator for Linux distributions
-------------------------------------
:Copyright: GPLv2
:Manual section: 1

Overview
========
The tool `mic` is used to create and manipulate images for Linux distributions.
It's composed of three subcommand: create, convert, chroot. Subcommand `create`
is used to create images with different types, including fs image, loop image,
live CD image, live USB image, raw image, etc. For each image type, there is a
corresponding subcommand. (Details in the following sections)

It supports native running in many mainstream Linux distributions, including:

* Fedora (14 and above)
* openSUSE (11.3 and above)
* Ubuntu (10.04 and above)
* Debian (5.0 and above)
* MeeGo

Installation
============

Repositories
------------
So far we support `mic` binary rpms/debs for many popular Linux distributions,
please see the following list. And you can get the corresponding repository on

 `<http://download.meego.com/live/devel:/tools:/building>`_

If there is no the distribution you want in the list, please install it from
source code.

* Debian 6.0
* Fedora 14
* Fedora 15
* Fedora 16
* openSUSE 11.3
* openSUSE 11.4
* openSUSE 12.1
* Ubuntu 10.04
* Ubuntu 10.10
* Ubuntu 11.04
* Ubuntu 11.10

Binary Installation
-------------------

Fedora Installation
~~~~~~~~~~~~~~~~~~~
1. Add devel:tools:building repo:
::

  $ sudo cat <<REPO > /etc/yum.repos.d/devel-tools-building.repo
  > [devel-tools-building]
  > name=Tools for Fedora
  > baseurl=http://download.meego.com/live/devel:/tools:/building/Fedora_<VERSION>
  > enabled=1
  > gpgcheck=0
  > REPO

Also you can take the repo file on devel:tools:building as example. For example,
Fedora 13 can use:
`<http://download.meego.com/live/devel:/tools:/building/Fedora_13/devel:tools:building.repo>`_.

2. Update repolist:
::

  $ sudo yum makecache

3. Install mic:
::

  $ sudo yum install mic

openSUSE Installation
~~~~~~~~~~~~~~~~~~~~~
1. Add devel:tools:building repo:
::

  $ sudo zypper addrepo http:/download.meego.com/live/devel:/tools:/building/openSUSE_<VERSION>/ devel-tools-building

2. Update repolist:
::

  $ sudo zypper refresh

3. Update libzypp:
::

  $ sudo zypper update libzypp

4. Install mic:
::

  $ sudo zypper install mic

Ubuntu/Debian Installation
~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Append repo source:
::

  $ sudo cat <<REPO >> /etc/apt-sources.list
  > deb http://download.meego.com/live/devel:/tools:/building/<Ubuntu/Debian>_<VERSION>/ /
  > REPO

*Tips*: for Ubuntu 10.10, you need to use xUbuntu_10.10 to replace
<Ubuntu/Debian>_<VERSIN>.

2. Update repolist:
::

  $ sudo apt-get update

3. Install mic:
::

  $ sudo apt-get install mic

Source Installation
-------------------
First, get the source of mic (`<TBD>`_). Then unpack the tar ball, and use make
to process the installation.

1. Unpack:
::

  $ tar xzvf mic.tar.gz

2. Build:
::

  $ cd micng
  $ make clean
  $ make

3. Install:
::

  $ sudo make install

Configuration file
==================
The configure file for mic can be provided as `/etc/mic/mic.conf`, where you
can specify the global settings.
The blow is the content of one sample file: ::

  [common]
  ; general settings
  
  [create]
  ; settings for create subcommand
  tmpdir= /var/tmp/mic
  cachedir= /var/tmp/mic/cache
  outdir= .
  pkgmgr = zypp
  
  ; proxy = http://proxy.yourcompany.com:8080/
  ; no_proxy = localhost,127.0.0.0/8,.yourcompany.com
  ; ssl_verify = no

  [convert]
  ; settings for convert subcommand
  
  [chroot]
  ; settings for chroot subcommand

In this configuration file, there are four sections: [common] is for general
setting, and [create] [convert] [chroot] sections are for the options of
corresponding mic subcommands: create, convert, and chroot.

In the [create] section, the following values can be specified:

tmpdir
  Temporary directory used in the image creation

cachedir
  Directory to store cached repos and downloaded rpm files

outdir
  Output directory

pkgmgr
  Default backend package manager: yum or zypp

Usages
======
It's recommended to use `--help` or `help <subcmd>` to get the help message, for
the tool is more or less self-documented.

Running 'mic create'
--------------------
Subcommand *create* is used for creating images. To create an image, you should
give the sub-sub commands which presents the image type you want, and also you
should provide an argument which presents the kickstart file for using, such
as: ::

  $ sudo mic create fs test.ks

The supported image types can be listed using `mic create --help` ::

  fs             create fs image
  livecd         create livecd image
  liveusb        create liveusb image
  loop           create loop image
  raw            create raw image

For each image type, you can get their own options by `--help` option, like
`mic cr fs --help`. Meanwhile, there are some common options that can be used
by all image types, as the following ::

  -h, --help          show this help message and exit
  --logfile=LOGFILE   Path of logfile
  -c CONFIG, --config=CONFIG
                      Specify config file for mic
  -k CACHEDIR, --cachedir=CACHEDIR
                      Cache directory to store the downloaded
  -o OUTDIR, --outdir=OUTDIR
                      Output directory
  -A ARCH, --arch=ARCH
                      Specify repo architecture
  --release=RID       Generate a release of RID with all necessary
                      files,when @BUILD_ID@ is contained in kickstart file,
                      it will be replaced by RID
  --record-pkgs=RECORD_PKGS
                      Record the info of installed packages, multiple values
                      can be specified which joined by ",", valid values:
                      "name", "content", "license"
  --pkgmgr=PKGMGR     Specify backend package manager
  --local-pkgs-path=LOCAL_PKGS_PATH
                      Path for local pkgs(rpms) to be installed

*Tips*: the common options can be normally put before sub-sub command, but also
can be after them, such as: ::

  $ sudo mic cr --outdir output fs test.ks

or ::

  $ sudo mic cr fs test.ks --outdir output

*Tips*: if you failed to create armv7* image, the reason may be: qemu/qemu-arm
on your host is lower than required, please upgrade qemu/qemu-arm higher than
version 0.13.0.

Running 'mic chroot'
--------------------
Subcommand *chroot* is used to chroot an image file. Given an image file, you
can use `mic chroot` to chroot inside the image, and then you can do some
modification to the image. After you logout, the image file will keep your
changes. It's a convenient way to hack your image file.

Sample command: ::

  $ sudo mic chroot test.img

Running 'mic convert'
---------------------
Subcommand *convert* is used for converting an image to another one with
different image type. Using `convert`, you can get your needed image type
comfortably. So far converting livecd to liveusb and liveusb to livecd is
supported.

Sample command: ::

  $ sudo mic convert test.iso liveusb

Debug/Verbose Output
--------------------
When you encounter some errors, and you want to know more about it, please use
debug/verbose output to get more details in the process by adding `-d/-v`. And
it's recommended to add `-d/--debug` or `-v/--verbose` like: ::

  $ sudo mic -d cr fs test.ks

Advance Features
================

Proxy support
-------------
proxy setting in mic.conf is not enabled, but you can set proxy in repo section
of ks file, example as follows: ::

  repo --name=1.2-oss --baseurl=http://repo.meego.com/MeeGo/releases/1.2.0/repos/oss/ia32/packages/ --proxy=http://host:port --save --debuginfo --source --gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-meego

Multiple running instances support
----------------------------------
mic support running multi-instance, but cache dir can't be shared between
instances, so you should specify different cachedir for different instance
using `--cachedir`. Also outdir should be specified to a different directory
for each instance using `--outdir`, example as follows: ::

    mic cr fs netbook1.ks --cachedir=/var/tmp/cache/mic1 --outdir=out1
    mic cr fs netbook2.ks --cachedir=/var/tmp/cache/mic2 --outdir=out2

Known Issues
============

Bug of latest "syslinux" package
--------------------------------
In some new Linux distributions, the "syslinux" package in their official
software repositories is the version 4.04. It will cause segment fault for
a fatal bug, and mic will failed with syslinux installation errors.

The solution is to install the patched "syslinux" package in MeeGo or Tizen's
tools repos, until the official released one being fixed.

