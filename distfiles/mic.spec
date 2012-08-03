%define is_tizen %(test -e /etc/tizen-release -o -e /etc/meego-release && echo 1 || echo 0)
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
Name:       mic
Summary:    Image Creator for Linux Distributions
Version:    0.14
Release:    1
Group:      System/Base
License:    GPLv2
BuildArch:  noarch
URL:        http://www.tizen.org
Source0:    %{name}-%{version}.tar.gz
Requires:   rpm-python
Requires:   util-linux
Requires:   coreutils
Requires:   python >= 2.5
Requires:   e2fsprogs
Requires:   dosfstools >= 2.11-8
%if 0%{is_tizen} == 0
Requires:   yum >= 3.2.24
%endif
%if 0%{?suse_version} == 1210
Requires:   syslinux == 4.04.1
%else
Requires:   syslinux >= 3.82
%endif
Requires:   kpartx
Requires:   parted
Requires:   device-mapper
Requires:   /usr/bin/genisoimage
Requires:   cpio
Requires:   isomd5sum
Requires:   gzip
Requires:   bzip2
Requires:   squashfs-tools >= 4.0
Requires:   python-urlgrabber
%if 0%{?suse_version}
Requires:   btrfsprogs
%else
Requires:   btrfs-progs
%endif

%if 0%{?fedora_version} || 0%{is_tizen} == 1
Requires:   m2crypto
%else
%if 0%{?suse_version} == 1210
Requires:   python-M2Crypto
%else
Requires:   python-m2crypto
%endif
%endif

%if 0%{?fedora_version} == 16
Requires:   syslinux-extlinux
%endif

%if 0%{?suse_version} == 1210
Requires:   python-zypp == 0.5.50
%else
Requires:   python-zypp >= 0.5.9.1
%endif
BuildRequires:  python-devel

Obsoletes:  mic2

BuildRoot:  %{_tmppath}/%{name}-%{version}-build


%description
The tool mic is used to create and manipulate images for Linux distributions.
It is composed of three subcommand\: create, convert, chroot. Subcommand create
is used to create images with different types; subcommand convert is used to
convert an image to a specified type; subcommand chroot is used to chroot into
an image.


%prep
%setup -q -n %{name}-%{version}


%build
CFLAGS="$RPM_OPT_FLAGS" %{__python} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%if 0%{?suse_version}
%{__python} setup.py install --root=$RPM_BUILD_ROOT --prefix=%{_prefix}
%else
%{__python} setup.py install --root=$RPM_BUILD_ROOT -O1
%endif

# install man page
# remove yum backend for tizen
%if 0%{is_tizen} == 1
rm -rf %{buildroot}/%{_prefix}/lib/%{name}/plugins/backend/yumpkgmgr.py
%endif
mkdir -p %{buildroot}/%{_prefix}/share/man/man1
install -m644 doc/mic.1 %{buildroot}/%{_prefix}/share/man/man1


%files
%defattr(-,root,root,-)
%doc README.rst
%{_mandir}/man1/*
%dir %{_sysconfdir}/%{name}
%config(noreplace) %{_sysconfdir}/%{name}/%{name}.conf
%{python_sitelib}/*
%dir %{_prefix}/lib/%{name}
%{_prefix}/lib/%{name}/*
%{_bindir}/*
