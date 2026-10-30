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
    args = ap.parse_args()

    tickets = read_jsonl(args.inp)
    # Дубли ищутся во времени, поэтому обрабатываем в хронологическом порядке
    order = sorted(range(len(tickets)), key=lambda i: tickets[i].get("created_at") or "")
    tri = Triage(use_model=not args.no_model)
    results, lat = [None] * len(tickets), []
    for i in order:
        t0 = time.perf_counter()
        results[i] = tri(tickets[i])
        lat.append(time.perf_counter() - t0)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lat.sort()
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else 0
    print(f"{len(results)} тикетов -> {args.out}; p95 = {p95 * 1000:.1f} мс", file=sys.stderr)


if __name__ == "__main__":
    main()
