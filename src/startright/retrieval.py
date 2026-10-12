"""Hybrid retrieval: vector search + BM25 keyword search, fused, optionally reranked.

Modes (set RETRIEVAL_MODE or pass mode=):
  vector         the Week 4 baseline (embeddings only, no query expansion)
  bm25           keyword search only
  hybrid         vector + BM25 merged with Reciprocal Rank Fusion   (default)
  hybrid_rerank  the hybrid candidates re-scored by a local cross-encoder
  bm25_light     keyword search only and NO embedding model, so it fits a 512 MB
                 server (the Render free tier). Its "score" is lexical coverage.

Everything runs on this computer, so it costs no API tokens. Each hit's "score" stays
the vector cosine similarity, because the refusal guardrail (MIN_SCORE) relies on it.
"""
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from startright import store
from startright.embeddings import embed_texts

MODES = ("vector", "bm25", "hybrid", "hybrid_rerank", "bm25_light")
COSINE_FLOOR = 0.25  # same value as tools.MIN_SCORE
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RRF_K = 60

# Acronyms people type, spelled out the way the Acts and notices write them.
ACRONYMS = {
    "nssa": "National Social Security Authority",
    "zimra": "Zimbabwe Revenue Authority",
    "vat": "value added tax",
    "paye": "pay as you earn",
    "pbc": "private business corporation",
    "cobe": "Companies and Other Business Entities Act",
    "dst": "digital services tax",
    "qpd": "quarterly payment date",
}

STOP_WORDS = frozenset(
    "a an and are as at be by for from how in is it its of on or that the this to "
    "what when which who with do does i my me you your can".split()
)
SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ar", "ed", "es", "s")
TOKEN = re.compile(r"[a-z0-9]+")


# ---------- text handling ----------

def stem(word: str) -> str:
    """A tiny stemmer: registration, registered, register -> regist. Only needs to be
    consistent between the question and the documents, not linguistically perfect."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    for _ in range(2):
        for suffix in SUFFIXES:
            if suffix == "s" and word.endswith("ss"):
                continue
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word = word[: -len(suffix)]
                break
        else:
            break
    if len(word) > 4 and word.endswith("r") and word[-2] in "bcdfgpt":
        word = word[:-1]  # registr(ation/ar) -> regist, matching register(ed)
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in TOKEN.findall(text.lower()) if w not in STOP_WORDS]


def expand_query(query: str) -> str:
    """Append the full name of any acronym in the question."""
    words = set(TOKEN.findall(query.lower()))
    extras = [full for short, full in ACRONYMS.items() if short in words]
    return query + (" " + " ".join(extras) if extras else "")


def scope_matches(source_file: str, patterns: list[str] | None) -> bool:
    """True if the file matches any SQL LIKE pattern ('%' = anything)."""
    if not patterns:
        return True
    for pattern in patterns:
        regex = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch)
                        for ch in pattern)
        if re.fullmatch(regex, source_file):
            return True
    return False


# ---------- BM25 ----------

class BM25Index:
    """Okapi BM25 over a list of texts. Scores reward rare words that appear in a
    chunk, with diminishing returns for repeats and a penalty for very long chunks."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        self.doc_terms: list[frozenset[str]] = []
        for doc_id, text in enumerate(texts):
            tokens = tokenize(text)
            self.lengths.append(len(tokens))
            counts = Counter(tokens)
            self.doc_terms.append(frozenset(counts))
            for term, count in counts.items():
                self.postings[term].append((doc_id, count))
        self.n = len(texts)
        self.avg_length = (sum(self.lengths) / self.n) if self.n else 0.0

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 20,
               allowed: set[int] | None = None) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            idf = self.idf(term)
            for doc_id, tf in self.postings.get(term, ()):
                if allowed is not None and doc_id not in allowed:
                    continue
                norm = 1 - self.b + self.b * self.lengths[doc_id] / (self.avg_length or 1)
                scores[doc_id] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return ranked[:top_k]


@dataclass
class Corpus:
    chunks: list[dict]
    index: BM25Index

    def keyword(self, query: str, top_k: int, scope: list[str] | None) -> list[dict]:
        allowed = None
        if scope:
            allowed = {i for i, c in enumerate(self.chunks)
                       if scope_matches(c["source_file"], scope)}
        hits = []
        for doc_id, score in self.index.search(query, top_k, allowed):
            hits.append({**self.chunks[doc_id], "bm25": score, "doc_id": doc_id})
        return hits

    def lexical(self, query: str, top_k: int, scope: list[str] | None) -> list[dict]:
        """BM25 order, but each hit's "score" is the share of the question's informative
        words (weighted by rarity) that the chunk contains. Words that appear nowhere in
        the documents are ignored, so a business word like "salon" does not sink a hit."""
        terms = {t for t in set(tokenize(query)) if t in self.index.postings}
        if not terms:
            return []
        total = sum(self.index.idf(t) for t in terms)
        hits = self.keyword(query, top_k, scope)
        for hit in hits:
            present = self.index.doc_terms[hit["doc_id"]]
            hit["score"] = sum(self.index.idf(t) for t in terms if t in present) / total
        return hits


_CORPUS: Corpus | None = None


def build_corpus(chunks: list[dict]) -> Corpus:
    return Corpus(chunks, BM25Index([c["content"] for c in chunks]))


def load_corpus(conn) -> Corpus:
    """Build the keyword index once per process (about 3 MB for 2,800 chunks)."""
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = build_corpus(store.load_chunks(conn))
    return _CORPUS


def reset_corpus() -> None:
    global _CORPUS
    _CORPUS = None


# ---------- fusion and reranking ----------

def rrf_fuse(rankings: list[list], k: int = RRF_K) -> list:
    """Reciprocal Rank Fusion: an item near the top of several lists beats an item
    that is first in only one. Needs ranks only, so cosine and BM25 scores (which are
    on different scales) never have to be compared."""
    scores: dict = defaultdict(float)
    first_seen: dict = {}
    for ranking in rankings:
        for position, key in enumerate(ranking, start=1):
            scores[key] += 1.0 / (k + position)
            first_seen.setdefault(key, len(first_seen))
    return sorted(scores, key=lambda key: (-scores[key], first_seen[key]))


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANK_MODEL)


def rerank(query: str, hits: list[dict], top_k: int) -> list[dict]:
    """Re-score (question, chunk) pairs with a cross-encoder, which reads both texts
    together and is usually more accurate than comparing two separate embeddings."""
    if len(hits) <= 1:
        return hits[:top_k]
    scores = _reranker().predict([(query, hit["content"]) for hit in hits])
    ranked = sorted(zip(scores, hits), key=lambda pair: float(pair[0]), reverse=True)
    out = []
    for score, hit in ranked[:top_k]:
        out.append({**hit, "rerank_score": float(score)})
    return out


# ---------- the public entry point ----------

def score_floor(mode: str | None = None) -> float:
    """The lowest "score" a hit may have to be used. Cosine similarity for the embedding
    modes; lexical coverage for bm25_light (tune with LEXICAL_MIN_SCORE)."""
    mode = mode or os.getenv("RETRIEVAL_MODE", "hybrid")
    if mode == "bm25_light":
        return float(os.getenv("LEXICAL_MIN_SCORE", "0.3"))
    return COSINE_FLOOR


def search(query: str, top_k: int = 4, scope: list[str] | None = None,
           mode: str | None = None, candidates: int = 20, conn=None) -> list[dict]:
    mode = mode or os.getenv("RETRIEVAL_MODE", "hybrid")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if mode == "bm25_light" and conn is None and _CORPUS is not None:
        # the keyword index is already in memory: no database connection needed at all
        return _CORPUS.lexical(expand_query(query), top_k, scope)
    own_connection = conn is None
    conn = conn or store.connect()
    try:
        return _search(conn, query, top_k, scope, mode, candidates)
    finally:
        if own_connection:
            conn.close()


def _search(conn, query, top_k, scope, mode, candidates) -> list[dict]:
    text = query if mode == "vector" else expand_query(query)
    if mode == "bm25_light":
        return load_corpus(conn).lexical(text, top_k, scope)
    vector = embed_texts([text])[0]
    if mode == "vector":
        return store.search(conn, vector, top_k, scope)

    corpus = load_corpus(conn)
    keyword_hits = corpus.keyword(text, candidates, scope)
    if mode == "bm25":
        scores = store.scores_for_ids(conn, vector, [h["id"] for h in keyword_hits])
        return [{**h, "score": scores.get(h["id"], 0.0)} for h in keyword_hits[:top_k]]

    vector_hits = store.search(conn, vector, candidates, scope)
    by_id = {h["id"]: h for h in vector_hits}
    missing = [h["id"] for h in keyword_hits if h["id"] not in by_id]
    cosine = store.scores_for_ids(conn, vector, missing)
    for hit in keyword_hits:
        if hit["id"] not in by_id:
            by_id[hit["id"]] = {**hit, "score": cosine.get(hit["id"], 0.0)}

    order = rrf_fuse([[h["id"] for h in vector_hits], [h["id"] for h in keyword_hits]])
    fused = [by_id[i] for i in order]
    if mode == "hybrid_rerank":
        return rerank(query, fused[:candidates], top_k)
    return fused[:top_k]
