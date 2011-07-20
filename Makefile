PYTHON ?= python
VERSION = $(shell cat VERSION)
TAGVER = $(shell cat VERSION | sed -e "s/\([0-9\.]*\).*/\1/")

PKGNAME = micng

ifeq ($(VERSION), $(TAGVER))
	TAG = $(TAGVER)
else
	TAG = "HEAD"
endif


all:
	$(PYTHON) setup.py build

dist-bz2:
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(TAG) | \
		bzip2  > $(PKGNAME)-$(VERSION).tar.bz2

dist-gz:
	git archive --format=tar --prefix=$(PKGNAME)-$(VERSION)/ $(TAG) | \
		gzip  > $(PKGNAME)-$(VERSION).tar.gz

install: all
	$(PYTHON) setup.py install --root=${DESTDIR}

develop: all
	$(PYTHON) setup.py develop

clean:
	rm -f tools/*.py[co]
	rm -rf *.egg-info
	rm -rf build/
	rm -rf dist/
