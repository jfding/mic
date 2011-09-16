PYTHON ?= python
VERSION = $(shell cat VERSION)
TAGVER = $(shell cat VERSION | sed -e "s/\([0-9\.]*\).*/\1/")

PKGNAME = mic

ifeq ($(VERSION), $(TAGVER))
	TAG = $(TAGVER)
else
	TAG = "HEAD"
endif

ifndef PREFIX
    PREFIX = "/usr/local"
endif

all:
	$(PYTHON) setup.py build

dist-common:
	git archive --format=tar --prefix=$(PKGNAME)-$(TAGVER)/ $(TAG) | tar xpf -
	git show $(TAG) --oneline | head -1 > $(PKGNAME)-$(TAGVER)/commit-id

dist-bz2: dist-common
	tar jcpf $(PKGNAME)-$(TAGVER).tar.bz2 $(PKGNAME)-$(TAGVER)
	rm -rf $(PKGNAME)-$(TAGVER)

dist-gz: dist-common
	tar zcpf $(PKGNAME)-$(TAGVER).tar.gz $(PKGNAME)-$(TAGVER)
	rm -rf $(PKGNAME)-$(TAGVER)

install: all
	$(PYTHON) setup.py install  --prefix=$(DESTDIR)/$(PREFIX)

develop: all
	$(PYTHON) setup.py develop

clean:
	rm -f tools/*.py[co]
	rm -rf *.egg-info
	rm -rf build/
	rm -rf dist/
