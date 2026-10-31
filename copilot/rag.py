"""Поиск по правилам и по базе прошлых ответов администраторов (RAG).

- Правила: TF-IDF по 227 пунктам rules.json, строится при запуске (доли секунды).
- База знаний: вопросы игроков из репортов и содержательные ответы админов на них.
  Строится скриптом scripts/build_kb.py из тренировочных данных и хранится в artifacts/kb.pkl
  (в репозиторий не попадает: публиковать производные данные запрещено).
"""
import pickle
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from . import rules
from .config import KB_PATH, PUBLIC

# Категория -> пункты, которые taxonomy.json рекомендует для неё
CATEGORY_RULES = {
    "complaint.insult": ["ОП 2.1", "ОП 2.4", "ОП 2.6"],
    "complaint.cheat": ["ОП 5.2"],
    "complaint.dm": ["GZ 1.1", "GZ 1.2", "ОП 5.3", "ОП 5.4"],
    "complaint.scam": ["ОП 4.1", "ОП 4.2"],
    "complaint.rmt_ads": ["ОП 2.3", "ОП 4.4"],
    "complaint.admin": ["ОП 3.4", "ЖБ 1.3.1"],
    "complaint.invalid": ["ЖБ 1.1.2", "ЖБ 1.2.2", "ЖБ 1.2.3", "ЖБ 1.2.7", "ЖБ 1.3.1"],
    "complaint.other": ["ЖБ 1.3.1"],
    "report.help": ["ОП 3.1"],
    "report.complaint": ["ЖБ 1.3.1"],
    "report.account": ["ОП 1.4"],
    "report.offtopic": ["ОП 3.1"],
    "report.question": [],
    "report.payment": [],
}


@lru_cache(maxsize=1)
def _rule_index():
    points = list(rules.load_points().values())
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    mat = vec.fit_transform([f"{p.section_title}. {p.text}" for p in points])
    return points, vec, mat


def search_rules(text: str, category: str, k: int = 4) -> list[rules.Point]:
    """Пункты для черновика: рекомендованные для категории + найденные по тексту."""
    out = [p for p in (rules.get(c) for c in CATEGORY_RULES.get(category, [])) if p]
    points, vec, mat = _rule_index()
    if text.strip():
        sims = linear_kernel(vec.transform([text]), mat)[0]
        for i in sims.argsort()[::-1][: k * 2]:
            if sims[i] < 0.08 or len(out) >= k + len(CATEGORY_RULES.get(category, [])):
                break
            if points[i] not in out:
                out.append(points[i])
    return out


class KnowledgeBase:
    _inst = None

    def __init__(self):
        with open(KB_PATH, "rb") as f:
            data = pickle.load(f)
        self.questions, self.answers = data["questions"], data["answers"]
        self.vec, self.mat = data["vec"], data["mat"]

    @classmethod
    def get(cls):
        if PUBLIC:  # в базе реальные ответы администраторов
            return None
        if cls._inst is None and KB_PATH.exists():
            cls._inst = cls()
        return cls._inst

    def search(self, text: str, k: int = 3, min_sim: float = 0.35) -> list[tuple[str, str, float]]:
        sims = linear_kernel(self.vec.transform([text]), self.mat)[0]
        top = sims.argsort()[::-1][:k]
        return [(self.questions[i], self.answers[i], float(sims[i])) for i in top if sims[i] >= min_sim]
