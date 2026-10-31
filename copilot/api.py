"""HTTP-сервис.

POST /triage                        контракт кейса: тикет -> разбор и черновик
GET  /                              интерфейс администратора
GET  /api/info                      что доступно интерфейсу: LLM, данные валидации
GET  /api/queue                     очередь для интерфейса
POST /api/tickets                   новое обращение из интерфейса
POST /api/tickets/{id}/decision     решение админа: отправить, сохранить правку, эскалировать
POST /api/tickets/bulk              то же сразу для многих обращений; reopen отменяет решение
GET  /api/quick                     быстрые ответы на языке игрока, с шаблонами из правок
POST /api/templates                 новый быстрый ответ из правки администратора
POST /api/batches                   пачка обращений из файла: разбирается в фоне
POST /api/batches/sample            пачка из валидации кейса (без ответов админов)
GET  /api/jobs/{id}                 прогресс и сводка пачки
POST /api/loadtests                 нагрузочная проверка POST /triage отдельным процессом
GET  /api/loadtests/{id}            её прогресс

Запуск: uvicorn copilot.api:app --port 8000
"""
import gzip
import json
import os
import random
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import drafts, rules
from .config import ARTIFACTS, PUBLIC, ROOT, VALID_PATH
from .llm import PROMISE, REF_LIKE
from .triage import Triage, contract_only

STATIC = Path(__file__).resolve().parent / "static"
# Очередь интерфейса: по умолчанию выдуманный демо-набор; можно указать свой .json или .jsonl
QUEUE_PATH = Path(os.environ.get("COPILOT_QUEUE", ROOT / "demo" / "tickets.json"))
# Решения админов: правки черновиков — обучающий сигнал для шаблонов и модели
FEEDBACK_PATH = ARTIFACTS / "feedback.jsonl"
LOADTEST_DIR = ARTIFACTS / "loadtests"
TEMPLATES_PATH = ARTIFACTS / "templates.json"
MAX_BATCH = 5000
PUBLIC_MAX_QUEUE = 1000
PUBLIC_MAX_LOAD = 500


# Модели запроса терпимы к типам: кривые поля приводит triage._normalize, а не ошибка 422
class Attachment(BaseModel):
    type: str | None = "image"
    url: str | None = None


class Message(BaseModel):
    role: str | None = "player"  # player | reported_player | admin
    ts: str | None = None
    text: str | None = ""
    attachments: list[Attachment] | int | str | None = Field(default_factory=list)  # в контракте кейса — число


class Ticket(BaseModel):
    ticket_id: str | int | None = None
    kind: str | None = "report"  # complaint | report
    created_at: str | None = None
    region: str | int | None = None
    server_lang: str | None = None
    lang: str | None = None
    reporter_hash: str | None = None
    reported_hash: str | None = None
    reported_nick: str | None = None
    rule_refs_raw: str | int | float | None = None
    images_count: int | str | None = 0
    messages: list[Message] | str | None = Field(default_factory=list)


class Decision(BaseModel):
    action: Literal["send", "save", "escalate", "reopen"]
    text: str | None = None


class BulkDecision(BaseModel):
    ids: list[str]
    action: Literal["send", "escalate", "reopen"]
    text: str | None = None  # общий текст для всех; {ник} заменяется ником из каждого обращения


class TemplateIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=2000)
    lang: str = "ru"


class BatchIn(BaseModel):
    name: str = "файл"
    tickets: list[dict]


class SampleIn(BaseModel):
    n: int = Field(500, ge=1, le=MAX_BATCH)


class LoadIn(BaseModel):
    n: int = Field(500, ge=1, le=MAX_BATCH)
    concurrency: int = Field(20, ge=1, le=100)
    source: str = "demo"  # demo или id пачки


def _read_tickets(path: Path) -> list[dict]:
    if not path.exists():
        return []
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * p))], 1)


class Queue:
    """Очередь интерфейса в памяти. Своя память дублей, чтобы демо не влияло на POST /triage."""

    def __init__(self, path: Path):
        self.triage = Triage()
        self.items: dict[str, dict] = {}
        self.lock = Lock()
        for t in sorted(_read_tickets(path), key=lambda t: t.get("created_at") or ""):
            self.add(t, source="demo")

    def add(self, t: dict, source: str = "form", triage: Triage | None = None) -> dict:
        t = dict(t)
        with self.lock:
            t.setdefault("ticket_id", f"new-{len(self.items) + 1:03d}")
        t.setdefault("created_at", datetime.now().isoformat(timespec="minutes"))
        t0 = time.perf_counter()
        result = (triage or self.triage)(t)  # разбор вне блокировки: решения админа не ждут пачку
        item = {
            "ticket": t, "result": result, "status": "new", "final_text": None, "decided_at": None,
            "received_at": datetime.now().isoformat(timespec="seconds"),
            "source": source, "processing_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        with self.lock:
            self.items[str(t["ticket_id"])] = item
        return item

    def snapshot(self) -> list[dict]:
        with self.lock:
            return list(self.items.values())

    def decide(self, ticket_id: str, action: str, text: str | None = None) -> dict:
        with self.lock:
            item = self.items.get(ticket_id)
            if not item:
                raise KeyError(ticket_id)
            return self._apply(ticket_id, item, action, text)

    def decide_many(self, ids: list[str], action: str, text: str | None = None) -> list[dict]:
        with self.lock:
            return [self._apply(i, self.items[i], action, text) for i in ids if i in self.items]

    def _apply(self, ticket_id: str, item: dict, action: str, text: str | None) -> dict:
        r = item["result"]
        draft = r["draft"]["text"]
        now = datetime.now().isoformat(timespec="seconds")
        if action == "reopen":  # отмена решения: обращение снова в очереди
            item.update(status="new", final_text=None, decided_at=None)
            final = draft
        else:
            typed = (text or "").strip().replace("{ник}", r["extracted"].get("nickname") or "этого игрока")
            final = typed or item["final_text"] or draft
            item["final_text"] = final if final != draft else None
            item["decided_at"] = now
            if action != "save":
                item["status"] = "sent" if action == "send" else "escalated"
        record = {
            "ts": now, "ticket_id": ticket_id, "action": action,
            "category": r["category"], "priority": r["priority"], "language": r["language"],
            "template": r["draft"]["template"], "needs_human": r["needs_human"],
            "draft": draft, "final": final, "edited": final != draft,
        }
        if not PUBLIC:
            ARTIFACTS.mkdir(exist_ok=True)
            with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return item


class BatchJob:
    """Пачка обращений, которая разбирается в фоне; интерфейс читает прогресс и сводку."""

    def __init__(self, name: str, tickets: list[dict]):
        self.id = uuid.uuid4().hex[:8]
        self.name = name
        self.tickets = sorted(tickets, key=lambda t: str(t.get("created_at") or ""))
        self.total = len(tickets)
        self.ids: list[str] = []
        self.latencies: list[float] = []
        self.started = time.time()
        self.finished: float | None = None
        self.error: str | None = None

    def run(self):
        # Своя память дублей для пачки, но общий LLM: лимит запросов в минуту один на весь сервис
        tri = Triage(use_llm=False)
        tri.llm = queue.triage.llm
        try:
            for t in self.tickets:
                item = queue.add(t, source=self.id, triage=tri)
                self.ids.append(str(item["ticket"]["ticket_id"]))
                self.latencies.append(item["processing_ms"])
        except Exception as e:  # разбор сам не падает; сюда попадёт только сбой самой очереди
            self.error = f"{type(e).__name__}: {e}"
        self.finished = time.time()

    def summary(self) -> dict:
        done = len(self.ids)
        elapsed = (self.finished or time.time()) - self.started
        with queue.lock:
            results = [queue.items[i]["result"] for i in self.ids if i in queue.items]
        llm = Counter()
        for r in results:
            m = r["draft"].get("llm")
            if m:
                llm["calls"] += 1
                err = m.get("error") or ""
                llm["accepted" if not err and "rejected" not in m else "limited" if "лимит" in err else "failed"] += 1
        human = sum(r["needs_human"] for r in results)
        return {
            "id": self.id, "name": self.name, "total": self.total, "done": done,
            "finished": self.finished is not None, "error": self.error,
            "elapsed_s": round(elapsed, 2), "per_second": round(done / elapsed, 1) if elapsed > 0 else 0,
            "p50_ms": _percentile(self.latencies, 0.5), "p95_ms": _percentile(self.latencies, 0.95),
            "max_ms": round(max(self.latencies), 1) if self.latencies else None,
            "needs_human": human, "auto": len(results) - human,
            "spam": sum(r["is_spam"] for r in results), "duplicates": sum(r["is_duplicate"] for r in results),
            "categories": Counter(r["category"] for r in results).most_common(),
            "priorities": dict(sorted(Counter(r["priority"] for r in results).items())),
            "languages": Counter(r["language"] for r in results).most_common(),
            "llm": dict(llm),
        }


app = FastAPI(title="Grand Mobile Support Copilot")
triage = Triage()
queue = Queue(QUEUE_PATH)
JOBS: dict[str, BatchJob] = {}
LOADTESTS: dict[str, dict] = {}
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health():
    return {"ok": True, "model": triage.model is not None, "llm": triage.llm is not None}


@app.post("/triage")
def do_triage(ticket: Ticket, full: bool = False):
    """Строго по контракту кейса; full=1 добавляет поля для отчёта и проверки нагрузки."""
    t0 = time.perf_counter()
    out = triage(ticket.model_dump())
    if not full:
        return contract_only(out)
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/info")
def info():
    llm = queue.triage.llm
    return {
        "public": PUBLIC,
        "llm": {"provider": llm.provider, "model": llm.model, "rpm": llm.rpm} if llm else None,
        "validation_available": VALID_PATH.exists() and not PUBLIC,
        "batches": [j.summary() for j in JOBS.values()],
    }


@app.get("/api/queue")
def get_queue():
    llm = queue.triage.llm
    return {
        "items": queue.snapshot(),
        "llm": {"provider": llm.provider, "model": llm.model} if llm else None,
        "batches": [{"id": j.id, "name": j.name, "total": j.total} for j in JOBS.values()],
    }


@app.post("/api/tickets")
def add_ticket(ticket: Ticket):
    if PUBLIC and len(queue.items) >= PUBLIC_MAX_QUEUE:
        raise HTTPException(429, "очередь демо-версии заполнена")
    t = ticket.model_dump(exclude_none=True)
    t.pop("ticket_id", None)
    return queue.add(t, source="form")


@app.post("/api/tickets/bulk")
def decide_bulk(b: BulkDecision):
    return {"items": queue.decide_many(b.ids, b.action, b.text)}


@app.post("/api/tickets/{ticket_id}/decision")
def decide(ticket_id: str, d: Decision):
    try:
        return queue.decide(ticket_id, d.action, d.text)
    except KeyError:
        raise HTTPException(404, f"нет обращения {ticket_id}")


# Быстрые ответы: готовые шаблоны, цитаты только из правил, обещаний нет (см. drafts.py)
QUICK_REPLIES = [
    ("complaint_no_evidence", "Нужны доказательства", ["ЖБ 1.2.2", "ЖБ 1.3.1"]),
    ("complaint_invalid", "Неверное оформление", ["ЖБ 1.2.3", "ЖБ 1.3.1"]),
    ("complaint_rejected", "Нарушений нет", ["ЖБ 1.3.1"]),
    ("already_punished", "Уже наказан", []),
    ("duplicate", "Повтор", ["ЖБ 1.2.9"]),
    ("appeal_rejected", "Наказание верно", ["ОП 3.4"]),
    ("report_complaint", "Как подать жалобу", ["ЖБ 1.3.1"]),
    ("offtopic", "Опишите подробнее", ["ОП 3.1"]),
    ("help", "Администратор поможет", []),
]


def _private_only() -> None:
    if PUBLIC:
        raise HTTPException(403, "в открытой демо-версии это отключено")


def _saved_templates() -> list[dict]:
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8")) if TEMPLATES_PATH.exists() else []


@app.get("/api/quick")
def quick_replies(lang: str = "ru"):
    base = [{"id": s, "title": title, "text": drafts.render(s, lang, codes),
             "citations": rules.validate_citations([{"ref": c} for c in codes])}
            for s, title, codes in QUICK_REPLIES]
    return base + [{"id": f"own-{i}", "title": t["title"], "text": t["text"], "citations": []}
                   for i, t in enumerate(_saved_templates()) if t["lang"] == lang]


@app.post("/api/templates")
def save_template(t: TemplateIn):
    """Шаблон из правки: те же запреты, что и для LLM, — без обещаний и без номеров пунктов вне цитат."""
    _private_only()
    if PROMISE.search(t.text):
        raise HTTPException(400, "в шаблоне есть обещание, которое сервис не может выполнить")
    if REF_LIKE.search(t.text):
        raise HTTPException(400, "в шаблоне есть номер пункта правил: у сохранённых шаблонов нет цитат")
    saved = _saved_templates() + [t.model_dump()]
    ARTIFACTS.mkdir(exist_ok=True)
    TEMPLATES_PATH.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"count": len(saved)}


def _start_batch(name: str, tickets: list[dict]) -> dict:
    if not tickets:
        raise HTTPException(400, "в файле нет обращений")
    if len(tickets) > MAX_BATCH:
        raise HTTPException(400, f"не больше {MAX_BATCH} обращений за раз")
    job = BatchJob(name, [t for t in tickets if isinstance(t, dict)])
    JOBS[job.id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return job.summary()


@app.post("/api/batches")
def start_batch(b: BatchIn):
    _private_only()
    return _start_batch(b.name, b.tickets)


@app.post("/api/batches/sample")
def start_sample(s: SampleIn):
    """Обращения из валидации кейса, как в скрытом тесте: без ответов администраторов и вердиктов."""
    _private_only()
    if not VALID_PATH.exists():
        raise HTTPException(404, "данные валидации не найдены: укажите COPILOT_DATA_DIR")
    tickets = _read_tickets(VALID_PATH)
    random.Random(7).shuffle(tickets)
    sample = []
    for t in tickets[: s.n]:
        t = {k: v for k, v in t.items() if k not in ("verdict", "punishment", "violation", "status")}
        t["messages"] = [m for m in t.get("messages", []) if m.get("role") != "admin"]
        sample.append(t)
    return _start_batch(f"валидация, {len(sample)}", sample)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "нет такой пачки")
    return job.summary()


@app.post("/api/loadtests")
def start_loadtest(body: LoadIn, request: Request):
    if PUBLIC and body.n > PUBLIC_MAX_LOAD:
        raise HTTPException(400, f"в открытой демо-версии не больше {PUBLIC_MAX_LOAD} запросов")
    if any(lt["proc"].poll() is None for lt in LOADTESTS.values()):
        raise HTTPException(409, "проверка нагрузки уже идёт")
    if body.source == "demo":
        tickets = [it["ticket"] for it in queue.snapshot() if it["source"] == "demo"]
    elif body.source in JOBS:
        job = JOBS[body.source]
        tickets = job.tickets
    else:
        raise HTTPException(400, "неизвестный источник обращений")
    if not tickets:
        raise HTTPException(400, "нет обращений для проверки")
    LOADTEST_DIR.mkdir(parents=True, exist_ok=True)
    lt_id = uuid.uuid4().hex[:8]
    tickets_path = LOADTEST_DIR / f"{lt_id}-tickets.json"
    out_path = LOADTEST_DIR / f"{lt_id}.json"
    tickets_path.write_text(json.dumps(tickets, ensure_ascii=False), encoding="utf-8")
    # localhost на Windows сначала пробует IPv6 и теряет ~2 с на каждом новом соединении, если сервис слушает
    # только IPv4: генератор нагрузки ходит на 127.0.0.1, чтобы мерить сервис, а не эту задержку
    # За туннелем адрес из запроса внешний: нагрузка должна идти на сервис, а не через туннель
    local = PUBLIC or request.base_url.hostname == "localhost"
    url = f"http://127.0.0.1:{request.scope['server'][1]}/" if local else str(request.base_url)
    url = url.rstrip("/") + "/triage?full=1"
    # Отдельный процесс: генератор нагрузки не отнимает процессор у сервиса, цифры честные
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "copilot.loadgen", "--url", url, "--tickets", str(tickets_path),
         "--n", str(body.n), "--concurrency", str(body.concurrency), "--out", str(out_path)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    LOADTESTS[lt_id] = {"proc": proc, "out": out_path, "n": body.n, "concurrency": body.concurrency, "source": body.source}
    return {"id": lt_id, "total": body.n, "concurrency": body.concurrency}


@app.get("/api/loadtests/{lt_id}")
def loadtest_status(lt_id: str):
    lt = LOADTESTS.get(lt_id)
    if not lt:
        raise HTTPException(404, "нет такой проверки")
    data = {"total": lt["n"], "done": 0, "finished": False}
    if lt["out"].exists():
        try:
            data = json.loads(lt["out"].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # файл как раз перезаписывается — покажем прошлое состояние при следующем опросе
    code = lt["proc"].poll()
    if code not in (None, 0) and not data.get("finished"):
        err = lt["proc"].stderr.read().decode("utf-8", "replace")[-300:] if lt["proc"].stderr else ""
        data.update(finished=True, failed=True, message=err or f"процесс завершился с кодом {code}")
    data.update(concurrency=lt["concurrency"], source=lt["source"])
    return data
