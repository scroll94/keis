"""Проверка перед коммитом (make secrets): в git не должно быть ключей и данных кейса.

Ключи ищутся по формату и по значениям из локального .env, в том числе в base64 и hex.
Найденные значения не печатаются. --history проверяет всю историю, а не только текущие файлы.
"""
import base64
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FORMATS = {
    "ключ Google": r"AIza[0-9A-Za-z_-]{30,}|\bAQ\.[0-9A-Za-z_-]{30,}",
    "ключ sk-": r"\bsk-[0-9A-Za-z_-]{20,}",
    "ключ cc_": r"\bcc_[0-9A-Za-z_-]{20,}",
    "токен GitHub": r"\bgh[pousr]_[0-9A-Za-z]{30,}|\bgithub_pat_\w{30,}",
}
FORBIDDEN_FILES = re.compile(
    r"(^|/)\.env$|(^|/)\.env\.(?!example$)|\.(pkl|joblib|pem|jsonl|jsonl\.gz)$|(^|/)artifacts/|(^|/)(rules|taxonomy)\.json$|tickets_(train|valid)")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", check=True).stdout


def env_values(path: Path) -> list[str]:
    """Значения секретов из .env и их кодировки: прятать ключ в base64 бесполезно."""
    if not path.exists():
        return []
    needles = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z0-9_]*(?:KEY|TOKEN|SECRET)[A-Z0-9_]*)\s*=\s*(.+)", line)
        value = m.group(2).strip().strip("\"'") if m else ""
        if len(value) >= 8:
            raw = value.encode()
            needles += [value, base64.b64encode(raw).decode().rstrip("="), base64.urlsafe_b64encode(raw).decode().rstrip("="), raw.hex()]
    return needles


def scan_text(text: str, needles: list[str] = ()) -> list[str]:
    found = [name for name, pattern in KEY_FORMATS.items() if re.search(pattern, text)]
    if any(n in text for n in needles):
        found.append("значение из .env")
    return found


def main() -> int:
    history = "--history" in sys.argv
    needles = env_values(ROOT / ".env")
    problems = []
    names = git("log", "--all", "--name-only", "--format=") if history else git("ls-files")
    for name in sorted(set(names.split("\n")) - {""}):
        if FORBIDDEN_FILES.search(name):
            problems.append(f"{name}: этот файл нельзя хранить в git")
    if history:
        added = "\n".join(l for l in git("log", "--all", "-p", "--format=").split("\n") if l.startswith("+"))
        problems += [f"история: {kind}" for kind in scan_text(added, needles)]
    else:
        for name in git("ls-files").split("\n"):
            path = ROOT / name
            if name and path.is_file():
                problems += [f"{name}: {kind}" for kind in scan_text(path.read_text(encoding="utf-8", errors="ignore"), needles)]
    for p in problems:
        print(p)
    print("Найдены проблемы, значения не показаны." if problems else "Ключей и данных кейса в git нет.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
