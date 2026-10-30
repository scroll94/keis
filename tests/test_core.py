"""Проверки ключевых гарантий сервиса. Запуск: python -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot import drafts, rules  # noqa: E402
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


class LLMGuardTest(unittest.TestCase):
    def setUp(self):
        self.llm = object.__new__(LLM)
        self.llm.provider, self.llm.model, self.llm.price_in, self.llm.price_out = "fake", "fake", 0.1, 0.5
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
