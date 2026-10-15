#
# Makefile for waldo_cam
#

PRJ ?= waldo_cam
DESTDIR ?= /usr/local/lib/${PRJ}
SRCDIR ?= $(HOME)/Projects/iot/${PRJ}
LAUNCH ?= ${PRJ}.sh
SERVICE ?= $(PRJ).service
SERVICE_DIR ?= /etc/systemd/system
PYENV ?= ${DESTDIR}/.venv
NODE := $(shell hostname)
SHELL := /bin/bash 
PYFILES = $(shell cd $(SRCDIR); ls *.py 2>/dev/null)

.PHONY: all update install clean distclean setup_dir stop start status run run-debug test lint

all: install

# Define function; $(1) is the python file name.
define copyheader =
$(DESTDIR)/$(1): $(SRCDIR)/$(1)
	cp -u $$^ $$@
endef

# Use function to create recipes for each python file.
$(foreach file,$(PYFILES),$(eval $(call copyheader,$(file))))

# Depend on all destination python files.
pyfiles: $(addprefix $(DESTDIR)/,$(PYFILES))

MFILES := ${DESTDIR}/${NODE}.toml ${DESTDIR}/Makefile ${DESTDIR}/${SERVICE} \
	${DESTDIR}/${LAUNCH}

$(DESTDIR)/$(NODE).toml: $(SRCDIR)/$(NODE).toml
	cp -u $(SRCDIR)/$(NODE).toml $(DESTDIR)

$(DESTDIR)/$(SERVICE): $(SRCDIR)/$(SERVICE)
	cp -u $(SRCDIR)/$(SERVICE) $(DESTDIR)

$(DESTDIR)/Makefile: $(SRCDIR)/Makefile
	cp -u $(SRCDIR)/Makefile $(DESTDIR)

$(DESTDIR)/$(LAUNCH): $(SRCDIR)/launch.sh
	sed s!PYENV!${PYENV}! <$(SRCDIR)/launch.sh >$(DESTDIR)/$(LAUNCH)
	chmod +x $(DESTDIR)/$(LAUNCH)

setup_dir:
	sudo mkdir -p ${DESTDIR}
	sudo chown -R ${USER}:${USER} ${DESTDIR}

${DESTDIR}: setup_dir
	cp -u ${SRCDIR}/Makefile ${DESTDIR}/
	cp -u ${SRCDIR}/requirements.txt ${DESTDIR}/
	cp -u ${SRCDIR}/${SERVICE} ${DESTDIR}/
	-cp -u ${SRCDIR}/${NODE}.toml ${DESTDIR}/
	sed s!PYENV!${PYENV}! <${SRCDIR}/launch.sh >${DESTDIR}/${LAUNCH}
	chmod +x ${DESTDIR}/${LAUNCH}

${PYENV}: setup_dir ${SRCDIR}/requirements.txt
	mkdir -p ${PYENV}
	uv venv --no-project ${PYENV}
	( \
	set -e ;\
	source ${PYENV}/bin/activate ; \
	uv pip install -r $(SRCDIR)/requirements.txt ; \
	)

update: pyfiles ${MFILES}
	sudo cp -u ${DESTDIR}/${SERVICE} ${SERVICE_DIR}/
	sudo systemctl daemon-reload

install: setup_dir ${DESTDIR} ${PYENV} update

start:
	sudo systemctl daemon-reload
	sudo systemctl enable ${SERVICE}
	sudo systemctl restart ${SERVICE}

stop:
	-sudo systemctl stop ${SERVICE}
	-sudo systemctl disable ${SERVICE}

status:
	sudo systemctl status ${SERVICE}

run:
	uv run python3 waldo.py -c ${NODE}.toml

run-debug:
	uv run python3 waldo.py -c ${NODE}.toml -d

test:
	uv run python3 -m unittest discover -s . -p "test_*.py"

lint:
	uv run flake8 --max-line-length 110 --exclude .venv,${PYENV}

clean:
	-sudo systemctl stop ${SERVICE} 2>/dev/null || true
	-sudo systemctl disable ${SERVICE} 2>/dev/null || true
	sudo rm -f ${SERVICE_DIR}/${SERVICE}
	sudo systemctl daemon-reload
	sudo rm -rf ${DESTDIR}

distclean: clean
	rm -rf .venv __pycache__
