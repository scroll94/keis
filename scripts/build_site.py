"""Сайт для GitHub Pages (make site): та же страница, но вместо сервера site/shim.js в браузере.

Демо-обращения разбирает настоящий сервис в открытом режиме: без цитат правил, базы ответов и LLM.
Для новых обращений выгружаются ключевые слова и готовые разборы по каждой категории и языку,
поэтому правила не дублируются вручную. Модели и данные кейса на страницу не попадают.
"""
import json
import os
import re
import sys
import uuid
from pathlib import Path

os.environ["COPILOT_PUBLIC"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot import api, classify, normalize  # noqa: E402
from copilot import triage as tr  # noqa: E402
from copilot.config import ROOT  # noqa: E402

LANGS = ("ru", "kk", "uz", "en")
NICK_TOKEN = "__NICK__"
COMPLAINTS = {
    "complaint.cheat": "игрок использует aimbot",
    "complaint.insult": "оскорбил меня в чате",
    "complaint.dm": "убил меня без причин",
    "complaint.scam": "мошенник, обман на деньги",
    "complaint.rmt_ads": "реклама другого сервера",
    "complaint.admin": "админ дал бан без причин",
    "complaint.invalid": "жб",
    "complaint.other": "случилось что-то непонятное на сервере сегодня",
}
REPORTS = {
    "report.payment": "задонатил, деньги списались",
    "report.account": "взломали аккаунт",
    "report.complaint": "он нарушает правила",
    "report.help": "застрял в текстурах",
    "report.question": "как заработать на сервере?",
    "report.offtopic": "привет",
}


def js_regex(pattern: str) -> str:
    """Регулярное выражение Python для флагов iu в JS: там \\w и \\b понимают только латиницу."""
    word = r"[\p{L}\p{N}_]"
    boundary = rf"(?:(?<={word})(?!{word})|(?<!{word})(?={word}))"
    return pattern.replace(r"\b", boundary).replace(r"\W", r"[^\p{L}\p{N}_]").replace(r"\w", word)


def archetypes() -> dict:
    """Готовый разбор на каждую категорию, язык, наличие доказательств и ника."""
    tri = tr.Triage(use_model=False, use_llm=False)
    out = {}

    def run(key, cat, ticket, lang):
        tr.detect_lang = lambda *_: lang
        r = tri({"ticket_id": "x", "reporter_hash": uuid.uuid4().hex, **ticket})
        if r["category"] == cat:
            out[key] = r

    for lang in LANGS:
        for cat, text in REPORTS.items():
            run(f"{cat}|{lang}", cat, {"kind": "report", "messages": [{"role": "player", "text": text}]}, lang)
        for cat, text in COMPLAINTS.items():
            for evidence in (0, 1):
                for nick in (0, 1):
                    t = {"kind": "complaint", "images_count": evidence, "messages": [{"role": "player", "text": text}]}
                    if nick:
                        t["reported_nick"] = NICK_TOKEN
                    run(f"{cat}|{evidence}|{nick}|{lang}", cat, t, lang)
    return out


def main():
    data = {
        "items": api.queue.snapshot(),
        "quick": {lang: api.quick_replies(lang) for lang in LANGS},
        "archetypes": archetypes(),
        "nick_token": NICK_TOKEN,
        "fix": {chr(k): v for k, v in normalize.CP1251_KK.items()},
        "kk_letters": sorted(c for c in normalize.KK_LETTERS if c not in "іІ"),
        "re": {
            "complaint": {k: js_regex(v) for k, v in classify.KW.items() if k.startswith("complaint.")},
            "payment": js_regex(classify.KW["report.payment"]),
            "account": js_regex(classify.KW["report.account"]),
            "report": {k: js_regex(v) for k, v in classify.REPORT_KW.items()},
            "empty": js_regex(classify.EMPTY_REPORT.pattern),
            "invalid": js_regex(classify.INVALID_COMPLAINT.pattern),
            "p0": js_regex(classify.P0_KW.pattern),
            "appeal": js_regex(tr.APPEAL.pattern),
            "promise": js_regex(tr.PROMISE_RISK.pattern),
            "uz": js_regex(normalize.UZ_LATIN_MARKERS.pattern),
            "ru_translit": js_regex(normalize.RU_TRANSLIT.pattern),
            "en": js_regex(normalize.EN_WORDS.pattern),
        },
    }
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site" / "data.js").write_text(
        "window.SITE_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")

    page = (ROOT / "copilot" / "static" / "index.html").read_text(encoding="utf-8")
    page = page.replace('href="/static/app.css"', 'href="copilot/static/app.css"')
    page = page.replace('<script src="/static/app.js"></script>',
                        '<script src="site/data.js"></script>\n<script src="site/shim.js"></script>\n'
                        '<script src="copilot/static/app.js"></script>')
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta name="robots" content="noindex">')
    finding = '<p class="finding" id="finding">Загружаю очередь…</p>'
    page = page.replace(finding, finding + '\n        <p class="demo-note">Демонстрация кейса Decentrathon 6.0. '
                        'Обращения выдуманные, это не официальный сервис Grand Mobile.</p>')
    assert "site/shim.js" in page and "demo-note" in page and re.search(r'href="/static', page) is None
    (ROOT / "index.html").write_text(page, encoding="utf-8")
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"готово: {len(data['items'])} обращений, {len(data['archetypes'])} готовых разборов")


if __name__ == "__main__":
    main()
