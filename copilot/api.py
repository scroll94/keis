"""HTTP-сервис: POST /triage.

Запуск: uvicorn copilot.api:app --port 8000
"""
import time
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .triage import Triage


class Attachment(BaseModel):
    type: str = "image"
    url: str | None = None


class Message(BaseModel):
    role: Literal["player", "reported_player", "admin"] = "player"
    ts: str | None = None
    text: str = ""
    attachments: list[Attachment] = Field(default_factory=list)


class Ticket(BaseModel):
    ticket_id: str | None = None
    kind: Literal["complaint", "report"] = "report"
    created_at: str | None = None
    region: str | None = None
    server_lang: str | None = None
    lang: str | None = None
    reporter_hash: str | None = None
    reported_hash: str | None = None
    reported_nick: str | None = None
    rule_refs_raw: str | None = None
    images_count: int = 0
    messages: list[Message]


app = FastAPI(title="Grand Mobile Support Copilot")
triage = Triage()


@app.get("/health")
def health():
    return {"ok": True, "model": triage.model is not None, "llm": triage.llm is not None}


@app.post("/triage")
def do_triage(ticket: Ticket):
    t0 = time.perf_counter()
    out = triage(ticket.model_dump())
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out
