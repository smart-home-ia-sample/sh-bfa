"""Lexical search over the capability catalog — Okapi BM25 (`rank_bm25`) with a
regex tokenizer that strips accents and PT/EN stopwords, reduces each token to a
Portuguese stem (`snowballstemmer`), then expands a small synonym map so
"acende a luz" and "liga a lampada" land on the same document. The BFA only
ranks; the caller decides what to actually use.

One document per catalog item (one per agent skill, one per MCP tool). A source
re-pulled by `catalog.build` replaces all of its documents and the index is
rebuilt (the corpus is a dozen entries — cheap)."""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field

import snowballstemmer
from rank_bm25 import BM25Okapi

from app.models import CatalogItem

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STEMMER = snowballstemmer.stemmer("portuguese")

# Common PT/EN fillers carry no retrieval signal and let a "polite" chit-chat
# query ("olá, tudo bem?") incidentally match example phrases. Dropped from both
# the index and the query.
_STOPWORDS = frozenset(
    """
    a o os as e de da do das dos que em no na nos nas um uma uns umas
    ao aos pra para por com sem se ja la ali aqui isso este esta esse essa
    meu minha seu sua ola oi ei tudo bem obrigado favor pode poderia quero
    the a an to of in on at is are be by for and or with my your this that
    """.split()
)


# Verb/noun groups the ranker should treat as interchangeable. Authored as PT
# surface forms and reduced to stems at import, so the table matches whatever the
# stemmer emits for a live query (some verbs — "abrir/abre/abra" — are irregular
# and never share a stem, hence every inflection is spelled out). Every member of
# a group expands to the whole group at both index and query time.
_SYNONYM_GROUPS = (
    ("ligar", "liga", "ligue", "acender", "acende", "acenda", "ativar"),
    ("desligar", "desliga", "apagar", "apaga", "apague", "escurecer", "escurece", "desativar"),
    ("aumentar", "aumenta", "subir", "elevar"),
    ("diminuir", "diminui", "abaixar", "abaixa", "baixar", "reduzir", "reduz"),
    ("trancar", "tranca", "tranque", "fechar", "fecha", "feche"),
    ("destrancar", "destranca", "destravar", "abrir", "abre", "abra"),
    ("quente", "calor"),
    ("frio", "gelado"),
    ("geladeira", "refrigerador"),
    ("televisao", "televisor", "tv"),
    ("cafeteira", "cafe"),
    ("cortina", "persiana"),
    ("luz", "lampada", "iluminacao"),
    ("alarme", "seguranca"),
)


def _stem(token: str) -> str:
    return _STEMMER.stemWord(token)


def _build_synonyms(groups: tuple[tuple[str, ...], ...]) -> dict[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {}
    for group in groups:
        stems = tuple(dict.fromkeys(_stem(w) for w in group))
        for stem in stems:
            table[stem] = stems
    return table


_SYNONYMS = _build_synonyms(_SYNONYM_GROUPS)


def normalize(text: str) -> list[str]:
    """Lowercase, strip accents (PT examples), split on non-alphanumerics, drop
    stopwords, stem each token (PT), then expand synonym groups. Duplicates are
    collapsed keeping first-seen order."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    raw = (t for t in _TOKEN_RE.findall(stripped.lower()) if t not in _STOPWORDS)
    out: list[str] = []
    seen: set[str] = set()
    for token in raw:
        stem = _stem(token)
        for term in (stem, *_SYNONYMS.get(stem, ())):
            if term not in seen:
                seen.add(term)
                out.append(term)
    return out


@dataclass
class Document:
    kind: str  # "agent" | "tool"
    service: str  # logical service name (DNS), e.g. "security"
    url: str  # base URL to call, e.g. "http://security:8200"
    item: CatalogItem  # the skill / tool this document ranks for
    tokens: list[str] = field(default_factory=list)


class SearchIndex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_service: dict[tuple[str, str], list[Document]] = {}
        self._docs: list[Document] = []
        self._bm25: BM25Okapi | None = None

    def set_source(self, kind: str, service: str, url: str, items: list[CatalogItem]) -> None:
        """Replace everything indexed for (kind, service) with one document per
        catalog item. An agent that announced no skills still gets one bare
        document keyed by its service name so it can be discovered at all."""
        entries = list(items) or [CatalogItem(id=service, name=service)]
        docs = []
        for item in entries:
            fragments = [item.id, item.name, item.description, service] + list(item.tags) + list(item.examples)
            docs.append(Document(kind, service, url, item, _join_tokens(fragments)))
        self._replace((kind, service), docs)

    def retain(self, keys: set[tuple[str, str]]) -> None:
        """Drop any (kind, service) not in `keys` — stale after a refresh."""
        with self._lock:
            for key in list(self._by_service):
                if key not in keys:
                    del self._by_service[key]
            self._rebuild()

    def size(self) -> int:
        return len(self._docs)

    def documents(self) -> list[Document]:
        return list(self._docs)

    def _replace(self, key: tuple[str, str], docs: list[Document]) -> None:
        with self._lock:
            if docs:
                self._by_service[key] = docs
            else:
                self._by_service.pop(key, None)
            self._rebuild()

    def _rebuild(self) -> None:
        self._docs = [d for docs in self._by_service.values() for d in docs]
        self._bm25 = BM25Okapi([d.tokens for d in self._docs]) if self._docs else None

    def query(self, text: str, kinds: set[str], threshold: float) -> list[tuple[Document, float]]:
        """Documents whose query-coverage (raw BM25 / best attainable score for
        this query) is at least `threshold`, highest first. Coverage is 0..1, so
        `threshold` means 'the doc must cover at least this fraction of the
        query's idf mass' — a garbage query like "olá tudo bem" matches nothing."""
        query_tokens = normalize(text)
        with self._lock:
            bm25 = self._bm25
            docs = self._docs
            if not query_tokens or bm25 is None:
                return []
            ceiling = _query_ceiling(bm25, query_tokens)
            if ceiling <= 0:
                return []
            raw = bm25.get_scores(query_tokens)
            hits = []
            for i, doc in enumerate(docs):
                if doc.kind not in kinds:
                    continue
                coverage = float(raw[i]) / ceiling
                if coverage >= threshold:
                    hits.append((doc, coverage))
        hits.sort(key=lambda pair: pair[1], reverse=True)
        return hits


def _query_ceiling(bm25: BM25Okapi, query_tokens: list[str]) -> float:
    """Upper bound on `get_scores` for this query — the score a document that
    covered every query term optimally would get. `f * (k1 + 1) / (f + …)`
    approaches `k1 + 1` as term frequency grows, so per term the cap is
    `idf * (k1 + 1)`, using the same `bm25.idf` the scorer does (clamped to 0 for
    the rare over-common term that Okapi idf drives negative)."""
    return sum(max(bm25.idf.get(t, 0.0), 0.0) for t in set(query_tokens)) * (bm25.k1 + 1)


def _join_tokens(fragments: list[str]) -> list[str]:
    tokens: list[str] = []
    for fragment in fragments:
        tokens += normalize(fragment)
    return tokens
