"""Индекс правил: поиск пунктов, цитаты и проверка, что цитата существует."""
import json
import re
from dataclasses import dataclass
from functools import lru_cache

from .config import RULES_PATH

# Короткие коды разделов, которыми пользуются админы и игроки («2.1 ОП», «1.2 GZ», «ЖБ 1.1.2»)
SECTION_CODES = {
    "Общие правила игры": "ОП",
    "Правила жалоб": "ЖБ",
    "Правила нахождения в Зелёной Зоне": "GZ",
    "Правила для лидеров и их заместителей": "ЛД",
    "Правила государственных организаций": "ГОС",
    "Правила государственной волны и департамента": "ГВ",
    "Правила семейных мероприятий": "СМ",
    "Правила для ОПГ": "ОПГ",
    "Правила войны за бизнес": "ВБ",
    "Правила битвы за фургон": "БФ",
}
CODE_ALIASES = {
    "ОП": "ОП", "OP": "ОП", "ОПГ": "ОПГ",
    "ЖБ": "ЖБ", "GZ": "GZ", "ГЗ": "GZ", "ЗЗ": "GZ",
}


@dataclass(frozen=True)
class Point:
    section: str      # код раздела, например «ОП»
    section_title: str
    ref: str          # «2.1»
    text: str

    @property
    def code(self) -> str:
        return f"{self.section} {self.ref}"

    def quote(self, limit: int = 220) -> str:
        """Дословный фрагмент пункта без блока санкций."""
        t = self.text.split(" | ")[0].strip()
        if len(t) <= limit:
            return t
        cut = t[:limit]
        return cut[: cut.rfind(" ")] + "…"


@lru_cache(maxsize=1)
def load_points() -> dict[str, Point]:
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    points = {}
    for sec in data["rules"]:
        code = SECTION_CODES.get(sec["category"])
        if not code:
            continue
        for p in sec.get("points", []):
            pt = Point(code, sec["category"], p["ref"], p["text"])
            points[pt.code] = pt
    return points


def get(code: str) -> Point | None:
    """Принимает «ОП 2.1», «2.1 ОП», «ЖБ 1.1.2», «2.1» (по умолчанию ОП)."""
    code = code.strip()
    m = re.match(r"^([A-Za-zА-Яа-я]+)\s*(\d+(?:\.\d+)*)$", code) or re.match(r"^(\d+(?:\.\d+)*)\s*([A-Za-zА-Яа-я]*)$", code)
    if not m:
        return None
    a, b = m.groups()
    ref, sec = (b, a) if a[0].isalpha() else (a, b)
    sec = CODE_ALIASES.get(sec.upper(), sec.upper()) if sec else "ОП"
    return load_points().get(f"{sec} {ref}")


REF_IN_TEXT = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s*(оп|op|gz|гз|жб)?(?![\d])", re.I)


def find_refs(text: str) -> list[str]:
    """Пункты правил, упомянутые в тексте игрока. Только существующие."""
    out = []
    for ref, sec in REF_IN_TEXT.findall(text or ""):
        p = get(f"{ref} {sec}" if sec else ref)
        if p and p.code not in out:
            out.append(p.code)
    return out


def validate_citations(citations: list[dict]) -> list[dict]:
    """Оставляет только цитаты на существующие пункты; текст цитаты берётся из rules.json."""
    valid = []
    for c in citations:
        p = get(c.get("ref", ""))
        if p:
            valid.append({"ref": p.code, "section": p.section_title, "quote": p.quote()})
    return valid


def short_ref(code: str) -> str:
    """Ссылка в виде контракта и taxonomy.json: общие правила — просто номер («2.1»), остальные — с кодом («ЖБ 1.2.2», «GZ 1.1»)."""
    return code[3:] if code.startswith("ОП ") else code


def cite(code: str) -> dict | None:
    p = get(code)
    return {"ref": p.code, "section": p.section_title, "quote": p.quote()} if p else None
