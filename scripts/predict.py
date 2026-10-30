"""make predict IN=tickets.jsonl OUT=pred.jsonl"""
import argparse
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot.triage import Triage  # noqa: E402


def read_jsonl(path: str):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--llm-wait", type=float, default=120,
                    help="сколько секунд можно ждать квоту LLM (LLM_RPM) на одном тикете: пакету важна полнота, а не секунды")
    args = ap.parse_args()

    tickets = read_jsonl(args.inp)
    # Дубли ищутся во времени, поэтому обрабатываем в хронологическом порядке
    order = sorted(range(len(tickets)), key=lambda i: tickets[i].get("created_at") or "")
    tri = Triage(use_model=not args.no_model)
    if tri.llm:
        tri.llm.max_wait = max(tri.llm.max_wait, args.llm_wait)
    results, lat, waited = [None] * len(tickets), [], 0.0
    for i in order:
        t0 = time.perf_counter()
        results[i] = tri(tickets[i])
        # Задержка обработки — без ожидания квоты провайдера: ожидание зависит от тарифа, а не от сервиса
        wait = (results[i]["draft"].get("llm") or {}).get("wait_ms", 0) / 1000
        waited += wait
        lat.append(time.perf_counter() - t0 - wait)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lat.sort()
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else 0
    calls = sum(1 for r in results if r["draft"].get("llm"))
    note = f"; вызовов LLM {calls}, ожидание квоты {waited:.0f} с" if tri.llm else ""
    print(f"{len(results)} тикетов -> {args.out}; p95 = {p95 * 1000:.1f} мс{note}", file=sys.stderr)


if __name__ == "__main__":
    main()
