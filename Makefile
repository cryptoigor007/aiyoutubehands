.PHONY: install venv check test lint typecheck coverage version clean

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PYTEST := $(BIN)/pytest
RUFF := $(BIN)/ruff
MYPY := $(BIN)/mypy

install: venv
	$(PIP) install -e ".[dev]"

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel

check: lint typecheck test version
	@echo "ALL CHECKS PASSED"

test:
	$(PYTEST) tests/ -v --cov=aiyoutubehands --cov-report=term-missing

lint:
	$(RUFF) check src tests
	$(RUFF) format --check src tests

typecheck:
	$(MYPY) src/aiyoutubehands

coverage:
	$(PYTEST) tests/ --cov=aiyoutubehands --cov-report=html --cov-report=term-missing
	@echo "HTML coverage report: htmlcov/index.html"

version:
	@echo "VERSION file: $$(cat VERSION)"
	@echo "pyproject.toml: $$(grep -E '^version' pyproject.toml | head -1)"
	@$(BIN)/python -c "from importlib.metadata import version; print('installed:', version('aiyoutubehands'))" 2>/dev/null || echo "installed: not installed yet"

clean:
	rm -rf $(VENV) build dist *.egg-info .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
