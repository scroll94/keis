"""HTTP-сервис.

POST /triage                       контракт кейса: тикет -> разбор и черновик
GET  /                             интерфейс администратора: очередь, черновик, решения
GET  /api/queue                    очередь для интерфейса
POST /api/tickets                  новое обращение из интерфейса
POST /api/tickets/{id}/decision    решение админа: отправить, сохранить правку, эскалировать

Запуск: uvicorn copilot.api:app --port 8000
"""
import gzip
import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ARTIFACTS, ROOT
from .triage import Triage

STATIC = Path(__file__).resolve().parent / "static"
# Очередь интерфейса: по умолчанию выдуманный демо-набор; можно указать свой .json или .jsonl
QUEUE_PATH = Path(os.environ.get("COPILOT_QUEUE", ROOT / "demo" / "tickets.json"))
# Решения админов: правки черновиков — обучающий сигнал для шаблонов и модели
FEEDBACK_PATH = ARTIFACTS / "feedback.jsonl"


# Модели запроса терпимы к типам: кривые поля приводит triage._normalize, а не ошибка 422
class Attachment(BaseModel):
    type: str | None = "image"
    url: str | None = None


class Message(BaseModel):
    role: str | None = "player"  # player | reported_player | admin
    ts: str | None = None
    text: str | None = ""
    attachments: list[Attachment] | None = Field(default_factory=list)


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
    action: Literal["send", "save", "escalate"]
    text: str | None = None


def _read_tickets(path: Path) -> list[dict]:
    if not path.exists():
        return []
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Queue:
    """Очередь интерфейса в памяти. Своя память дублей, чтобы демо не влияло на POST /triage."""

    def __init__(self, path: Path):
        self.triage = Triage()
        self.items: dict[str, dict] = {}
        self.lock = Lock()
        for t in sorted(_read_tickets(path), key=lambda t: t.get("created_at") or ""):
            self.add(t)

    def add(self, t: dict) -> dict:
        with self.lock:
            t.setdefault("ticket_id", f"new-{len(self.items) + 1:03d}")
            t.setdefault("created_at", datetime.now().isoformat(timespec="minutes"))
            item = {"ticket": t, "result": self.triage(t), "status": "new", "final_text": None, "decided_at": None}
            self.items[t["ticket_id"]] = item
            return item

    def decide(self, ticket_id: str, d: Decision) -> dict:
        with self.lock:
            item = self.items.get(ticket_id)
            if not item:
                raise KeyError(ticket_id)
            draft = item["result"]["draft"]["text"]
            final = (d.text or "").strip() or item["final_text"] or draft
            item["final_text"] = final if final != draft else None
            if d.action != "save":
                item["status"] = "sent" if d.action == "send" else "escalated"
            item["decided_at"] = datetime.now().isoformat(timespec="seconds")
            r = item["result"]
            record = {
                "ts": item["decided_at"], "ticket_id": ticket_id, "action": d.action,
                "category": r["category"], "priority": r["priority"], "language": r["language"],
                "template": r["draft"]["template"], "needs_human": r["needs_human"],
                "draft": draft, "final": final, "edited": final != draft,
            }
            ARTIFACTS.mkdir(exist_ok=True)
            with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return item


app = FastAPI(title="Grand Mobile Support Copilot")
triage = Triage()
queue = Queue(QUEUE_PATH)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health():
    return {"ok": True, "model": triage.model is not None, "llm": triage.llm is not None}


@app.post("/triage")
def do_triage(ticket: Ticket):
    t0 = time.perf_counter()
    out = triage(ticket.model_dump())
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/queue")
def get_queue():
    llm = queue.triage.llm
    return {
        "items": list(queue.items.values()),
        "llm": {"provider": llm.provider, "model": llm.model} if llm else None,
    }


@app.post("/api/tickets")
def add_ticket(ticket: Ticket):
    t = ticket.model_dump(exclude_none=True)
    t.pop("ticket_id", None)
    return queue.add(t)


@app.post("/api/tickets/{ticket_id}/decision")
def decide(ticket_id: str, d: Decision):
    try:
        return queue.decide(ticket_id, d)
    except KeyError:
        raise HTTPException(404, f"нет обращения {ticket_id}")
