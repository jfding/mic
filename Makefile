PYTHON ?= python
VERSION = $(shell cat VERSION)
TAGVER = $(shell cat VERSION | sed -e "s/\([0-9\.]*\).*/\1/")

PKGNAME = mic

ifeq ($(VERSION), $(TAGVER))
	TAG = $(TAGVER)
else
	TAG = "HEAD"
endif


all: build

build:
	$(PYTHON) setup.py build

dist-common: man
	git archive --format=tar --prefix=$(PKGNAME)-$(TAGVER)/ $(TAG) | tar xpf -
	git show $(TAG) --oneline | head -1 > $(PKGNAME)-$(TAGVER)/commit-id
	mkdir $(PKGNAME)-$(TAGVER)/doc; mv mic.1 $(PKGNAME)-$(TAGVER)/doc
	rm -rf $(PKGNAME)-$(TAGVER)/tests

dist-bz2: dist-common
	tar jcpf $(PKGNAME)-$(TAGVER).tar.bz2 $(PKGNAME)-$(TAGVER)
	rm -rf $(PKGNAME)-$(TAGVER)

dist-gz: dist-common
	tar zcpf $(PKGNAME)-$(TAGVER).tar.gz $(PKGNAME)-$(TAGVER)
	rm -rf $(PKGNAME)-$(TAGVER)

man: USAGE.rst
	rst2man $< >mic.1

install: build
	$(PYTHON) setup.py install

develop: build
	$(PYTHON) setup.py develop

test:
	cd tests/unittest/ && $(PYTHON) suite.py 

clean:
	rm -f *.tar.gz
	rm -f *.tar.bz2
	rm -f mic/__version__.*
	rm -f tools/*.py[co]
	rm -f mic.1
	rm -rf *.egg-info
	rm -rf build/
	rm -rf dist/
