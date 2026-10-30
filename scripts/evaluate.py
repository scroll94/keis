"""Метрики на валидации (make eval). Пишет artifacts/eval_report.md.

Категорий в валидации нет, поэтому точность категории считается как прокси: сравниваем
предсказание по тексту игрока со слабой меткой, восстановленной из ответа администратора.
"""
import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot import rules  # noqa: E402
from copilot.config import ARTIFACTS, VALID_PATH  # noqa: E402
from copilot.llm import PROMISE, REF_LIKE  # noqa: E402
from copilot.triage import Triage  # noqa: E402
from copilot.weak import weak_label  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-model", action="store_true", help="только правила, для сравнения с моделью")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    tickets = [json.loads(line) for line in open(VALID_PATH, encoding="utf-8") if line.strip()]
    if args.limit:
        tickets = tickets[: args.limit]
    order = sorted(range(len(tickets)), key=lambda i: tickets[i].get("created_at") or "")
    tri = Triage(use_model=not args.no_model, use_llm=not args.no_llm)
    if tri.llm:
        tri.llm.max_wait = max(tri.llm.max_wait, 120)  # оценка, как и пакетный прогон, ждёт квоту провайдера
    preds, lat, waited = [None] * len(tickets), [], 0.0
    for i in order:
        t0 = time.perf_counter()
        preds[i] = tri(tickets[i])
        wait = (preds[i]["draft"].get("llm") or {}).get("wait_ms", 0) / 1000
        waited += wait
        lat.append(time.perf_counter() - t0 - wait)  # задержка обработки без ожидания квоты

    n = len(tickets)
    lines = [f"# Метрики на валидации ({n} тикетов)", ""]

    # Категория (прокси)
    pairs = [(weak_label(t), p["category"], t["kind"]) for t, p in zip(tickets, preds)]
    pairs = [x for x in pairs if x[0]]
    acc = sum(g == p for g, p, _ in pairs) / len(pairs)
    lines += ["## Категория (прокси по ответам админов)", f"- тикетов со слабой меткой: {len(pairs)}", f"- accuracy: **{acc:.3f}**"]
    for kind in ("complaint", "report"):
        sub = [(g, p) for g, p, k in pairs if k == kind]
        if sub:
            lines.append(f"- {kind}: {sum(g == p for g, p in sub) / len(sub):.3f} ({len(sub)})")
    errs = Counter((g, p) for g, p, _ in pairs if g != p).most_common(8)
    lines += ["- частые ошибки (метка → предсказание): " + "; ".join(f"{g} → {p} ({c})" for (g, p), c in errs), ""]

    # Безопасность черновиков
    known = set(rules.load_points())
    bad_cite = sum(any(c["ref"] not in known for c in p["draft"]["citations"]) for p in preds)
    stray_refs = 0
    for p in preds:
        cited = {c["ref"].split(" ", 1)[1] for c in p["draft"]["citations"]}
        stray_refs += any(num not in cited for num in REF_LIKE.findall(p["draft"]["text"]))
    promises = sum(bool(PROMISE.search(p["draft"]["text"])) for p in preds)
    no_cite = sum(not p["draft"]["citations"] for p in preds)
    lines += [
        "## Черновики",
        f"- несуществующих цитат: **{bad_cite}**",
        f"- упоминаний пунктов вне цитат: **{stray_refs}**",
        f"- обещаний (разбан, возврат, наказание): **{promises}**",
        f"- черновиков без цитат: {no_cite} (категории, где правила не нужны: вопросы, помощь, платежи)",
        f"- шаблоны: {dict(Counter(p['draft']['template'] for p in preds).most_common())}",
        "",
    ]

    # Маршрутизация
    human = sum(p["needs_human"] for p in preds)
    lines += [
        "## Маршрутизация",
        f"- needs_human: **{human / n:.1%}** ({human}), автоответ: {1 - human / n:.1%}",
        f"- спам: {sum(p['is_spam'] for p in preds)}, дубли: {sum(p['is_duplicate'] for p in preds)}",
        f"- приоритеты: {dict(sorted(Counter(p['priority'] for p in preds).items()))}",
        f"- языки: {dict(Counter(p['language'] for p in preds).most_common())}",
        "",
    ]

    # Стоимость и задержка
    llm_calls = [p["draft"]["llm"] for p in preds if p["draft"].get("llm")]
    cost = sum(m.get("cost_usd", 0) for m in llm_calls)
    ok = sorted(m["latency_ms"] for m in llm_calls if "tokens_in" in m)
    lat.sort()
    lines += [
        "## Стоимость и задержка",
        f"- вызовов LLM: {len(llm_calls)} ({len(llm_calls) / n:.1%} тикетов), отклонено проверками: "
        f"{sum('rejected' in m for m in llm_calls)}, ошибок: {sum('error' in m for m in llm_calls)}",
        *([f"- ответ LLM: p50 {ok[len(ok) // 2]} мс, p95 {ok[max(0, int(len(ok) * 0.95) - 1)]} мс; "
           f"токенов в среднем {sum(m['tokens_in'] for m in llm_calls if 'tokens_in' in m) // len(ok)} на вход, "
           f"{sum(m['tokens_out'] for m in llm_calls if 'tokens_in' in m) // len(ok)} на выход"] if ok else []),
        *([f"- ожидание квоты провайдера (LLM_RPM): {waited:.0f} с за прогон, в задержку не входит"] if waited else []),
        f"- стоимость: всего ${cost:.4f}, в среднем **${cost / n:.6f}** за тикет (лимит $0.002)",
        f"- задержка: p50 {statistics.median(lat) * 1000:.1f} мс, p95 **{lat[int(n * 0.95) - 1] * 1000:.1f} мс** (лимит 5000 мс)",
        "",
    ]

    # Согласованность с решениями админов по жалобам
    vt = Counter((t.get("verdict"), p["draft"]["template"]) for t, p in zip(tickets, preds) if t["kind"] == "complaint")
    lines += ["## Жалобы: вердикт админа → наш шаблон", *(f"- {v} → {tpl}: {c}" for (v, tpl), c in vt.most_common(12)), ""]

    report = "\n".join(lines)
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "eval_report.md").write_text(report, encoding="utf-8")
    with open(ARTIFACTS / "pred_valid.jsonl", "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(report)


if __name__ == "__main__":
    main()
