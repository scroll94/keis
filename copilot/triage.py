"""Основной конвейер триажа: тикет (dict) -> ответ по контракту (dict)."""
import re
from datetime import datetime, timedelta, timezone

from . import drafts, rules
from .classify import Model, VerdictModel, keyword_category, priority
from .features import category_input, n_attachments, verdict_input
from .llm import LLM
from .normalize import content_text, detect_lang, fix_text
from .rag import KnowledgeBase

NICK = re.compile(r"\b[A-Z][a-z]+_[A-Z][a-z]+\d{0,3}\b")
# Номер игрока в репорте («123 дм», «id 45»), но не сумма или срок («500 рублей», «3 дня»)
PLAYER_ID = re.compile(
    r"(?:^|\s|id\s?|айди\s?|\[)(\d{1,4})(?=\]|\s|$)"
    r"(?!\s*(?:руб|р\b|₽|гк|gc|тенге|тг|сум|млн|млрд|тыс|к\b|\$|%|мин|час|сек|дн|лвл|lvl|уров|раз|шт))",
    re.I,
)
SERVER = re.compile(r"(\d{1,2})\s*(?:сервер|сервак|server|serv)|(?:сервер|server)\s*№?\s*(\d{1,2})", re.I)
APPEAL = re.compile(
    r"не согл|норози|norozi|ban ?yech|yechib ber|banni ol|бан ал|банды ал|разбан|сним(ите|и)? (бан|мут|варн|наказ|деморган)|незаслуж|ни за что|без причины (дал|выдал|кинул|посадил)|"
    r"меня (забан|замут|посад|наказ|кикнул)|мне (выдал|дали|дал|кинул)\w* (бан|мут|варн)|верните|обжал|amnist|nohaq|нохақ",
    re.I,
)
PROMISE_RISK = re.compile(r"верн(и|ите)|возврат|компенс|разбан|сним(и|ите)|refund|qaytar", re.I)
GZ_HINT = re.compile(r"зел[её]н|\bзз\b|\bgz\b|\bгз\b|green|больниц|банк|автосалон|вокзал|спавн|мэри|мэрия", re.I)
HOUSE_HINT = re.compile(r"\bдом\b|у дома|квартир|у входа", re.I)
RMT_HINT = re.compile(r"реал|руб|тг|телеграм|продае|продаё|купи", re.I)
RACISM_HINT = re.compile(r"расизм|наци|национал|рели|кавказ|чурк|хач|негр", re.I)
THREAT_HINT = re.compile(r"угрож|деанон|адрес|найду|вычислю|докс", re.I)

NEEDS_HUMAN_ALWAYS = {"report.account", "report.payment", "complaint.admin"}

# Шаблон по вероятному вердикту берётся, только если модель уверена. Пороги подобраны на валидации так,
# чтобы совпадение с решением админа было не ниже ~70% (need_evidence при 0.7 — 79%, appeal_rejected при 0.6 — 71%).
# invalid_format не используется: точность модели на нём ниже 60%.
VERDICT_MIN = {"need_evidence": 0.7, "appeal_rejected": 0.6, "rejected": 0.7, "duplicate": 0.7, "already_punished": 0.7}
# База знаний: от KB_MIN ответ идёт в черновик, от KB_AUTO его можно отправить без администратора
KB_MIN, KB_AUTO = 0.7, 0.85
VERDICT_SITUATION = {
    "need_evidence": ("complaint_no_evidence", ["ЖБ 1.2.2", "ЖБ 1.3.1"]),
    "rejected": ("complaint_rejected", ["ЖБ 1.3.1"]),
    "already_punished": ("already_punished", []),
    "duplicate": ("duplicate", ["ЖБ 1.2.9"]),
}


class DedupStore:
    """Помнит недавние обращения: один игрок, одна проблема, несколько тикетов за час."""

    def __init__(self, window_min: int = 60):
        self.window = timedelta(minutes=window_min)
        self.seen: dict[tuple, tuple[datetime, str]] = {}

    def check(self, keys: list[tuple], ts: datetime, ticket_id: str) -> str | None:
        dup_of = None
        for k in keys:
            prev = self.seen.get(k)
            if prev and timedelta(0) <= ts - prev[0] <= self.window and prev[1] != ticket_id:
                dup_of = dup_of or prev[1]
        for k in keys:
            if k not in self.seen or not dup_of:
                self.seen[k] = (ts, ticket_id)
        return dup_of


def _parse_ts(s: str | None) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")) if s else datetime.now()
    except (ValueError, AttributeError):
        return datetime.now()
    # Время с часовым поясом приводим к UTC без пояса, чтобы его можно было сравнивать с остальными
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


MAX_TEXT = 20_000  # длиннее этого текст игрока обрезается: держит задержку на огромных сообщениях


def _normalize(t) -> dict:
    """Приводит тикет к ожидаемым типам: кривое поле не должно ронять разбор."""
    t = dict(t) if isinstance(t, dict) else {}
    msgs = t.get("messages")
    if isinstance(msgs, str):
        msgs = [{"role": "player", "text": msgs}]
    elif not isinstance(msgs, list):
        msgs = []
    clean = []
    for m in msgs:
        if isinstance(m, str):
            m = {"role": "player", "text": m}
        if not isinstance(m, dict):
            continue
        text = "" if m.get("text") is None else str(m.get("text"))[:MAX_TEXT]
        # В контракте кейса attachments — число вложений («"attachments": 2»), в API бывает и список
        clean.append({**m, "role": m.get("role") or "player", "text": text,
                      "attachments": m.get("attachments") if isinstance(m.get("attachments"), list) else [],
                      "n_attachments": n_attachments(m)})
    t["messages"] = clean
    if t.get("kind") not in ("complaint", "report"):
        t["kind"] = "complaint" if t.get("reported_hash") or t.get("reported_nick") else "report"
    for k in ("ticket_id", "created_at", "region", "server_lang", "reporter_hash", "reported_hash", "reported_nick", "rule_refs_raw"):
        v = t.get(k)
        t[k] = None if v is None or isinstance(v, (list, dict)) else str(v)
    try:
        t["images_count"] = max(0, int(t.get("images_count") or 0))
    except (TypeError, ValueError):
        t["images_count"] = 0
    return t


CONTRACT_KEYS = ("ticket_id", "lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply",
                 "needs_human", "confidence", "reasons")


def with_contract(r: dict) -> dict:
    """Поля контракта кейса (POST /triage) идут первыми; после них — расширенные поля для интерфейса и отчёта."""
    x = r["extracted"]
    extracted = {"nickname": x.get("reported_nick"), "rule_refs": [rules.short_ref(c) for c in x.get("rule_refs_claimed", [])],
                 "has_evidence": x.get("has_evidence", False), "server": x.get("server")}
    extracted.update({k: v for k, v in x.items() if k not in extracted})
    contract = {
        "ticket_id": r["ticket_id"],
        "lang": r["language"],
        "category": r["category"],
        "priority": r["priority"],
        "is_spam_or_duplicate": bool(r["is_spam"] or r["is_duplicate"]),
        "extracted": extracted,
        "draft_reply": {"lang": r["draft"]["language"], "text": r["draft"]["text"],
                        "cited": [rules.short_ref(c["ref"]) for c in r["draft"]["citations"]]},
        "needs_human": r["needs_human"],
        "confidence": r["confidence"],
        "reasons": r["reasons"],
    }
    return {**contract, **{k: v for k, v in r.items() if k not in contract}}


def _fallback(t, error: Exception) -> dict:
    """Ответ по контракту, если разбор всё же упал: черновик-подтверждение и обязательно человек."""
    t = t if isinstance(t, dict) else {}
    kind = t.get("kind") if t.get("kind") in ("complaint", "report") else "report"
    return with_contract({
        "ticket_id": t.get("ticket_id"),
        "language": "ru",
        "category": "complaint.other" if kind == "complaint" else "report.question",
        "priority": "p2",
        "is_spam": False,
        "is_duplicate": False,
        "duplicate_of": None,
        "extracted": {"reported_nick": None, "player_ids": [], "rule_refs_claimed": [], "rule_refs_raw": None,
                      "has_evidence": False, "evidence": {"images_count": 0, "links": 0}, "server": None, "region": None},
        "draft": {"text": drafts.render("help", "ru", []), "language": "ru", "citations": [], "template": "fallback"},
        "needs_human": True,
        "needs_human_reasons": ["обращение не удалось разобрать автоматически"],
        "suggested_verdict": None,
        "confidence": 0.0,
        "reasons": [f"ошибка разбора: {type(error).__name__}"],
    })


def _violation_codes(category: str, text: str, claimed: list[str]) -> list[str]:
    allowed = {
        "complaint.insult": ["ОП 2.1", "ОП 2.4", "ОП 2.6"],
        "complaint.cheat": ["ОП 5.2"],
        "complaint.dm": ["GZ 1.1", "GZ 1.2", "ОП 5.4"],
        "complaint.scam": ["ОП 4.1", "ОП 4.2"],
        "complaint.rmt_ads": ["ОП 2.3", "ОП 4.4"],
    }.get(category, [])
    picked = [c for c in claimed if c in allowed]
    if picked:
        return picked[:2]
    if category == "complaint.insult":
        return ["ОП 2.4"] if RACISM_HINT.search(text) else ["ОП 2.6"] if THREAT_HINT.search(text) else ["ОП 2.1"]
    if category == "complaint.dm":
        return ["GZ 1.1"] if GZ_HINT.search(text) else ["ОП 5.4"] if HOUSE_HINT.search(text) else []
    if category == "complaint.scam":
        return ["ОП 4.2"] if re.search(r"вымог|угрож", text, re.I) else ["ОП 4.1"]
    if category == "complaint.rmt_ads":
        return ["ОП 4.4"] if RMT_HINT.search(text) else ["ОП 2.3"]
    if category == "complaint.cheat":
        return ["ОП 5.2"]
    # «Другое»: доверяем только существующим пунктам, которые назвал игрок, и помечаем это
    return claimed[:1]


class Triage:
    def __init__(self, use_model: bool = True, use_llm: bool = True):
        self.model = Model.get() if use_model else None
        self.verdict = VerdictModel.get() if use_model else None
        self.kb = KnowledgeBase.get()
        self.dedup = DedupStore()
        self.llm = LLM.from_env() if use_llm else None

    def __call__(self, t: dict) -> dict:
        """Разбор одного тикета. Не падает: один кривой тикет не должен ронять пакетный прогон."""
        try:
            return self._triage(_normalize(t))
        except Exception as e:
            return _fallback(t, e)

    def _triage(self, t: dict) -> dict:
        kind = t["kind"]
        server_lang = t.get("server_lang")
        msgs = [m for m in t.get("messages", []) if m.get("role") == "player"]
        raw = "\n".join(m.get("text", "") for m in msgs)
        text = fix_text(raw, server_lang)
        body = content_text(text)
        reasons: list[str] = []

        # --- факты ---
        images = int(t.get("images_count") or 0) + sum(m["n_attachments"] for m in msgs)
        links = text.count("<url>") + len(re.findall(r"https?://", text))
        has_evidence = images > 0 or links > 0
        claimed = rules.find_refs(" ".join([t.get("rule_refs_raw") or "", text]))
        nick = t.get("reported_nick") or next((n for n in NICK.findall(text)), None)
        srv = SERVER.search(text)
        extracted = {
            "reported_nick": nick,
            "player_ids": sorted(set(PLAYER_ID.findall(" " + body + " ")))[:3] if kind == "report" else [],
            "rule_refs_claimed": claimed,  # заявлено игроком, не проверено
            "rule_refs_raw": t.get("rule_refs_raw"),
            "has_evidence": has_evidence,
            "evidence": {"images_count": images, "links": links},
            # В контракте server — регион (ответ экспертов); номер из текста — запасной вариант
            "server": t.get("region") or ((srv.group(1) or srv.group(2)) if srv else None),
            "region": t.get("region"),
        }

        # --- язык ---
        lang = detect_lang(text, server_lang)

        # --- категория: точные правила -> обученная модель -> ключевые слова ---
        cat, conf, why = keyword_category(kind, text, has_evidence)
        hard_rule = conf >= 0.85 or cat in ("report.payment", "report.account")
        if self.model and not hard_rule:
            mcat, mconf = self.model.predict(category_input(t), kind)
            cat, conf, why = mcat, mconf, f"модель ({mconf:.2f})"
        is_appeal = kind == "complaint" and bool(APPEAL.search(text))
        if is_appeal and cat != "complaint.admin":
            cat, why = "complaint.admin", "оспаривание своего наказания"
        reasons.append(f"категория: {why}")

        prio, pwhy = priority(cat, text, has_evidence)
        reasons.append(f"приоритет: {pwhy}")

        # --- спам и дубли ---
        # Спам — пустые сообщения и флуд; мат в адрес админа и «помогите» спамом не считаются
        is_spam = kind == "report" and cat == "report.offtopic" and len(body) <= 3
        if is_spam:
            reasons.append("спам: пустое сообщение без содержания")
        ts = _parse_ts(t.get("created_at"))
        rep = t.get("reporter_hash") or "anon"
        if kind == "complaint":
            keys = [("c", rep, t.get("reported_hash") or nick or body.lower()[:60])]
        else:
            keys = [("r", rep, body.lower()[:60])] if len(body) > 3 else []
        dup_of = self.dedup.check(keys, ts, t.get("ticket_id", "")) if keys else None
        is_dup = dup_of is not None
        if is_dup:
            reasons.append(f"дубль обращения {dup_of} за последний час")

        # --- вероятный вердикт администратора (подсказка, решение остаётся за человеком) ---
        verdict, vp = (None, 0.0)
        if kind == "complaint" and self.verdict:
            verdict, vp = self.verdict.predict(verdict_input(t))
            reasons.append(f"вероятный вердикт: {verdict} ({vp:.2f})")
        confident_verdict = verdict if vp >= VERDICT_MIN.get(verdict, 1.01) else None

        # --- черновик ---
        by_verdict = False  # шаблон выбран по предсказанному вердикту, а не по точному правилу
        if kind == "complaint":
            if is_dup:
                situation, codes = "duplicate", ["ЖБ 1.2.9"]
            elif cat == "complaint.admin":
                by_verdict = confident_verdict == "appeal_rejected"
                situation, codes = ("appeal_rejected", ["ОП 3.4"]) if by_verdict else ("appeal", ["ОП 3.4", "ЖБ 1.3.1"])
            elif cat == "complaint.invalid":
                situation, codes = "complaint_invalid", ["ЖБ 1.2.3", "ЖБ 1.3.1"]
            elif not has_evidence:
                situation, codes = "complaint_no_evidence", ["ЖБ 1.2.2", "ЖБ 1.3.1"]
            elif confident_verdict in VERDICT_SITUATION:
                by_verdict = True
                situation, codes = VERDICT_SITUATION[confident_verdict]
            else:
                situation, codes = "complaint_review", _violation_codes(cat, text, claimed)
        else:
            situation, codes = {
                "report.offtopic": ("offtopic", ["ОП 3.1"]),
                "report.help": ("help", []),
                "report.question": ("question", []),
                "report.complaint": ("report_complaint", ["ЖБ 1.3.1"]),
                "report.account": ("account", ["ОП 1.4"]),
                "report.payment": ("payment", []),
            }[cat]
        # Вопрос, на который админы уже отвечали: подставляем их ответ (без LLM — только для русского)
        kb_answer, kb_sim = "", 0.0
        if situation == "question" and lang == "ru" and not self.llm and self.kb:
            hits = self.kb.search(body, k=1, min_sim=KB_MIN)
            if hits:
                _, kb_answer, kb_sim = hits[0]
                situation = "question_kb"
                reasons.append(f"ответ из базы знаний (сходство {kb_sim:.2f})")
        citations = rules.validate_citations([{"ref": c} for c in codes])
        if situation == "complaint_review":
            citations += rules.validate_citations([{"ref": "ЖБ 1.4.1"}])
        draft_text = drafts.render(
            situation, lang, [c["ref"] for c in citations if c["ref"] != "ЖБ 1.4.1"],
            nick=nick if situation == "complaint_review" else None, answer=kb_answer,
        )
        draft = {"text": draft_text, "language": lang if lang in drafts.GREET else "ru", "citations": citations, "template": situation}

        # --- LLM только там, где шаблон не справляется: вопросы и неуверенная классификация ---
        llm_meta = {}
        if self.llm and not is_spam and not is_dup and (situation == "question" or conf < 0.5):
            draft = self.llm.improve(t, text, cat, lang, draft)
            llm_meta = draft.get("llm", {})
            if conf < 0.5 and llm_meta.get("category"):
                cat, conf = llm_meta["category"], 0.6
                prio, pwhy = priority(cat, text, has_evidence)
                reasons.append(f"категория уточнена LLM: {cat}; приоритет: {pwhy}")

        # --- нужен ли человек ---
        needs_human, why_h = False, []
        if cat in NEEDS_HUMAN_ALWAYS:
            needs_human, why_h = True, why_h + [f"категория {cat} всегда к человеку"]
        if situation == "complaint_review":
            needs_human, why_h = True, why_h + ["вердикт по доказательствам выносит администратор"]
        if by_verdict:
            needs_human, why_h = True, why_h + ["черновик по вероятному вердикту, нужно подтверждение администратора"]
        if cat == "report.help":
            needs_human, why_h = True, why_h + ["нужны действия администратора в игре"]
        if situation == "question" and draft["template"] != "llm":
            needs_human, why_h = True, why_h + ["ответ на вопрос требует знаний администратора"]
        # Ответ LLM на вопрос уходит без админа, только если опирается на близкий прошлый ответ администратора
        if cat == "report.question" and draft["template"] == "llm" and llm_meta.get("kb_sim", 0) < KB_MIN:
            needs_human, why_h = True, why_h + ["ответ LLM без похожего прошлого ответа администратора, стоит проверить"]
        if situation == "question_kb" and (kb_sim < KB_AUTO or len(kb_answer) < 8):
            needs_human, why_h = True, why_h + ["ответ из базы стоит проверить администратору"]
        if llm_meta.get("needs_human"):
            needs_human, why_h = True, why_h + [f"LLM: {llm_meta.get('reason') or 'нужен администратор'}"]
        if PROMISE_RISK.search(text):
            needs_human, why_h = True, why_h + ["просьба о возврате или снятии наказания"]
        if prio == "p0":
            needs_human, why_h = True, why_h + ["критичный приоритет"]
        if conf < 0.5 and not is_spam:
            needs_human, why_h = True, why_h + [f"низкая уверенность ({conf:.2f})"]
        reasons += why_h or ["можно ответить автоматически по шаблону"]

        return with_contract({
            "ticket_id": t.get("ticket_id"),
            "language": lang,
            "category": cat,
            "priority": prio,
            "is_spam": is_spam,
            "is_duplicate": is_dup,
            "duplicate_of": dup_of,
            "extracted": extracted,
            "draft": draft,
            "needs_human": needs_human,
            "needs_human_reasons": why_h,
            "suggested_verdict": {"label": verdict, "p": round(vp, 3)} if verdict else None,
            "confidence": round(conf, 3),
            "reasons": reasons,
        })
