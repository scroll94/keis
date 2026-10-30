"""Категория и приоритет.

Два уровня:
1. keyword_category — правила по ключевым словам. Работают всегда и дают слабую разметку для обучения.
2. Model — TF-IDF + логистическая регрессия, обученная на разметке (scripts/train.py).
   Если модели нет, используются только правила.
"""
import pickle
import re

from .config import MODEL_PATH, VERDICT_PATH

KW = {
    # порядок важен: первое совпадение побеждает
    "report.payment": r"донат|задонат|оплат|оплатил|платеж|платёж|пополн|гк не приш|не пришл[иао]? (гк|деньг|коин)|списал|чек|карт[аы] спис|transaction|payment|pul tushmadi",
    "report.account": r"взлом|взломал|украл[иа]? акк|пароль|не могу войти|не могу зайти|нет доступа|потерял акк|пропал[аио]? (машин|дом|бизнес|имущ|деньг|вещ)|пропал[аи]? все|hacked|parol",
    "complaint.admin": r"\bадм(ин)?\w*\b.*(без причин|ни за что|неправ|превыш|бан|мут|кикнул|варн|посадил|наказал)|(бан|мут|варн|деморган|джайл)\w* без причин|не соглас|разбан|сним(ите)? (бан|мут|наказ)|незаслуж|amnist|нохақ|nohaq|снять наказан|обжал",
    "complaint.cheat": r"(?<![а-яё])чит(ы|ер\w*|ак\w*|ом|ами|ов)?(?![а-яё])|софт|soft|(?<![а-яё])аим|aimbot|\baim\b|wh\b|вх\b|через стен|летает|летал|телепорт\w* по карте|спидхак|speed ?hack|макрос|5\.2|сторонн\w* (по|програм)|\bсб\b",
    "complaint.rmt_ads": r"реклам|продает? акк|прода[её]т за реал|за реал|рмт|rmt|тг канал|телеграм|discord\.gg|другой сервер|4\.4|2\.3",
    "complaint.scam": r"скам|scam|обман|кинул на|развел|развёл|мошен|не отдал|не верн|вымога|4\.1|4\.2",
    "complaint.dm": r"(?<![а-яёa-z])(дм|dm|дб|db|sk|ск|тк|tk)(?![а-яёa-z])|без причин\w* убил|убил без|убил меня|убивает|застрелил|сбил|давит|в (зел[её]н|зз|gz)|\bgz\b|\bгз\b|нрп|non ?rp|nonrp|\bрк\b|\bpg\b|атып|o'ldir|oldir|o‘ldir|ol?dirdi|sababsiz|дмз|\bdmz\b|ұрды",
    "complaint.insult": r"оск|оскорб|мат\b|матер|родн|мать|мамк|сем[ьи]|токсич|унижа|расизм|нацизм|национал|угрожа|2\.1|2\.4|2\.6|haqorat|so'k|sok(di|ar|ma)|so‘k|osk|сөкт|сөк|дадан|dadan|onan|онан",
}
REPORT_KW = {
    "report.payment": KW["report.payment"],
    "report.account": KW["report.account"],
    "report.complaint": r"(?<![а-яёa-z])(дм|dm|дб|db|ск|sk|рк|тк|кик)(?![а-яёa-z])|дмят|убива|убил|(?<![а-яё])чит(ы|ер\w*|ак\w*)?(?![а-яё])|софт|оскорб|(?<![а-яё])оск|через стен|мешает|нарушает|скам|обман|сбива|таран",
    "report.help": r"застрял|текстур|вытащ|достань|выбрат|баг|телепорт|тп\b|\btp\b|в воде|под землей|под землёй|провалил|не могу (выйти|выбраться|сесть)|зависл|помогите выбраться|stuck|yordam",
    "report.question": r"\?|как |где |когда |сколько|почему|можно ли|что делать|подскаж|как\b|qanday|qayerda|қалай|қайда|how|where",
}
EMPTY_REPORT = re.compile(r"^\W*(\+|\.+|ау+|а+|э+|алл?о+|привет\w*|хай|hi|hello|ку|помогите|помоги|памаги\w*|хелп\w*|help\w*|админ\w*|адм|yordam\w*|\?+|\d+)?\W*$", re.I)
INVALID_COMPLAINT = re.compile(r"^\W*(жб|жалоба|вот|вот он|он|\.+|\+|-|хз|нарушение|наказать|накажите)?\W*$", re.I)

PRIORITY_BY_CATEGORY = {
    "report.account": "p0", "report.payment": "p0",
    "complaint.cheat": "p1", "complaint.scam": "p1", "complaint.rmt_ads": "p1",
    "complaint.insult": "p2", "complaint.dm": "p2", "complaint.admin": "p2",
    "complaint.other": "p2", "report.complaint": "p2", "report.help": "p2",
    "complaint.invalid": "p3", "report.question": "p3", "report.offtopic": "p3",
}
P0_KW = re.compile(r"угрож\w* (в реал|убить|найти|адрес)|найду тебя|суицид|самоуб|покончу|массов\w* баг|все сервера|сервер упал|не работает сервер|дудос|ddos", re.I)


def keyword_category(kind: str, text: str, has_evidence: bool = True) -> tuple[str, float, str]:
    """Возвращает (категория, уверенность, причина)."""
    t = text.lower()
    if kind == "report":
        if EMPTY_REPORT.match(t):
            return "report.offtopic", 0.9, "пустое или служебное сообщение"
        for cat, pat in REPORT_KW.items():
            m = re.search(pat, t)
            if m:
                return cat, 0.7, f"ключевое слово «{m.group(0).strip()}»"
        return "report.question" if len(t) > 25 else "report.offtopic", 0.4, "нет явных признаков"
    if INVALID_COMPLAINT.match(t) and not has_evidence:
        return "complaint.invalid", 0.85, "нет описания и доказательств"
    for cat, pat in KW.items():
        if cat.startswith("report."):
            continue
        m = re.search(pat, t)
        if m:
            return cat, 0.7, f"ключевое слово «{m.group(0).strip()}»"
    for cat in ("report.payment", "report.account"):
        if re.search(KW[cat], t):
            # Платёж/взлом в жалобе: категория жалобы «другое», но эскалация к человеку
            return "complaint.other", 0.5, "жалоба с темой аккаунта или платежа"
    if not has_evidence and len(t) < 15:
        return "complaint.invalid", 0.6, "короткая жалоба без доказательств"
    return "complaint.other", 0.4, "нет явных признаков"


def priority(category: str, text: str, has_evidence: bool) -> tuple[str, str]:
    if P0_KW.search(text):
        return "p0", "угрозы вне игры или массовая проблема"
    p = PRIORITY_BY_CATEGORY.get(category, "p2")
    if category.startswith("complaint.") and category != "complaint.invalid" and not has_evidence:
        return "p3", "жалоба без доказательств"
    if category in ("complaint.insult", "complaint.dm") and has_evidence:
        return "p2", "нарушение с доказательствами"
    return p, f"приоритет категории {category}"


class Model:
    _inst = None

    def __init__(self):
        with open(MODEL_PATH, "rb") as f:
            self.pipe = pickle.load(f)

    @classmethod
    def get(cls):
        if cls._inst is None and MODEL_PATH.exists():
            cls._inst = cls()
        return cls._inst

    def predict(self, x: str, kind: str) -> tuple[str, float]:
        """x — вход из features.category_input; выбираем лучшую категорию нужного вида."""
        proba = self.pipe.predict_proba([x])[0]
        classes = self.pipe.classes_
        # Только категории подходящего вида
        best = max((p, c) for p, c in zip(proba, classes) if c.startswith(kind))
        return best[1], float(best[0])


class VerdictModel:
    """Вероятный вердикт администратора по жалобе — подсказка для черновика, не решение."""

    _inst = None

    def __init__(self):
        with open(VERDICT_PATH, "rb") as f:
            self.pipe = pickle.load(f)

    @classmethod
    def get(cls):
        if cls._inst is None and VERDICT_PATH.exists():
            cls._inst = cls()
        return cls._inst

    def predict(self, x: str) -> tuple[str, float]:
        proba = self.pipe.predict_proba([x])[0]
        i = int(proba.argmax())
        return str(self.pipe.classes_[i]), float(proba[i])
