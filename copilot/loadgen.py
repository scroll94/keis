"""Нагрузочная проверка POST /triage.

Запускается отдельным процессом, чтобы генератор запросов не отнимал процессор у сервиса и цифры
были честными. Прогресс раз в четверть секунды пишется в JSON-файл, его читает интерфейс.

    python -m copilot.loadgen --url http://localhost:8000/triage --tickets t.json --n 500 --concurrency 20 --out p.json
"""
import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

# Границы корзин гистограммы задержки, мс
BUCKETS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]


def summarize(latencies: list[float], total: int, errors: int, elapsed: float, llm: dict, finished: bool,
              slowest: list | None = None) -> dict:
    lat = sorted(latencies)
    q = lambda p: round(lat[min(len(lat) - 1, int(len(lat) * p))], 1) if lat else None
    hist = [0] * (len(BUCKETS) + 1)
    for x in lat:
        hist[next((i for i, b in enumerate(BUCKETS) if x <= b), len(BUCKETS))] += 1
    return {
        "total": total, "done": len(lat), "errors": errors, "finished": finished,
        "elapsed_s": round(elapsed, 2), "rps": round(len(lat) / elapsed, 1) if elapsed > 0 else 0,
        "p50_ms": q(0.5), "p95_ms": q(0.95), "p99_ms": q(0.99), "max_ms": round(lat[-1], 1) if lat else None,
        "buckets_ms": BUCKETS, "hist": hist, "llm": llm,
        # Самые долгие запросы и почему: тикет, полное время, время разбора на сервере, что было с LLM
        "slowest": sorted(slowest or [], key=lambda s: -s["ms"])[:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--tickets", required=True, help="JSON-массив тикетов; повторяются по кругу до n")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.tickets, encoding="utf-8") as f:
        tickets = json.load(f)
    lock = threading.Lock()
    latencies: list[float] = []
    slowest: list[dict] = []
    errors = 0
    llm = {"calls": 0, "accepted": 0, "limited": 0, "failed": 0}
    started = time.perf_counter()
    run_id = f"load{int(time.time()) % 100000}"
    done = threading.Event()

    def write(finished=False):
        with lock:
            snap = summarize(list(latencies), args.n, errors, time.perf_counter() - started, dict(llm), finished, list(slowest))
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        os.replace(tmp, args.out)

    def writer():
        while not done.wait(0.25):
            write()

    def one(client: httpx.Client, i: int):
        nonlocal errors
        src = tickets[i % len(tickets)]
        t = dict(src)
        t["ticket_id"] = f"{run_id}-{i + 1}"  # свои номера на каждый прогон: повторный прогон — не повтор того же тикета
        t0 = time.perf_counter()
        ok, meta, server_ms = False, None, None
        try:
            r = client.post(args.url, json=t)
            ok = r.status_code == 200
            if ok:
                body = r.json()
                meta, server_ms = body["draft"].get("llm"), body.get("latency_ms")
        except Exception:
            pass
        ms = (time.perf_counter() - t0) * 1000
        with lock:
            latencies.append(ms)
            errors += not ok
            if len(slowest) < 5 or ms > min(s["ms"] for s in slowest):
                llm_note = None if not meta else (meta.get("error") or meta.get("rejected") or f"LLM {round(meta.get('latency_ms', 0))} мс")
                slowest.append({"ms": round(ms, 1), "server_ms": server_ms, "ticket": str(src.get("ticket_id")),
                                "llm": llm_note, "ok": ok})
                slowest.sort(key=lambda s: -s["ms"])
                del slowest[5:]
            if meta:
                llm["calls"] += 1
                err = meta.get("error") or ""
                if not err and "rejected" not in meta:
                    llm["accepted"] += 1
                elif "лимит" in err:
                    llm["limited"] += 1
                else:
                    llm["failed"] += 1

    threading.Thread(target=writer, daemon=True).start()
    with httpx.Client(timeout=30) as client, ThreadPoolExecutor(args.concurrency) as pool:
        list(pool.map(lambda i: one(client, i), range(args.n)))
    done.set()
    write(finished=True)


if __name__ == "__main__":
    main()
