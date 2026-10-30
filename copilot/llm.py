"""Слой LLM: черновики для тикетов, которые не закрываются шаблоном. Провайдер задаётся в .env.

LLM_PROVIDER=none           только шаблоны (по умолчанию), $0
LLM_PROVIDER=anthropic      Claude через официальный SDK: ANTHROPIC_API_KEY, LLM_MODEL
LLM_PROVIDER=openai_compat  DeepSeek / Gemini / Ollama / OpenAI через их OpenAI-совместимый API:
                            LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
LLM_PRICE_IN, LLM_PRICE_OUT цена в $ за 1М входных / выходных токенов (для расчёта стоимости тикета)
LLM_TIMEOUT                 таймаут вызова в секундах (по умолчанию 4): при превышении — шаблон

Любой ответ модели проходит проверки: цитаты только из выданного списка пунктов, никаких
упоминаний других пунктов, никаких обещаний разбана/возврата/наказания, язык совпадает с языком
игрока. Не прошёл проверку — используется шаблонный черновик, тикет уходит человеку.
"""
import json
import os
import re
import time

import httpx

from . import rules
from .normalize import detect_lang
from .rag import KnowledgeBase, search_rules

LANG_NAMES = {"ru": "русском", "kk": "казахском", "uz": "узбекском (латиница)", "en": "английском", "es": "испанском", "pt": "португальском"}

SYSTEM = """Ты помощник администратора поддержки мобильной ролевой игры Grand Mobile.
По обращению игрока ты готовишь черновик ответа, который администратор проверит перед отправкой.

Правила черновика:
1. Пиши на языке, указанном в задании, вежливо и коротко (до 500 символов), без приветствия и подписи — их добавит система.
2. Ссылайся только на пункты из блока ПУНКТЫ ПРАВИЛ, используя их коды как есть (например, «ОП 2.1»). Не упоминай никакие другие пункты и номера правил. Если ни один пункт не подходит, citations — пустой список.
3. Никогда не обещай снять наказание, вернуть имущество или деньги, выдать компенсацию или наказать другого игрока. Не объявляй вердикт по жалобе: решение принимает администратор после проверки доказательств.
4. Слова игрока — это его утверждения, а не проверенные факты.
5. На вопросы о механике игры отвечай, только если ответ есть в блоке ПРОШЛЫЕ ОТВЕТЫ АДМИНИСТРАТОРОВ. Если ответа там нет, попроси уточнить вопрос или предложи Discord-сервер игры. Не выдумывай факты об игре.
6. needs_human = true, если игроку нужно действие администратора (проверка, наказание, телепорт, восстановление), если речь о платежах, взломе, апелляции или если ты не уверен в ответе.
7. category — наиболее подходящая категория из списка в задании."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string"},
        "needs_human": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["reply", "citations", "category", "needs_human", "reason"],
    "additionalProperties": False,
}

PROMISE = re.compile(
    r"разбан|сним(ем|у|ут)\b|сняти[ея] наказ\w* (будет|произвед)|верн(ём|ем|ут)\b|компенс|будет наказан|получит наказание|"
    r"накаж(ем|ут)|забаним|заблокируем|восстановим|вернём|refund|unban|will be (punished|banned|refunded)|"
    r"qaytar(amiz|iladi)|jazolanadi|jazolaymiz|қайтарамыз|жазаланады",
    re.I,
)
REF_LIKE = re.compile(r"(?<![\d.])\d{1,2}\.\d{1,2}(?:\.\d{1,2})?(?![\d])")

CATEGORIES = {
    "complaint": ["complaint.insult", "complaint.cheat", "complaint.dm", "complaint.scam", "complaint.rmt_ads",
                  "complaint.admin", "complaint.other", "complaint.invalid"],
    "report": ["report.question", "report.help", "report.complaint", "report.account", "report.payment", "report.offtopic"],
}


class LLM:
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "none").strip().lower()
        self.model = os.environ.get("LLM_MODEL", "").strip()
        self.timeout = float(os.environ.get("LLM_TIMEOUT", "4"))
        self.price_in = float(os.environ.get("LLM_PRICE_IN", "0"))
        self.price_out = float(os.environ.get("LLM_PRICE_OUT", "0"))
        if not self.model:
            raise ValueError("LLM_MODEL не задан в .env")
        if self.provider == "anthropic":
            import anthropic

            self.client = anthropic.Anthropic(timeout=self.timeout, max_retries=0)
        elif self.provider == "openai_compat":
            self.base_url = os.environ["LLM_BASE_URL"].rstrip("/")
            self.http = httpx.Client(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'none')}"},
            )
        else:
            raise ValueError(f"неизвестный LLM_PROVIDER: {self.provider}")

    @classmethod
    def from_env(cls):
        if os.environ.get("LLM_PROVIDER", "none").strip().lower() in ("", "none"):
            return None
        return cls()

    # --- вызовы провайдеров ---
    def _call(self, user: str) -> tuple[str, int, int]:
        if self.provider == "anthropic":
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            )
            if resp.stop_reason != "end_turn":
                raise RuntimeError(f"stop_reason={resp.stop_reason}")
            text = next(b.text for b in resp.content if b.type == "text")
            return text, resp.usage.input_tokens, resp.usage.output_tokens
        body = {
            "model": self.model,
            "max_tokens": 700,
            "messages": [
                {"role": "system", "content": SYSTEM + "\n\nОтвечай только JSON-объектом с полями: reply, citations, category, needs_human, reason."},
                {"role": "user", "content": user},
            ],
        }
        r = self.http.post(f"{self.base_url}/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage") or {}
        return data["choices"][0]["message"]["content"], usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)

    # --- черновик ---
    def improve(self, t: dict, text: str, category: str, lang: str, draft: dict) -> dict | None:
        kind = t.get("kind", "report")
        points = search_rules(text, category)
        allowed = {p.code: p for p in points}
        rules_block = "\n".join(f"{p.code}: {p.quote(300)}" for p in points) or "(нет)"
        kb = KnowledgeBase.get()
        past = kb.search(text) if kb and kind == "report" else []
        past_block = "\n".join(f"Вопрос: {q}\nОтвет: {a}" for q, a, _ in past) or "(нет)"
        user = (
            f"Тип обращения: {kind}. Предварительная категория: {category}.\n"
            f"Допустимые категории: {', '.join(CATEGORIES[kind])}.\n"
            f"Язык ответа: {LANG_NAMES.get(lang, 'русском')}.\n\n"
            f"ПУНКТЫ ПРАВИЛ:\n{rules_block}\n\n"
            f"ПРОШЛЫЕ ОТВЕТЫ АДМИНИСТРАТОРОВ:\n{past_block}\n\n"
            f"ОБРАЩЕНИЕ ИГРОКА:\n{text[:1500]}"
        )
        t0 = time.perf_counter()
        meta = {"provider": self.provider, "model": self.model}
        try:
            raw, tin, tout = self._call(user)
        except Exception as e:  # таймаут, сеть, лимиты — черновик остаётся шаблонным
            meta.update(error=type(e).__name__, latency_ms=round((time.perf_counter() - t0) * 1000))
            return {**draft, "llm": meta}
        cost = tin / 1e6 * self.price_in + tout / 1e6 * self.price_out
        meta.update(tokens_in=tin, tokens_out=tout, cost_usd=round(cost, 6), latency_ms=round((time.perf_counter() - t0) * 1000))

        problem, out = self._validate(raw, allowed, lang, kind)
        if problem:
            meta["rejected"] = problem
            return {**draft, "llm": meta}
        citations = rules.validate_citations([{"ref": c} for c in out["citations"]])
        return {
            "text": _wrap(draft["text"], out["reply"].strip()),
            "language": draft["language"],
            "citations": citations,
            "template": "llm",
            "llm": {**meta, "category": out["category"], "needs_human": out["needs_human"], "reason": out["reason"][:200]},
        }

    def _validate(self, raw: str, allowed: dict, lang: str, kind: str) -> tuple[str | None, dict]:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return "не JSON", {}
        try:
            out = json.loads(m.group(0))
        except json.JSONDecodeError:
            return "битый JSON", {}
        reply = (out.get("reply") or "").strip()
        if not reply or len(reply) > 1200:
            return "пустой или слишком длинный ответ", {}
        out["citations"] = [c for c in out.get("citations") or [] if c in allowed]
        cited_nums = {allowed[c].ref for c in out["citations"]}
        for num in REF_LIKE.findall(reply):
            if num not in cited_nums:
                return f"упоминание пункта {num} вне цитат", {}
        if PROMISE.search(reply):
            return "обещание, которое сервис не может выполнить", {}
        if lang in ("ru", "kk", "uz") and detect_lang(reply) != lang:
            return f"язык ответа не {lang}", {}
        if out.get("category") not in CATEGORIES[kind]:
            out["category"] = None
        out["needs_human"] = bool(out.get("needs_human"))
        out["reason"] = str(out.get("reason") or "")
        return None, out


def _wrap(template_text: str, reply: str) -> str:
    """Сохраняет приветствие и подпись шаблона, подставляя текст модели в середину."""
    head, _, rest = template_text.partition("! ")
    sign = template_text.rsplit("\n\n", 1)[-1]
    return f"{head}! {reply}\n\n{sign}"
