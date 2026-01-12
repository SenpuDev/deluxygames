VENV_DIR := .venv
PYTHON := python

.PHONY: venv run

venv:
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_DIR)\Scripts\python -m pip install --upgrade pip
	$(VENV_DIR)\Scripts\pip install -r requirements.txt

run:
	$(VENV_DIR)\Scripts\python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000



