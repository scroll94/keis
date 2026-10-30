"""База знаний для RAG: вопросы игроков из репортов и содержательные ответы администраторов."""
import gzip
import json
import pickle
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

from copilot.config import ARTIFACTS, KB_PATH, TRAIN_PATH  # noqa: E402
from copilot.normalize import content_text  # noqa: E402
from copilot.weak import player_text, weak_label  # noqa: E402

GREETING = re.compile(r"^\W*(приветствую|здравствуйте|добрый (день|вечер)|assalomu? ?a?l?a?ykum|сәлеметсіз бе)\W*", re.I)
TEMPLATE = re.compile(
    r"уточните|слежу|ожидайте|спешу|спешит|в пути|помочь|помощь|приятной игры|нет информации|не владеем|"
    r"узнайте самостоятельно|передал|работаю|оффтоп|не оказываем|не предоставляем|телепорт|жалоб|мут репорта|"
    r"лечу|бегу|иду\b|kuzat|yordam",
    re.I,
)
NICK = re.compile(r"\b[A-Z][a-z]+_[A-Z][a-z]+\d*\b")


def main():
    questions, answers, seen = [], [], set()
    with gzip.open(TRAIN_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if t["kind"] != "report" or weak_label(t) != "report.question":
                continue
            q = content_text(player_text(t))
            adm = " ".join(m["text"] for m in t["messages"] if m["role"] == "admin")
            a = GREETING.sub("", adm).strip()
            if len(q) < 12 or len(a) < 2 or TEMPLATE.search(a) or NICK.search(a):
                continue
            key = q.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            questions.append(q[:300])
            answers.append(a[:300])
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
    mat = vec.fit_transform(questions)
    ARTIFACTS.mkdir(exist_ok=True)
    with open(KB_PATH, "wb") as f:
        pickle.dump({"questions": questions, "answers": answers, "vec": vec, "mat": mat}, f)
    print(f"база знаний: {len(questions)} пар вопрос-ответ -> {KB_PATH}")


if __name__ == "__main__":
    main()
