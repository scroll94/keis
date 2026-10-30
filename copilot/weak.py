"""Слабая разметка категорий по тренировочным данным, без LLM.

В тренировочных тикетах есть ответ администратора: код нарушения («2.1 ОП», «DM», «1.1 GZ»),
вердикт и типовая фраза («спешу на помощь», «слежу за игроком»). По ним восстанавливаем
категорию тикета, а модель потом учится предсказывать её только по тексту игрока.
Тикеты без надёжного сигнала остаются без метки (None).
"""
import re

from .classify import EMPTY_REPORT, INVALID_COMPLAINT, KW, REPORT_KW
from .normalize import content_text, fix_text

# Код нарушения из ответа админа -> категория жалобы
CODE_CATEGORY = [
    (r"\b(2\.1|2\.4|2\.6|5\.7|5\.8)\s*(оп|op)?\b", "complaint.insult"),
    (r"\b5\.2\s*(оп|op)?\b|\bсофт|\bчит", "complaint.cheat"),
    (r"\b(4\.1|4\.2)\s*(оп|op)?\b|мошен|обман", "complaint.scam"),
    (r"\b(2\.3|4\.4)\s*(оп|op)?\b|реклам", "complaint.rmt_ads"),
    (r"\b(5\.1|5\.3|5\.4|5\.5)\s*(оп|op)?\b|\d\.\d\s*(gz|гз)\b|\b(gz|гз|dm|db|sk|tk|rk|pg|дм|дб|ск|тк|рк|пг|nonrp|нрп)\b|non ?rp", "complaint.dm"),
    (r"\b(1\.6|2\.2|2\.5|3\.2|5\.6|5\.9)\s*(оп|op)\b", "complaint.other"),
]

# Типовые ответы админа на репорт -> категория репорта
REPLY_CATEGORY = [
    (r"спешу|спешит|помощь (уже )?в пути|в пути|лечу|бегу|иду\b|направляюсь|попробую (вам )?помочь|постараюсь (вам )?помочь|попытаюсь|эвакуатор|подключился к вашей|телепорт|не телепортируем|yordamga", "report.help"),
    (r"слежу за (указанным )?(вами )?игроком|при наличии доказательств|пишите жалобу|напишите жалобу|не вмешиваемся в рп|не вмешивается в рп|не согласны с наказанием", "report.complaint"),
    (r"узнайте самостоятельно|не владеем|нет информации|^\W*(приветствую\W*)?(да|нет)\W*$", "report.question"),
    (r"уточните|оффтоп|приятной игры", "report.offtopic"),
]


def admin_text(t: dict) -> str:
    return " ".join(m.get("text", "") for m in t.get("messages", []) if m.get("role") == "admin").lower()


def player_text(t: dict) -> str:
    raw = "\n".join(m.get("text", "") for m in t.get("messages", []) if m.get("role") == "player")
    return fix_text(raw, t.get("server_lang"))


def weak_label(t: dict) -> str | None:
    text = player_text(t).lower()
    adm = admin_text(t)
    if t.get("kind") == "report":
        for cat in ("report.payment", "report.account"):
            if re.search(REPORT_KW[cat], text):
                return cat
        if EMPTY_REPORT.match(text):
            return "report.offtopic"
        for cat in ("report.complaint", "report.help"):
            if re.search(REPORT_KW[cat], text):
                return cat
        for pat, cat in REPLY_CATEGORY:
            if re.search(pat, adm):
                return cat
        if re.search(REPORT_KW["report.question"], text) and len(content_text(text)) > 10:
            return "report.question"
        return None

    verdict = t.get("verdict")
    if verdict in ("appeal_approved", "appeal_rejected"):
        return "complaint.admin"
    code_src = " ".join(filter(None, [t.get("violation") or "", adm])).lower()
    if verdict in ("approved", "already_punished"):
        for pat, cat in CODE_CATEGORY:
            if re.search(pat, code_src):
                return cat
    if INVALID_COMPLAINT.match(text):
        return "complaint.invalid"
    # Тема жалобы важнее оформления: «оск родни» с вердиктом invalid_format всё равно про оскорбления
    for cat, pat in KW.items():
        if cat.startswith("report."):
            continue
        if re.search(pat, text):
            return cat
    refs = (t.get("rule_refs_raw") or "").lower()
    for pat, cat in CODE_CATEGORY:
        if re.search(pat, refs):
            return cat
    if verdict in ("invalid_format", "need_evidence") and len(content_text(text)) < 25:
        return "complaint.invalid"
    if verdict == "approved":
        return "complaint.other"
    return None
