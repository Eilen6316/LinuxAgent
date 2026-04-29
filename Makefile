# LinuxAgent v4 developer commands.
# Red-lines enforced by `make security` mirror the CI security job.

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)

.PHONY: help install test integration optional-anthropic lint type security harness build verify-build clean

help:
	@echo "Targets:"
	@echo "  install    Editable install with dev extras"
	@echo "  test       pytest tests/unit/ with coverage"
	@echo "  integration optional integration tests"
	@echo "  optional-anthropic verify Anthropic extra compatibility"
	@echo "  lint       ruff check"
	@echo "  type       mypy"
	@echo "  security   grep red-lines + bandit"
	@echo "  harness    scenario-driven HITL harness"
	@echo "  build      build wheel + sdist"
	@echo "  verify-build build wheel + verify install + packaged data"
	@echo "  clean      remove build / cache artifacts"

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/unit/ --cov=linuxagent --cov-report=term-missing --cov-fail-under=80

integration:
	$(PYTHON) -m pytest tests/integration/ -m integration --integration

optional-anthropic:
	@$(PYTHON) -c "import langchain_anthropic" >/dev/null 2>&1 || { \
		echo "error: install Anthropic extra first: pip install -e '.[anthropic,dev]'" >&2; \
		exit 1; \
	}
	$(PYTHON) -m pytest tests/unit/providers/test_factory.py -q

lint:
	$(PYTHON) -m ruff check src/linuxagent/ tests/

type:
	$(PYTHON) -m mypy src/linuxagent/

security:
	@echo "--> R-QUAL-02/03 code structure"
	@$(PYTHON) scripts/check_code_rules.py
	@echo "--> R-SEC-01 shell=True"
	@! grep -rn "shell=True" src/linuxagent/
	@echo "--> R-SEC-03 AutoAddPolicy"
	@! grep -rn "AutoAddPolicy" src/linuxagent/
	@echo "--> R-QUAL-01 bare except"
	@! grep -rnE '^[[:space:]]*except:[[:space:]]*$$' src/linuxagent/
	@echo "--> R-HITL-05 input() in graph nodes"
	@if [ -d src/linuxagent/graph ]; then ! grep -rn "input(" src/linuxagent/graph/; fi
	@echo "--> bandit"
	@$(PYTHON) -m bandit -q -r src/linuxagent/ -ll

harness:
	$(PYTHON) -m tests.harness.runner --scenarios tests/harness/scenarios/

build:
	@$(PYTHON) -c "import hatchling.build" >/dev/null 2>&1 || { \
		echo "error: hatchling.build is unavailable. Run 'make install' or activate the project .venv before make build." >&2; \
		exit 1; \
	}
	$(PYTHON) -m build --no-isolation

verify-build: build
	./scripts/verify_wheel_install.sh

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info \
	       .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
