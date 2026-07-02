.DEFAULT_GOAL := help

PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip
REQ_STAMP := $(VENV_DIR)/.requirements-installed

HOST ?= 127.0.0.1
PORT ?= 5000
DEBUG ?= 0

.PHONY: help setup install run test clean clean-venv

help:
	@echo "MVR Offer Tool — Make targets"
	@echo ""
	@echo "Setup"
	@echo "  make setup            Create .venv and install requirements.txt"
	@echo "  make install          Same as setup"
	@echo ""
	@echo "Run"
	@echo "  make run              Start Flask dev server (host=127.0.0.1, port=5000)"
	@echo "  make run DEBUG=1      Start with debug mode enabled"
	@echo "  make run PORT=8080    Start on a custom port"
	@echo ""
	@echo "Tests"
	@echo "  make test             Run all tests with pytest"
	@echo ""
	@echo "Utilities"
	@echo "  make clean            Remove __pycache__, .pytest_cache, .hypothesis"
	@echo "  make clean-venv       Remove virtual environment (.venv/)"

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV_DIR)

$(REQ_STAMP): requirements.txt | $(VENV_PYTHON)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	@touch $(REQ_STAMP)

install: $(REQ_STAMP)

setup: install

run: install
	@if [ "$(DEBUG)" = "1" ]; then \
		FLASK_APP=app $(VENV_PYTHON) -m flask run --host $(HOST) --port $(PORT) --debug; \
	else \
		FLASK_APP=app $(VENV_PYTHON) -m flask run --host $(HOST) --port $(PORT); \
	fi

test: install
	$(VENV_PYTHON) -m pytest tests/ -v

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".hypothesis" -prune -exec rm -rf {} +

clean-venv:
	rm -rf $(VENV_DIR)
