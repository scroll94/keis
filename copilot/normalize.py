"""Нормализация текста игроков и определение языка."""
import re

# На казахских серверах текст прошёл через cp1251: казахские буквы заменены похожими.
CP1251_KK = str.maketrans({
    "ќ": "қ", "Ќ": "Қ", "ѓ": "ғ", "Ѓ": "Ғ", "ћ": "һ", "Ћ": "Һ",
    "ў": "ұ", "Ў": "Ұ", "ї": "ү", "Ї": "Ү", "є": "ә", "Є": "Ә",
    "ѕ": "ө", "Ѕ": "Ө", "ґ": "ң", "Ґ": "Ң",
})

KK_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
UZ_CYR_LETTERS = set("ўқғҳЎҚҒҲ")
UZ_LATIN_MARKERS = re.compile(
    r"(oʻ|o'|g'|gʻ|\bassalom|\bassalomu|\byordam|\bmenga|\bmeni\b|\bqil|\bnima\b|\bkerak|\bsababsiz|\brahmat|\bhurmat|\bbilan\b|\buchun\b|\bo'yin|\boyin"
    r"|\bkun\b|\bonadan|\bonang|\bsok|\w+(yapti|yapman|yapsan|ibdi|ishdi|moqda|dimi)\b|\bbu\b|\bmen\b|\bsiz\b)",
    re.I,
)
KK_MARKERS = re.compile(r"\b(мені|маған|сәлем|көмек|рахмет|неге|қалай|жоқ|бар ма|керек|ойын|ұрды|өлтірді|сен|біз)\b", re.I)
EN_WORDS = re.compile(r"\b(the|and|to|it|of|in|on|for|with|this|that|was|will|be|help|please|pls|me|my|kill|killed|why|what|is|are|you|player|admin|stuck|can|not)\b", re.I)
ES_WORDS = re.compile(r"\b(ayuda|por favor|hola|que|el|la|los|mi|me|mató|jugador|porque|sin)\b", re.I)
PT_WORDS = re.compile(r"\b(ajuda|por favor|olá|ola|você|voce|meu|minha|não|nao|jogador|matou|sem motivo)\b", re.I)
# Русский транслитом («pomogite», «osk rodni»)
RU_TRANSLIT = re.compile(r"\b(pomogi|pomogite|privet|osk|rodn|zhaloba|zhb|nakaz|igrok|pochemu|ubil|bez prichin|spasibo|admin pomog)\w*", re.I)
TOKEN = re.compile(r"<(url|email|handle|digits)>")


def fix_text(text: str, server_lang: str | None = None) -> str:
    text = text or ""
    if server_lang == "kk" or any(c in text for c in "ќѓћ"):
        text = text.translate(CP1251_KK)
    text = text.replace(" ", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def content_text(text: str) -> str:
    """Текст без служебных токенов и эмодзи — чтобы понять, есть ли содержание."""
    t = TOKEN.sub(" ", text)
    t = re.sub(r"[^\w\s.,!?:;'ʻ’-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def detect_lang(text: str, server_lang: str | None = None) -> str:
    t = content_text(text)
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 2:
        return server_lang if server_lang in ("kk", "uz") else "ru"
    cyr = sum("Ѐ" <= c <= "ӿ" for c in letters)
    if cyr >= len(letters) / 2:
        # «і» есть и в украинском, поэтому одна она — признак казахского только на казахском сервере
        kk_hits = sum(c in KK_LETTERS and c not in "іІ" for c in t) + (server_lang == "kk") * sum(c in "іІ" for c in t)
        if kk_hits >= 2 or KK_MARKERS.search(t) or (server_lang == "kk" and kk_hits >= 1):
            return "kk"
        # Узбекская кириллица: ў/ҳ или несколько қ/ғ (одна буква — скорее опечатка в русском тексте)
        if any(c in "ўҳЎҲ" for c in t) or sum(c in UZ_CYR_LETTERS for c in t) >= 2:
            return "uz"
        return "ru"
    if UZ_LATIN_MARKERS.search(t):
        return "uz"
    if RU_TRANSLIT.search(t):
        return "ru"
    scores = {
        "pt": len(PT_WORDS.findall(t)) + 2 * bool(re.search(r"[ãõç]", t)),
        "es": len(ES_WORDS.findall(t)) + 2 * bool(re.search(r"[ñ¿¡]", t)),
        "en": len(EN_WORDS.findall(t)),
    }
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    if server_lang == "uz":
        return "uz"
    # Короткие латинские «dm», «db», «soft» на СНГ-серверах — это русскоязычные игроки
    return "ru"
