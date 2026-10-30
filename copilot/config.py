import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env: KEY=VALUE, переменные окружения имеют приоритет."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")
# Папка с выданными данными. По умолчанию — соседняя папка handout, можно переопределить.
DATA_DIR = Path(os.environ.get(
    "COPILOT_DATA_DIR",
    ROOT.parent / "grand-support-copilot-handout-2026-10-27" / "handout",
))
ARTIFACTS = ROOT / "artifacts"

RULES_PATH = DATA_DIR / "rules.json"
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"
TRAIN_PATH = DATA_DIR / "tickets_train.jsonl.gz"
VALID_PATH = DATA_DIR / "tickets_valid.jsonl"
MODEL_PATH = ARTIFACTS / "classifier.pkl"
VERDICT_PATH = ARTIFACTS / "verdict.pkl"
KB_PATH = ARTIFACTS / "kb.pkl"
