"""Сайт для GitHub Pages (make site): та же страница, но вместо сервера site/shim.js в браузере.

Демо-обращения разбирает настоящий сервис в открытом режиме: без цитат правил, базы ответов и LLM.
Для новых обращений выгружаются ключевые слова и готовые разборы по каждой категории и языку,
поэтому правила не дублируются вручную. Модели и данные кейса на страницу не попадают.
"""
import html
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

os.environ["COPILOT_PUBLIC"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot import api, classify, normalize  # noqa: E402
from copilot import triage as tr  # noqa: E402
from copilot.config import ROOT  # noqa: E402

LANGS = ("ru", "kk", "uz", "en")
NICK_TOKEN = "__NICK__"
NOTE = ("Демо кейса Decentrathon 6.0 · RAG-триаж на базе датасета Grand Mobile · Верификация по rules.json · Дешифратор cp1251 · "
        "Очередь синтетическая: условия кейса запрещают публиковать реальные тикеты")
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


def js_map(source: str, name: str) -> dict:
    """Подписи из app.js, чтобы не повторять их здесь."""
    block = re.search(rf"const {name} = \{{(.*?)\}};", source, re.S).group(1)
    return dict(re.findall(r'"?([\w.]+)"?: "([^"]+)"', block))


def static_markup(items: list[dict], app_js: str) -> dict:
    """Первый экран прямо в HTML: очередь видна без JavaScript, в том числе инструментам, читающим исходник.

    Разметка повторяет renderList в app.js, который заменяет её после запуска.
    """
    e = html.escape
    category, priority = js_map(app_js, "CATEGORY"), js_map(app_js, "PRIORITY")
    months = "янв. февр. марта апр. мая июня июля авг. сент. окт. нояб. дек.".split()
    waiting = sorted((it for it in items if it["result"]["needs_human"]),
                     key=lambda it: (it["result"]["priority"], it["ticket"]["created_at"]))
    ready = len(items) - len(waiting)
    critical = sum(it["result"]["priority"] == "p0" for it in waiting)

    def text(it):
        return " ".join(m["text"] for m in it["ticket"]["messages"] if m["role"] == "player")

    def row(it, n):
        r, id_ = it["result"], e(str(it["ticket"]["ticket_id"]))
        when = datetime.fromisoformat(it["ticket"]["created_at"])
        pill = f'<span class="pill {r["priority"]}">{priority[r["priority"]]}</span>' if r["priority"] in ("p0", "p1") else ""
        return (f'<li class="row-wrap"><input type="checkbox" class="row-check" aria-label="Выбрать {id_}">'
                f'<button class="row" aria-current="{"true" if n == 0 else "false"}">'
                f'<span class="row-title">{e(category[r["category"]])}</span>'
                f'<span class="row-slots"><span class="row-lang">{e(r["language"].upper())}</span>{pill}</span>'
                f'<span class="row-text"><span class="id">{id_}</span>{e(text(it))}</span>'
                f'<span class="row-time">{when.day} {months[when.month - 1]}, {when:%H:%M}</span></button></li>')

    first, r = waiting[0], waiting[0]["result"]
    reasons = "".join(f"<li>{e(s.replace(r['category'], f'«{category[r["category"]]}»').capitalize())}</li>" for s in r["needs_human_reasons"])
    nav = [("Ждут администратора", len(waiting)), ("Готовы к отправке", ready), ("Все обращения", None),
           ("Эскалированы", None), ("Отправлены", None), ("Архив", None)]
    return {
        "finding": f"{critical} критичных ждут ответа. Ждут администратора: {len(waiting)}, готовы к отправке: {ready}.",
        "meta": f"{len(waiting)} обращение · сначала срочные",
        "nav": "".join(f'<button class="nav-item" aria-current="{"true" if i == 0 else "false"}"><span>{title}</span>'
                       + (f'<span class="count">{count}</span>' if count is not None else "") + "</button>"
                       for i, (title, count) in enumerate(nav)),
        "list": "".join(row(it, n) for n, it in enumerate(waiting)),
        "detail": (f'<div class="detail-body"><h2>{e(category[r["category"]])}</h2>'
                   f'<div class="decision human"><h3>Нужен администратор</h3><ul>{reasons}</ul></div>'
                   f'<section class="block"><h3>Сообщение игрока</h3><p class="message">{e(text(first))}</p></section>'
                   f'<section class="block"><h3>Черновик ответа</h3><p class="message">{e(r["draft"]["text"])}</p></section></div>'
                   '<div class="actions"><button class="btn primary">Отправить</button><button class="btn">Править</button>'
                   '<button class="btn">Эскалировать</button></div>'),
    }


def write_page(data_js: str, items: list[dict]) -> None:
    """Всё в одном index.html: странице нечему не догрузиться, а открывается она сразу."""
    static = ROOT / "copilot" / "static"
    inline = lambda code: f"<script>\n{code.replace('</script', '<\\/script')}</script>"  # noqa: E731
    scripts = "\n".join(inline(code) for code in (
        data_js, (ROOT / "site" / "shim.js").read_text(encoding="utf-8"), (static / "app.js").read_text(encoding="utf-8")))
    css = (static / "app.css").read_text(encoding="utf-8")
    finding = '<p class="finding" id="finding">Загружаю очередь…</p>'

    page = (static / "index.html").read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="/static/app.css">', f"<style>\n{css}</style>")
    page, fonts = re.subn(r'(<link href="https://fonts\.googleapis\.com/css2[^"]*" rel="stylesheet")>',
                          lambda m: m.group(1) + """ media="print" onload="this.media='all'">""", page)
    page, tags = re.subn(r"<script>\s*// Страница открыта без сервера.*?onerror=\"openStaticSite\(\)\"></script>",
                         lambda _: scripts, page, flags=re.S)
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta name="robots" content="noindex">')
    page = page.replace(finding, finding + f'\n        <p class="demo-note">{NOTE}</p>')
    assert fonts == 1 and tags == 1 and "/static/" not in page.split("<style>")[0] and NOTE in page
    static_html = static_markup(items, (static / "app.js").read_text(encoding="utf-8"))
    for old, new in (
        ('<div id="nav"></div>', f'<div id="nav">{static_html["nav"]}</div>'),
        ('<div class="nav-label">Проверка</div>', '<div class="nav-label" hidden>Проверка</div>'),
        (finding, f'<p class="finding" id="finding">{static_html["finding"]}</p>'),
        ('<span class="meta" id="list-meta"></span>', f'<span class="meta" id="list-meta">{static_html["meta"]}</span>'),
        ('<ul class="list" id="list" aria-label="Обращения"></ul>', f'<ul class="list" id="list" aria-label="Обращения">{static_html["list"]}</ul>'),
        ('<section class="detail" id="detail" aria-label="Обращение"></section>',
         f'<section class="detail" id="detail" aria-label="Обращение">{static_html["detail"]}</section>'),
    ):
        assert old in page, old
        page = page.replace(old, new, 1)
    (ROOT / "index.html").write_text(page, encoding="utf-8")


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
    data_js = "window.SITE_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"

    write_page(data_js, data["items"])
    (ROOT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"готово: {len(data['items'])} обращений, {len(data['archetypes'])} готовых разборов")


if __name__ == "__main__":
    main()
