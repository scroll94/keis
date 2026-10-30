# Python из виртуального окружения: на Windows — .venv/Scripts/python.exe, на Linux/macOS — .venv/bin/python
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python.exe
else
PY ?= .venv/bin/python
endif
# Python для создания окружения (на Linux может понадобиться PYTHON=python3)
PYTHON ?= python
# -X utf8: вывод кириллицы в консоль Windows без ошибок кодировки
RUN = $(PY) -X utf8

IN ?= ../grand-support-copilot-handout-2026-10-27/handout/tickets_valid.jsonl
OUT ?= pred.jsonl

.PHONY: install predict serve train eval test

install:
	$(PYTHON) -m venv .venv
	$(RUN) -m pip install -r requirements.txt

predict:
	$(RUN) scripts/predict.py --in $(IN) --out $(OUT)

serve:
	$(RUN) -m uvicorn copilot.api:app --host 0.0.0.0 --port 8000

train:
	$(RUN) scripts/build_kb.py
	$(RUN) scripts/train.py

eval:
	$(RUN) scripts/evaluate.py $(ARGS)

test:
	$(RUN) -m unittest discover tests
