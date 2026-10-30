"""Входы моделей. Используются и при обучении, и в сервисе, чтобы они точно совпадали."""
import re

from .weak import player_text

# Вердикты, по которым учится модель; «other», «closed» и пустые не несут понятного исхода
VERDICTS = {
    "approved", "need_evidence", "rejected", "invalid_format", "duplicate",
    "already_punished", "appeal_approved", "appeal_rejected",
}


def _refs(t: dict) -> str:
    return re.sub(r"\s+", " ", (t.get("rule_refs_raw") or "").strip().lower())[:40]


def category_input(t: dict) -> str:
    kind = t.get("kind", "report")
    refs = f" [ref {_refs(t)}]" if kind == "complaint" and _refs(t) else ""
    return f"[{kind}]{refs} {player_text(t)}"


def verdict_input(t: dict) -> str:
    text = player_text(t)
    images = int(t.get("images_count") or 0) + sum(
        len(m.get("attachments") or []) for m in t.get("messages", []) if m.get("role") == "player"
    )
    urls = text.count("<url>") + len(re.findall(r"https?://", text))
    accused = any(m.get("role") == "reported_player" for m in t.get("messages", []))
    meta = (
        f"[img{min(images, 3)}] [url{min(urls, 3)}] [len{min(len(text) // 40, 5)}]"
        f" [srv_{t.get('server_lang') or 'na'}] [acc{int(accused)}]"
    )
    return f"{meta} [ref {_refs(t)}] {text}"
