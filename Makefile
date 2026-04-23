# LinuxAgent v4 developer commands.
# Red-lines enforced by `make security` mirror the CI security job.

.PHONY: help install test lint type security harness clean

help:
	@echo "Targets:"
	@echo "  install    Editable install with dev extras"
	@echo "  test       pytest tests/unit/ with coverage"
	@echo "  lint       ruff check"
	@echo "  type       mypy"
	@echo "  security   grep red-lines + bandit"
	@echo "  harness    scenario-driven HITL harness"
	@echo "  clean      remove build / cache artifacts"

install:
	pip install -e ".[dev]"

test:
	pytest tests/unit/ --cov=linuxagent --cov-report=term-missing --cov-fail-under=80

lint:
	ruff check src/linuxagent/ tests/

type:
	mypy src/linuxagent/

security:
	@echo "--> R-SEC-01 shell=True"
	@! grep -rn "shell=True" src/linuxagent/
	@echo "--> R-SEC-03 AutoAddPolicy"
	@! grep -rn "AutoAddPolicy" src/linuxagent/
	@echo "--> R-QUAL-01 bare except"
	@! grep -rnE '^[[:space:]]*except:[[:space:]]*$$' src/linuxagent/
	@echo "--> R-HITL-05 input() in graph nodes"
	@if [ -d src/linuxagent/graph ]; then ! grep -rn "input(" src/linuxagent/graph/; fi
	@echo "--> bandit"
	@bandit -q -r src/linuxagent/ -ll

harness:
	python -m tests.harness.runner --scenarios tests/harness/scenarios/

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info \
	       .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
