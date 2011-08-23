--- ./mic_cases/base/test.ks	2011-08-23 11:18:52.562082531 +0800
+++ meego-handset-armv7hl-n900-1.2.0.90.12.20110808.1.ks	2011-08-23 11:20:29.543093697 +0800
@@ -6,48 +6,77 @@
 lang en_US.UTF-8
 keyboard us
 timezone --utc America/Los_Angeles
-part / --size 3000 --ondisk sda --fstype=ext3
+part / --size=1750  --ondisk mmcblk0p --fstype=ext3
+
+# This is not used currently. It is here because the /boot partition
+# needs to be the partition number 3 for the u-boot usage.
+part swap --size=8 --ondisk mmcblk0p --fstype=swap
+
+# This partition is made so that u-boot can find the kernel
+part /boot --size=32 --ondisk mmcblk0p --fstype=vfat
+
 rootpw meego 
 xconfig --startxonboot
-bootloader --timeout=0 --append="quiet"
-desktop --autologinuser=meego  
+desktop --autologinuser=meego  --defaultdesktop=DUI --session="/usr/bin/mcompositor"
 user --name meego  --groups audio,video --password meego 
 
-repo --name=1.2-oss --baseurl=http://download.meego.com/snapshots/1.2.0.90.12.20110808.80/repos/oss/ia32/packages/ --save --debuginfo --source --gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-meego
-repo --name=1.2-non-oss --baseurl=http://download.meego.com/snapshots/1.2.0.90.12.20110808.80/repos/non-oss/ia32/packages/ --save --debuginfo --source --gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-meego
+repo --name=1.2-oss --baseurl=http://linux-ftp.intel.com/pub/mirrors/MeeGo/snapshots/stable/1.2.0.90/1.2.0.90.12.20110808.1/repos/oss/armv7hl/packages/ --save --debuginfo --source --gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-meego
+repo --name=1.2-non-oss --baseurl=http://linux-ftp.intel.com/pub/mirrors/MeeGo/snapshots/stable/1.2.0.90/1.2.0.90.12.20110808.1/repos/non-oss/armv7hl/packages/ --save --debuginfo --source --gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-meego
 
 %packages
 
-@MeeGo Base Development
-@Base Double Byte IME Support
 @MeeGo Compliance
 @MeeGo Core
-@MeeGo X Window System
-@X for Netbooks
-@MeeGo Netbook
-@MeeGo Netbook Desktop
-@Printing
-@Games
-
-kernel-adaptation-pinetrail
-
-chromium
--adobe-release
--flash-plugin
+@X for Handsets
+@MeeGo Handset Desktop
+@MeeGo Handset Applications
+@MeeGo Base Development
+@Minimal MeeGo X Window System
+@Nokia N900 Support
+@Nokia N900 Proprietary Support
+
+kernel-adaptation-n900
+
+xorg-x11-utils-xev
 %end
 
 %post
 # save a little bit of space at least...
 rm -f /boot/initrd*
 
-# Prelink can reduce boot time
-if [ -x /usr/sbin/prelink ]; then
-    /usr/sbin/prelink -aRqm
-fi
-
 rm -f /var/lib/rpm/__db*
 rpm --rebuilddb
 
+# Remove cursor from showing during startup BMC#14991
+echo "xopts=-nocursor" >> /etc/sysconfig/uxlaunch
+
+# open serial line console for embedded system
+echo "s0:235:respawn:/sbin/agetty -L 115200 ttyO2 vt100" >> /etc/inittab
+
+# Set up proper target for libmeegotouch
+Config_Src=`gconftool-2 --get-default-source`
+gconftool-2 --direct --config-source $Config_Src \
+  -s -t string /meegotouch/target/name N900
+
+# Normal bootchart is only 30 long so we use this to get longer bootchart during startup when needed.
+cat > /sbin/bootchartd-long << EOF
+#!/bin/sh
+exec /sbin/bootchartd -n 4000
+EOF
+chmod +x /sbin/bootchartd-long
+
+# Use eMMC swap partition as MeeGo swap as well.
+# Because of the 2nd partition is swap for the partition numbering
+# we can just change the current fstab entry to match the eMMC partition.
+sed -i 's/mmcblk0p2/mmcblk1p3/g' /etc/fstab
+
+# Without this line the rpm don't get the architecture right.
+echo -n 'armv7hl-meego-linux' > /etc/rpm/platform
+ 
+# Also libzypp has problems in autodetecting the architecture so we force tha as well.
+# https://bugs.meego.com/show_bug.cgi?id=11484
+echo 'arch = armv7hl' >> /etc/zypp/zypp.conf
+
 
 %end
 
