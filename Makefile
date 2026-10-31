# Python из виртуального окружения: на Windows — .venv/Scripts/python.exe, на Linux/macOS — .venv/bin/python
ifeq ($(OS),Windows_NT)
PY ?= .venv/Scripts/python.exe
PYTHON ?= python
else
PY ?= .venv/bin/python
PYTHON ?= python3
endif
# -X utf8: вывод кириллицы в консоль Windows без ошибок кодировки
RUN = $(PY) -X utf8

# Папка с данными кейса (tickets_train.jsonl.gz, rules.json): make predict DATA=/путь/к/handout ...
ifdef DATA
export COPILOT_DATA_DIR := $(DATA)
endif

IN ?= ../grand-support-copilot-handout-2026-10-27/handout/tickets_valid.jsonl
OUT ?= pred.jsonl
MODELS = artifacts/classifier.pkl

.PHONY: install predict serve public train eval test

# Окружение создаётся само при первом запуске любой команды
$(PY):
	$(PYTHON) -m venv .venv
	$(RUN) -m pip install -r requirements.txt

# Модели обучаются сами, если их ещё нет: один раз, около 5 минут.
# В репозитории их нет, потому что они получены из данных кейса.
$(MODELS): | $(PY)
	$(RUN) scripts/build_kb.py
	$(RUN) scripts/train.py --fast

install:
	$(PYTHON) -m venv .venv
	$(RUN) -m pip install -r requirements.txt

predict: $(MODELS)
	$(RUN) scripts/predict.py --in $(IN) --out $(OUT)

serve: $(MODELS)
	$(RUN) -m uvicorn copilot.api:app --host 0.0.0.0 --port 8000

# Открытая демо-версия для показа по ссылке: только этот компьютер, снаружи доступна через туннель
public: export COPILOT_PUBLIC = 1
public: $(MODELS)
	$(RUN) -m uvicorn copilot.api:app --host 127.0.0.1 --port 8100

# Полное обучение с отложенной проверкой и метриками
train: | $(PY)
	$(RUN) scripts/build_kb.py
	$(RUN) scripts/train.py

eval: $(MODELS)
	$(RUN) scripts/evaluate.py $(ARGS)

test: | $(PY)
	$(RUN) -m unittest discover tests
