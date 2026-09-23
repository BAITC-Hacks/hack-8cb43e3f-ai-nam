"""Нормализация текста и семантическое сходство формулировок.

Базовый режим (без ИИ-модели): гибрид TF-IDF по основам слов (стемминг Snowball)
и TF-IDF по символьным n-граммам — устойчив к перефразированию, падежам и
опечаткам OCR. Если в настройках указана embedding-модель, сходство
дополнительно усредняется с косинусной близостью эмбеддингов.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from functools import lru_cache

import numpy as np
import snowballstemmer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_stemmer = snowballstemmer.stemmer("russian")

STOPWORDS = set(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было
    вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь
    опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам
    чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь
    этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой
    хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо
    свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между
    также т ч др пр т.ч. т.п. п пп рамках части числе том соответствии согласно порядке
    общества общество обществом настоящего настоящим положения положением положение компании
    установленном установленные предусмотренном иных иные иной других другие являются является
    """.split()
)

GENERIC_STEMS = {"осуществля", "осуществлен", "обеспеч", "обеспечен", "организ", "организац", "вопрос", "работ"}

_WORD_RE = re.compile(r"[a-zа-яёәғқңөұүһі0-9]+(?:-[a-zа-яёәғқңөұүһі0-9]+)*", re.I)


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[«»\"“”„'`]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;:,")


@lru_cache(maxsize=50000)
def stem(word: str) -> str:
    if re.fullmatch(r"[а-яе]+", word):
        return _stemmer.stemWord(word)
    return word


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    words = _WORD_RE.findall(normalize(text))
    out = []
    for w in words:
        if not keep_stop and (w in STOPWORDS or len(w) < 2):
            continue
        out.append(stem(w))
    return out


def content_stems(text: str) -> set[str]:
    return {t for t in tokens(text) if len(t) > 2 and t not in GENERIC_STEMS and not t.isdigit()}


def _stem_analyzer(text: str) -> list[str]:
    toks = tokens(text)
    return toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


EmbedFn = Callable[[list[str]], list[list[float]] | None]


class Similarity:
    """Матрица сходства между двумя наборами формулировок (0..1)."""

    def __init__(self, embed: EmbedFn | None = None) -> None:
        self.embed = embed
        self.used_embeddings = False

    def matrix(self, a: Sequence[str], b: Sequence[str]) -> np.ndarray:
        if not a or not b:
            return np.zeros((len(a), len(b)))
        corpus = list(a) + list(b)
        word_vec = TfidfVectorizer(analyzer=_stem_analyzer, sublinear_tf=True, min_df=1)
        char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1,
                                   preprocessor=normalize)
        try:
            w = word_vec.fit_transform(corpus)
            s_word = cosine_similarity(w[: len(a)], w[len(a):])
        except ValueError:
            s_word = np.zeros((len(a), len(b)))
        c = char_vec.fit_transform(corpus)
        s_char = cosine_similarity(c[: len(a)], c[len(a):])
        sim = 0.55 * s_word + 0.45 * s_char
        if self.embed is not None:
            try:
                ea = self.embed(list(a))
                eb = self.embed(list(b))
            except Exception:  # noqa: BLE001 - эмбеддинги необязательны
                ea = eb = None
            if ea and eb:
                s_emb = cosine_similarity(np.array(ea), np.array(eb))
                s_emb = np.clip((s_emb - 0.3) / 0.6, 0, 1)  # растягиваем типичный диапазон косинуса
                sim = 0.5 * sim + 0.5 * s_emb
                self.used_embeddings = True
        return np.clip(sim, 0.0, 1.0)

    def self_matrix(self, a: Sequence[str]) -> np.ndarray:
        return self.matrix(a, a)


def name_similarity(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    sa = " ".join(tokens(na))
    sb = " ".join(tokens(nb))
    return max(fuzz.token_set_ratio(sa, sb), fuzz.ratio(na, nb)) / 100.0


def is_generic(text: str, phrases: Sequence[str]) -> bool:
    n = normalize(text)
    for p in phrases:
        pn = normalize(p)
        if pn and (pn in n or name_similarity(pn, n[: len(pn) + 30]) > 0.85):
            return True
    return False


def short(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
