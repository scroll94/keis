"""Обучение моделей на слабой разметке.

1. Классификатор категорий: текст игрока -> одна из 14 категорий taxonomy.json.
2. Модель вердикта (только жалобы): текст + признаки -> вероятный вердикт администратора.

Метки берутся из ответов администраторов (copilot/weak.py), но на вход моделям подаётся
только то, что будет известно в момент поступления тикета.
"""
import argparse
import gzip
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import accuracy_score, classification_report, f1_score  # noqa: E402
from sklearn.model_selection import GroupShuffleSplit  # noqa: E402
from sklearn.pipeline import FeatureUnion, Pipeline  # noqa: E402

from copilot.config import ARTIFACTS, MODEL_PATH, TRAIN_PATH, VALID_PATH, VERDICT_PATH  # noqa: E402
from copilot.features import category_input, verdict_input, VERDICTS  # noqa: E402
from copilot.weak import weak_label  # noqa: E402


def load(path: Path):
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_pipe(max_char: int, max_word: int, C: float) -> Pipeline:
    feats = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=max_char, sublinear_tf=True)),
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_features=max_word, sublinear_tf=True, token_pattern=r"(?u)\b\w+\b|<\w+>|\[\w+[^\]]*\]")),
    ])
    return Pipeline([("feats", feats), ("clf", LogisticRegression(C=C, max_iter=1000))])


def fit_eval(name, X, y, groups, pipe, fast=False):
    if fast:
        t0 = time.time()
        pipe.fit(X, y)
        print(f"=== {name}: обучение {time.time() - t0:.0f} с на {len(X)} примерах")
        return pipe
    split = GroupShuffleSplit(n_splits=1, test_size=0.1, random_state=42)
    tr, te = next(split.split(X, y, groups))
    t0 = time.time()
    pipe.fit([X[i] for i in tr], [y[i] for i in tr])
    pred = pipe.predict([X[i] for i in te])
    gold = [y[i] for i in te]
    print(f"\n=== {name}: обучение {time.time() - t0:.0f} с, отложено {len(te)}")
    print(f"accuracy {accuracy_score(gold, pred):.3f}  macro-F1 {f1_score(gold, pred, average='macro'):.3f}")
    print(classification_report(gold, pred, digits=3, zero_division=0))
    # Финальная модель на всех данных
    pipe.fit(X, y)
    return pipe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="одно обучение на всех данных, без отложенной проверки")
    args = ap.parse_args()
    if not TRAIN_PATH.exists():
        print(f"Нет данных для обучения: {TRAIN_PATH}\n"
              f"Укажите папку с данными: make predict DATA=<папка handout> ... "
              f"Пока моделей нет, сервис работает на правилах.", file=sys.stderr)
        sys.exit(0)
    ARTIFACTS.mkdir(exist_ok=True)
    train = load(TRAIN_PATH)
    valid = load(VALID_PATH) if VALID_PATH.exists() and not args.fast else []

    # --- категории ---
    labeled = [(t, weak_label(t)) for t in train]
    labeled = [(t, l) for t, l in labeled if l]
    print("слабая разметка:", len(labeled), "из", len(train), Counter(l for _, l in labeled).most_common())
    X = [category_input(t) for t, _ in labeled]
    y = [l for _, l in labeled]
    g = [t.get("reporter_hash") or t["ticket_id"] for t, _ in labeled]
    cat_pipe = fit_eval("категории", X, y, g, make_pipe(200_000, 100_000, C=4.0), args.fast)

    # Прокси-проверка на валидации: слабая метка по ответу админа против предсказания по тексту игрока
    vl = [(t, weak_label(t)) for t in valid]
    vl = [(t, l) for t, l in vl if l]
    if vl:
        vp = cat_pipe.predict([category_input(t) for t, _ in vl])
        print(f"валидация (прокси, {len(vl)} тикетов со слабой меткой): accuracy {accuracy_score([l for _, l in vl], vp):.3f}")

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(cat_pipe, f)

    # --- вердикт ---
    comp = [t for t in train if t["kind"] == "complaint" and t.get("verdict") in VERDICTS]
    Xv = [verdict_input(t) for t in comp]
    yv = [t["verdict"] for t in comp]
    gv = [t.get("reporter_hash") or t["ticket_id"] for t in comp]
    print("\nвердикты:", Counter(yv).most_common())
    ver_pipe = fit_eval("вердикт", Xv, yv, gv, make_pipe(150_000, 80_000, C=2.0), args.fast)
    vc = [t for t in valid if t["kind"] == "complaint" and t.get("verdict") in VERDICTS]
    if vc:
        pv = ver_pipe.predict([verdict_input(t) for t in vc])
        print(f"валидация вердикта ({len(vc)} жалоб): accuracy {accuracy_score([t['verdict'] for t in vc], pv):.3f}")
    with open(VERDICT_PATH, "wb") as f:
        pickle.dump(ver_pipe, f)
    print("\nсохранено:", MODEL_PATH, VERDICT_PATH)


if __name__ == "__main__":
    main()
