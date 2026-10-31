"""Проверки ключевых гарантий сервиса. Запуск: python -m unittest discover tests"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from collections import deque

os.environ["LLM_PROVIDER"] = "none"  # тесты не ходят в сеть и не тратят квоту, даже если в .env есть ключ
from pathlib import Path
from threading import Lock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot import drafts, rules  # noqa: E402
from copilot.classify import keyword_category  # noqa: E402
from copilot.llm import LLM, PROMISE  # noqa: E402
from copilot.triage import Triage  # noqa: E402


def ticket(text, kind="report", **kw):
    t = {"ticket_id": kw.pop("ticket_id", "t1"), "kind": kind, "created_at": kw.pop("created_at", "2026-10-30T12:00:00"),
         "region": "cis", "server_lang": "ru", "reporter_hash": kw.pop("reporter", "r1"),
         "messages": [{"role": "player", "text": text}]}
    t.update(kw)
    return t


class RulesTest(unittest.TestCase):
    def test_lookup_variants(self):
        self.assertEqual(rules.get("2.1").code, "ОП 2.1")
        self.assertEqual(rules.get("2.1 оп").code, "ОП 2.1")
        self.assertEqual(rules.get("1.2 гз").code, "GZ 1.2")
        self.assertEqual(rules.get("ЖБ 1.1.2").code, "ЖБ 1.1.2")
        self.assertIsNone(rules.get("ОП 99.9"))

    def test_fake_citations_are_dropped(self):
        out = rules.validate_citations([{"ref": "ОП 2.1"}, {"ref": "ОП 77.7"}, {"ref": "GZ 1.1"}])
        self.assertEqual([c["ref"] for c in out], ["ОП 2.1", "GZ 1.1"])
        self.assertTrue(all(c["quote"] for c in out))


class TriageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tri = Triage(use_llm=False)

    def run_one(self, t):
        return self.tri(t)

    def test_contract_fields(self):
        r = self.run_one(ticket("помогите застрял в текстурах", ticket_id="c1"))
        for key in ("language", "category", "priority", "is_spam", "is_duplicate", "extracted", "draft", "needs_human", "confidence", "reasons"):
            self.assertIn(key, r)
        self.assertIn("text", r["draft"])
        self.assertIn("citations", r["draft"])

    def test_empty_report_is_offtopic_spam(self):
        r = self.run_one(ticket("+", ticket_id="e1"))
        self.assertEqual(r["category"], "report.offtopic")
        self.assertTrue(r["is_spam"])

    def test_payment_always_human_p0(self):
        r = self.run_one(ticket("оплатил донат 500 рублей а гк не пришли", ticket_id="p1", reporter="r2"))
        self.assertEqual(r["category"], "report.payment")
        self.assertEqual(r["priority"], "p0")
        self.assertTrue(r["needs_human"])

    def test_appeal_goes_to_human_without_promises(self):
        r = self.run_one(ticket("не согласен с наказанием, снимите бан, я ничего не делал", kind="complaint",
                                ticket_id="a1", reporter="r3", images_count=1))
        self.assertEqual(r["category"], "complaint.admin")
        self.assertTrue(r["needs_human"])
        self.assertIsNone(PROMISE.search(r["draft"]["text"]))

    def test_duplicate_within_hour(self):
        base = dict(kind="complaint", reporter="r4", reported_hash="x9", images_count=1)
        self.run_one(ticket("оск родни <url>", ticket_id="d1", created_at="2026-10-30T10:00:00", **base))
        r = self.run_one(ticket("оск родни снова <url>", ticket_id="d2", created_at="2026-10-30T10:20:00", **base))
        self.assertTrue(r["is_duplicate"])
        self.assertEqual(r["duplicate_of"], "d1")

    def test_all_citations_exist_and_no_promises(self):
        texts = ["оск родни <url>", "читер летает <url>", "убил в зз у больницы <url>", "кинул на машину <url>",
                 "продаёт акк за реал в тг <url>", "жб", "как устроиться в полицию?"]
        known = set(rules.load_points())
        for i, txt in enumerate(texts):
            kind = "report" if txt.endswith("?") else "complaint"
            r = self.run_one(ticket(txt, kind=kind, ticket_id=f"s{i}", reporter=f"u{i}", images_count=1))
            self.assertTrue(all(c["ref"] in known for c in r["draft"]["citations"]), txt)
            self.assertIsNone(PROMISE.search(r["draft"]["text"]), txt)

    def test_kazakh_and_uzbek_drafts(self):
        r = self.run_one(ticket("мені себепсіз атып тастады <url>", kind="complaint", ticket_id="k1", reporter="k", server_lang="kk", images_count=1))
        self.assertEqual(r["language"], "kk")
        self.assertTrue(r["draft"]["text"].startswith(drafts.GREET["kk"].format(name="")))
        r = self.run_one(ticket("meni sababsiz o'ldirdi <url>", kind="complaint", ticket_id="u1", reporter="u", server_lang="uz", images_count=1))
        self.assertEqual(r["language"], "uz")


class MalformedInputTest(unittest.TestCase):
    """Скрытый тест может прислать что угодно: разбор не должен падать ни на одном тикете."""

    CASES = {
        "нет сообщений": {"messages": []},
        "нет поля messages": {"messages": None},
        "text = None": {"messages": [{"role": "player", "text": None}]},
        "kind = appeal": {"kind": "appeal"},
        "kind = None": {"kind": None},
        "дата с зоной": {"created_at": "2026-10-30T12:00:00Z"},
        "кривая дата": {"created_at": "вчера"},
        "rule_refs_raw числом": {"kind": "complaint", "rule_refs_raw": 2.1},
        "images_count строкой": {"kind": "complaint", "images_count": "2"},
        "messages строкой": {"messages": "помогите застрял"},
        "attachments не список": {"messages": [{"role": "player", "text": "скрин", "attachments": 3}]},
        "огромный текст": {"messages": [{"role": "player", "text": "оск родни " * 10000}]},
    }

    def test_triage_never_crashes(self):
        tri = Triage(use_llm=False)
        for name, patch in self.CASES.items():
            t = {"ticket_id": name, "kind": "report", "created_at": "2026-10-30T12:00:00",
                 "messages": [{"role": "player", "text": "помогите"}], **patch}
            r = tri(t)
            self.assertNotEqual(r["draft"].get("template"), "fallback", name)  # разобран по-настоящему
            self.assertTrue(r["draft"]["text"] and r["category"], name)

    def test_fallback_keeps_contract(self):
        tri = Triage(use_llm=False)
        tri._triage = lambda t: 1 / 0  # любая непредвиденная ошибка внутри разбора
        r = tri({"ticket_id": "x", "kind": "complaint", "messages": []})
        self.assertEqual(r["ticket_id"], "x")
        self.assertTrue(r["needs_human"])
        self.assertEqual(r["category"], "complaint.other")
        self.assertEqual(r["draft"]["template"], "fallback")

    def test_http_accepts_malformed(self):
        from fastapi.testclient import TestClient

        from copilot.api import app

        client = TestClient(app)
        for body in ({"kind": "appeal", "messages": [{"text": None}]}, {"messages": "помогите"},
                     {"ticket_id": 5, "rule_refs_raw": 2.1, "images_count": "1", "kind": "complaint", "messages": []}):
            r = client.post("/triage", json=body)
            self.assertEqual(r.status_code, 200, body)
            self.assertIn("category", r.json())


class LLMGuardTest(unittest.TestCase):
    def setUp(self):
        self.llm = object.__new__(LLM)
        self.llm.provider, self.llm.model, self.llm.price_in, self.llm.price_out = "fake", "fake", 0.1, 0.5
        self.llm.rpm, self.llm.max_wait, self.llm._calls, self.llm._lock = 0, 0.0, deque(), Lock()
        self.base = {"text": drafts.render("question", "ru", []), "language": "ru", "citations": [], "template": "question"}

    def answer(self, reply, citations=()):
        out = {"reply": reply, "citations": list(citations), "category": "report.question", "needs_human": False, "reason": ""}
        self.llm._call = lambda user: (json.dumps(out, ensure_ascii=False), 1000, 200)
        return self.llm.improve(ticket("где взять лицензию?"), "где взять лицензию?", "report.question", "ru", self.base)

    def test_accepts_grounded_answer(self):
        d = self.answer("Лицензию выдают в Правительстве.")
        self.assertEqual(d["template"], "llm")
        self.assertAlmostEqual(d["llm"]["cost_usd"], 0.0002)

    def test_rejects_invented_rule(self):
        self.assertEqual(self.answer("Это нарушение пункта 7.7.")["template"], "question")

    def test_rejects_promise(self):
        self.assertEqual(self.answer("Мы снимем вам бан.")["template"], "question")

    def test_rejects_wrong_language(self):
        self.assertEqual(self.answer("You can get it at the Government.")["template"], "question")

    def test_rate_limit_falls_back_without_waiting(self):
        self.llm.rpm = 2  # квота: два вызова в минуту, ждать нельзя (как в HTTP-сервисе)
        results = [self.answer("Лицензию выдают в Правительстве.") for _ in range(3)]
        self.assertEqual([r["template"] for r in results], ["llm", "llm", "question"])
        self.assertEqual(results[2]["llm"]["error"], "лимит запросов в минуту")

    def test_provider_429_is_reported(self):
        def over_quota(user):
            raise httpx.HTTPStatusError("429", request=httpx.Request("POST", "http://llm"), response=httpx.Response(429))
        self.llm._call = over_quota
        d = self.llm.improve(ticket("вопрос"), "вопрос", "report.question", "ru", self.base)
        self.assertEqual(d["template"], "question")
        self.assertEqual(d["llm"]["error"], "HTTP 429")

    def test_timeout_falls_back(self):
        def boom(user):
            raise TimeoutError
        self.llm._call = boom
        d = self.llm.improve(ticket("вопрос"), "вопрос", "report.question", "ru", self.base)
        self.assertEqual(d["template"], "question")
        self.assertEqual(d["llm"]["error"], "TimeoutError")


class AdminUiTest(unittest.TestCase):
    def test_queue_decision_writes_feedback(self):
        import tempfile

        from fastapi.testclient import TestClient

        import copilot.api as api

        client = TestClient(api.app)
        with tempfile.TemporaryDirectory() as tmp:
            api.FEEDBACK_PATH = Path(tmp) / "feedback.jsonl"
            queue = client.get("/api/queue").json()
            self.assertGreaterEqual(len(queue["items"]), 10)  # демо-набор
            self.assertEqual(client.get("/").status_code, 200)

            item = client.post("/api/tickets", json={"kind": "report", "server_lang": "ru",
                                                     "messages": [{"role": "player", "text": "застрял в текстурах, помогите"}]}).json()
            tid = item["ticket"]["ticket_id"]
            r = client.post(f"/api/tickets/{tid}/decision", json={"action": "send", "text": "Здравствуйте! Иду к вам."}).json()
            self.assertEqual(r["status"], "sent")
            record = json.loads(api.FEEDBACK_PATH.read_text(encoding="utf-8").splitlines()[-1])
            self.assertTrue(record["edited"])
            self.assertEqual(record["final"], "Здравствуйте! Иду к вам.")
            self.assertEqual(client.post("/api/tickets/nope/decision", json={"action": "send"}).status_code, 404)


class BatchAndLoadTest(unittest.TestCase):
    def wait_job(self, client, job_id, timeout=30):
        import time

        t0 = time.time()
        while time.time() - t0 < timeout:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["finished"]:
                return job
            time.sleep(0.05)
        self.fail("пачка не разобралась вовремя")

    def test_batch_upload_lands_in_queue(self):
        from fastapi.testclient import TestClient

        import copilot.api as api

        client = TestClient(api.app)
        tickets = [ticket("оск родни <url>", kind="complaint", ticket_id=f"b-{i}", reporter=f"br{i}", images_count=1)
                   for i in range(3)] + [{"messages": "помогите застрял"}]  # и один кривой
        job = client.post("/api/batches", json={"name": "тест", "tickets": tickets}).json()
        job = self.wait_job(client, job["id"])
        self.assertEqual((job["done"], job["total"]), (4, 4))
        self.assertIsNone(job["error"])
        self.assertEqual(job["needs_human"] + job["auto"], 4)
        self.assertIn("complaint.insult", dict(job["categories"]))
        queue = client.get("/api/queue").json()
        mine = [it for it in queue["items"] if it["source"] == job["id"]]
        self.assertEqual(len(mine), 4)
        self.assertTrue(all(it["processing_ms"] >= 0 for it in mine))
        self.assertEqual(client.post("/api/batches", json={"name": "пусто", "tickets": []}).status_code, 400)

    def test_validation_sample_has_no_admin_answers(self):
        from fastapi.testclient import TestClient

        import copilot.api as api

        if not api.VALID_PATH.exists():
            self.skipTest("нет данных валидации")
        client = TestClient(api.app)
        job = self.wait_job(client, client.post("/api/batches/sample", json={"n": 5}).json()["id"])
        self.assertEqual(job["done"], 5)
        items = [it for it in client.get("/api/queue").json()["items"] if it["source"] == job["id"]]
        self.assertTrue(all(m["role"] != "admin" for it in items for m in it["ticket"]["messages"]))
        self.assertTrue(all("verdict" not in it["ticket"] for it in items))

    def test_loadgen_summary(self):
        from copilot.loadgen import BUCKETS, summarize

        lat = [3.0] * 90 + [40.0] * 8 + [1800.0, 7000.0]
        slow = [{"ms": 7000.0, "server_ms": 6.0, "ticket": "a", "llm": None, "ok": True},
                {"ms": 1800.0, "server_ms": 1790.0, "ticket": "b", "llm": "LLM 1780 мс", "ok": True}]
        s = summarize(lat, total=100, errors=1, elapsed=2.0, llm={"calls": 1}, finished=True, slowest=slow)
        self.assertEqual((s["done"], s["rps"], s["p50_ms"]), (100, 50.0, 3.0))
        self.assertEqual(s["hist"][0], 90)                 # до 5 мс
        self.assertEqual(s["hist"][len(BUCKETS)], 1)      # больше 5 с
        self.assertEqual(sum(s["hist"]), 100)
        self.assertEqual([x["ticket"] for x in s["slowest"]], ["a", "b"])


class BulkReplyTest(unittest.TestCase):
    def test_bulk_send_personal_text_and_undo(self):
        import tempfile

        from fastapi.testclient import TestClient

        import copilot.api as api

        client = TestClient(api.app)
        with tempfile.TemporaryDirectory() as tmp:
            api.FEEDBACK_PATH = Path(tmp) / "feedback.jsonl"
            ids = []
            for i, nick in enumerate(["Ivan_Petrov", None]):
                t = ticket("оск родни <url>", kind="complaint", reporter=f"bulk{i}", images_count=1)
                t.pop("ticket_id")
                if nick:
                    t["reported_nick"] = nick
                ids.append(client.post("/api/tickets", json=t).json()["ticket"]["ticket_id"])
            items = client.post("/api/tickets/bulk", json={"ids": ids + ["нет-такого"], "action": "send",
                                                           "text": "Жалоба на {ник} рассмотрена."}).json()["items"]
            self.assertEqual([it["status"] for it in items], ["sent", "sent"])
            self.assertEqual(items[0]["final_text"], "Жалоба на Ivan_Petrov рассмотрена.")
            self.assertEqual(items[1]["final_text"], "Жалоба на этого игрока рассмотрена.")
            items = client.post("/api/tickets/bulk", json={"ids": ids, "action": "reopen"}).json()["items"]
            self.assertTrue(all(it["status"] == "new" and it["final_text"] is None for it in items))
            self.assertEqual(len(api.FEEDBACK_PATH.read_text(encoding="utf-8").splitlines()), 4)

    def test_bulk_without_text_keeps_own_drafts(self):
        import tempfile

        from fastapi.testclient import TestClient

        import copilot.api as api

        client = TestClient(api.app)
        with tempfile.TemporaryDirectory() as tmp:
            api.FEEDBACK_PATH = Path(tmp) / "feedback.jsonl"
            t = ticket("застрял в текстурах", reporter="bulk-own")
            t.pop("ticket_id")
            tid = client.post("/api/tickets", json=t).json()["ticket"]["ticket_id"]
            item = client.post("/api/tickets/bulk", json={"ids": [tid], "action": "escalate"}).json()["items"][0]
            self.assertEqual(item["status"], "escalated")
            self.assertIsNone(item["final_text"])

    def test_quick_replies_in_player_language(self):
        from fastapi.testclient import TestClient

        from copilot.api import app

        replies = TestClient(app).get("/api/quick", params={"lang": "kk"}).json()
        self.assertGreaterEqual(len(replies), 5)
        self.assertTrue(all(r["text"].startswith(drafts.GREET["kk"].format(name="")) or r["id"] == "appeal_rejected" for r in replies))
        known = set(rules.load_points())
        self.assertTrue(all(c["ref"] in known and not PROMISE.search(r["text"]) for r in replies for c in r["citations"]))


class StreamAnswersTest(unittest.TestCase):
    """Уточнения экспертов Grand Mobile на стриме."""

    def test_server_is_region(self):
        r = Triage(use_llm=False)(ticket("помогите застрял", ticket_id="reg", region="kz"))
        self.assertEqual(r["extracted"]["server"], "kz")

    def test_obscene_message_is_not_spam(self):
        tri = Triage(use_llm=False)
        self.assertFalse(tri(ticket("сука админ", ticket_id="ob1", reporter="ob1"))["is_spam"])
        self.assertFalse(tri(ticket("помогите", ticket_id="ob2", reporter="ob2"))["is_spam"])
        self.assertTrue(tri(ticket("ау", ticket_id="ob3", reporter="ob3"))["is_spam"])

    def test_sections_without_official_code_use_full_name(self):
        code = next(c for c in rules.load_points() if c.startswith("ОПГ "))
        self.assertEqual(rules.short_ref(code), f"Правила для ОПГ {code.split()[1]}")

    def test_llm_sees_accused_comment(self):
        llm = object.__new__(LLM)
        llm.provider, llm.model, llm.price_in, llm.price_out = "fake", "fake", 0.0, 0.0
        llm.rpm, llm.max_wait, llm._calls, llm._lock = 0, 0.0, deque(), Lock()
        seen = {}

        def call(user):
            seen["prompt"] = user
            out = {"reply": "Обращение передано администратору.", "citations": ["2.1"], "category": "complaint.insult",
                   "needs_human": True, "reason": ""}
            return json.dumps(out, ensure_ascii=False), 1, 1

        llm._call = call
        t = ticket("оск родни", kind="complaint")
        t["messages"].append({"role": "reported_player", "text": "это была игра по роли"})
        base = {"text": drafts.render("complaint_review", "ru", []), "language": "ru", "citations": [], "template": "complaint_review"}
        d = llm.improve(t, "оск родни", "complaint.insult", "ru", base)
        self.assertIn("это была игра по роли", seen["prompt"])
        self.assertEqual([c["ref"] for c in d["citations"]], ["ОП 2.1"])


class ChatRequestsTest(unittest.TestCase):
    def test_cp1251_kazakh_is_repaired_and_original_kept(self):
        r = Triage(use_llm=False)(ticket("Мен ќазір текстурада тўрып ќалдым, кјмек беріѕіз", ticket_id="cp", reporter="cp", server_lang="kk"))
        self.assertEqual(r["text_fix"]["fixed"], "Мен қазір текстурада тұрып қалдым, көмек беріңіз")
        self.assertIn("ќазір", r["text_fix"]["original"])
        self.assertEqual(r["language"], "kk")

    def test_clean_text_has_no_fix(self):
        self.assertIsNone(Triage(use_llm=False)(ticket("застрял в текстурах", ticket_id="cl", reporter="cl"))["text_fix"])

    def test_template_from_edit(self):
        import tempfile

        from fastapi.testclient import TestClient

        import copilot.api as api

        client = TestClient(api.app)
        with tempfile.TemporaryDirectory() as tmp:
            api.TEMPLATES_PATH = Path(tmp) / "templates.json"
            ok = {"title": "Спавн", "text": "Проверяем проблему со спавном.", "lang": "ru"}
            self.assertEqual(client.post("/api/templates", json=ok).status_code, 200)
            self.assertIn("Спавн", [q["title"] for q in client.get("/api/quick").json()])
            self.assertNotIn("Спавн", [q["title"] for q in client.get("/api/quick", params={"lang": "uz"}).json()])
            self.assertEqual(client.post("/api/templates", json={**ok, "text": "Мы снимем вам бан."}).status_code, 400)
            self.assertEqual(client.post("/api/templates", json={**ok, "text": "Нарушение 7.7."}).status_code, 400)


class PublicModeTest(unittest.TestCase):
    def test_no_case_data_and_no_writes(self):
        script = """
import json
from fastapi.testclient import TestClient
import copilot.api as api
from copilot import rules
c = TestClient(api.app)
assert c.get("/api/info").json()["public"] is True
assert api.queue.triage.kb is None and api.queue.triage.llm is None
assert all(not x["quote"] for it in c.get("/api/queue").json()["items"] for x in it["result"]["draft"]["citations"])
assert c.post("/api/batches", json={"tickets": [{}]}).status_code == 403
assert c.post("/api/batches/sample", json={"n": 1}).status_code == 403
assert c.post("/api/templates", json={"title": "a", "text": "b"}).status_code == 403
assert c.post("/api/loadtests", json={"n": 501}).status_code == 400
before = api.FEEDBACK_PATH.stat().st_size if api.FEEDBACK_PATH.exists() else 0
assert c.post("/api/tickets/demo-001/decision", json={"action": "send"}).status_code == 200
assert (api.FEEDBACK_PATH.stat().st_size if api.FEEDBACK_PATH.exists() else 0) == before
"""
        env = {**os.environ, "COPILOT_PUBLIC": "1"}
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", script], cwd=Path(__file__).resolve().parent.parent,
                           env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])


class SecretsTest(unittest.TestCase):
    def setUp(self):
        import importlib.util

        path = Path(__file__).resolve().parent.parent / "scripts" / "check_secrets.py"
        spec = importlib.util.spec_from_file_location("check_secrets", path)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_finds_key_formats(self):
        self.assertTrue(self.m.scan_text("key = 'AIza" + "x" * 35 + "'"))
        self.assertTrue(self.m.scan_text("sk-" + "a" * 30))
        self.assertFalse(self.m.scan_text("LLM_API_KEY=AIza... или нового формата AQ...."))

    def test_finds_env_value_in_base64(self):
        import base64
        import tempfile

        secret = "not-a-real-key-123456"
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(f"LLM_PROVIDER=none\nLLM_API_KEY={secret}\n", encoding="utf-8")
            needles = self.m.env_values(env)
        self.assertEqual(len(needles), 4)
        encoded = base64.b64encode(secret.encode()).decode()
        self.assertEqual(self.m.scan_text(f"key = atob('{encoded}')", needles), ["значение из .env"])
        self.assertFalse(self.m.scan_text("обычный текст", needles))

    def test_forbidden_files(self):
        for name in (".env", ".env.local", "artifacts/kb.pkl", "x/rules.json", "tickets_valid.jsonl"):
            self.assertTrue(self.m.FORBIDDEN_FILES.search(name), name)
        for name in (".env.example", "copilot/rules.py", "demo/tickets.json"):
            self.assertFalse(self.m.FORBIDDEN_FILES.search(name), name)


@unittest.skipUnless(shutil.which("node"), "нужен node")
class SiteTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def data(self):
        text = (self.ROOT / "site" / "data.js").read_text(encoding="utf-8")
        return json.loads(text[len("window.SITE_DATA = "):].rstrip().rstrip(";"))

    def test_page_is_self_contained(self):
        page = (self.ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<script src=", page)
        self.assertNotIn('href="/static', page)
        self.assertIn("window.SITE_DATA", page)
        self.assertIn("Очередь синтетическая", page)

    def test_no_case_data_on_page(self):
        d = self.data()
        results = [it["result"] for it in d["items"]] + list(d["archetypes"].values())
        self.assertTrue(all(not c["quote"] for r in results for c in r["draft"]["citations"]))
        self.assertTrue(all(not c["quote"] for q in d["quick"].values() for x in q for c in x["citations"]))
        self.assertFalse([r for r in results if r["draft"]["template"] == "question_kb"])

    def test_browser_triage_matches_python_rules(self):
        checks = [
            ("report", "задонатил 500 рублей, деньги списались", 0, None, "report.payment", True),
            ("report", "застрял в текстурах", 0, None, "report.help", True),
            ("report", "ау", 0, None, "report.offtopic", False),
            ("complaint", "жб", 0, None, "complaint.invalid", False),
            ("complaint", "он использует aimbot", 1, "Ivan_Petrov", "complaint.cheat", True),
            ("complaint", "оскорбил мать в чате", 1, "Ivan_Petrov", "complaint.insult", True),
        ]
        script = """
const fs = require("fs");
global.window = { fetch: async () => { throw new Error("сеть"); } };
global.performance = { now: () => 0 };
eval(fs.readFileSync("site/data.js", "utf8"));
eval(fs.readFileSync("site/shim.js", "utf8"));
(async () => {
  const out = [];
  for (const [kind, text, images_count, reported_nick] of JSON.parse(process.argv[1])) {
    const t = { kind, images_count, messages: [{ role: "player", text }] };
    if (reported_nick) t.reported_nick = reported_nick;
    const r = await window.fetch("/api/tickets", { method: "POST", body: JSON.stringify(t) });
    out.push((await r.json()).result);
  }
  const ids = ["demo-001"];
  await window.fetch("/api/tickets/bulk", { method: "POST", body: JSON.stringify({ ids, action: "send" }) });
  const q = await (await window.fetch("/api/queue")).json();
  console.log(JSON.stringify({ out, sent: q.items.filter((i) => i.status === "sent").length }));
})();
"""
        r = subprocess.run(["node", "-e", script, json.dumps([c[:4] for c in checks], ensure_ascii=False)], cwd=self.ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        res = json.loads(r.stdout)
        self.assertEqual(res["sent"], 1)
        for c, got in zip(checks, res["out"]):
            kind, text, images, nick, cat, human = c
            self.assertEqual(got["category"], cat, text)
            self.assertEqual(got["needs_human"], human, text)
            self.assertNotIn("__NICK__", json.dumps(got, ensure_ascii=False))
            py = keyword_category(kind, text, bool(images))[0]
            self.assertEqual(got["category"], py, text)
        self.assertIn("Ivan_Petrov", res["out"][4]["draft"]["text"])


class ContractTest(unittest.TestCase):
    """Ответ POST /triage по контракту из документа кейса."""

    def test_case_example(self):
        from fastapi.testclient import TestClient

        from copilot.api import app
        from copilot.triage import CONTRACT_KEYS

        req = {"kind": "complaint", "messages": [{"role": "player", "text": "оскорбил меня и семью в чате, 2.1", "attachments": 2}]}
        r = TestClient(app).post("/triage", json=req)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(tuple(j)[: len(CONTRACT_KEYS)], CONTRACT_KEYS)  # поля контракта первыми и по порядку
        self.assertEqual(j["lang"], "ru")
        self.assertEqual(j["category"], "complaint.insult")
        self.assertIn(j["priority"], ("p0", "p1", "p2", "p3"))
        self.assertIs(j["is_spam_or_duplicate"], False)
        self.assertEqual(j["extracted"]["rule_refs"], ["2.1"])
        self.assertIs(j["extracted"]["has_evidence"], True)  # attachments: 2 — это доказательства
        self.assertIn("nickname", j["extracted"])
        self.assertIn("server", j["extracted"])
        d = j["draft_reply"]
        self.assertEqual(set(d), {"lang", "text", "cited"})
        self.assertIn("2.1", d["cited"])
        known = {rules.short_ref(c) for c in rules.load_points()}
        self.assertTrue(set(d["cited"]) <= known)
        self.assertIsInstance(j["needs_human"], bool)
        self.assertIsInstance(j["confidence"], float)
        self.assertTrue(j["reasons"] and all(isinstance(s, str) for s in j["reasons"]))

    def test_short_ref(self):
        self.assertEqual(rules.short_ref("ОП 2.1"), "2.1")
        self.assertEqual(rules.short_ref("ЖБ 1.2.2"), "ЖБ 1.2.2")
        self.assertEqual(rules.short_ref("GZ 1.1"), "GZ 1.1")

    def test_spam_or_duplicate_flag(self):
        tri = Triage(use_llm=False)
        self.assertTrue(tri(ticket("+", ticket_id="sp1"))["is_spam_or_duplicate"])


class ApiTest(unittest.TestCase):
    def test_post_triage(self):
        from fastapi.testclient import TestClient

        from copilot.api import app

        client = TestClient(app)
        r = client.post("/triage", json={"ticket_id": "api1", "kind": "report",
                                         "messages": [{"role": "player", "text": "застрял под землёй, помогите выбраться"}]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["category"], "report.help")
        self.assertTrue(body["needs_human"])
        self.assertLess(body["latency_ms"], 5000)


if __name__ == "__main__":
    unittest.main()
