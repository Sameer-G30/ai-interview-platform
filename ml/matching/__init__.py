"""Job-matching: rank job postings against a resume by embedding similarity, behind one interface.

Two backends implement the same `MatchingBackend` protocol so the product API and a future research
harness can swap the ranking method without touching call sites:

- `SbertBackend` ranks using precomputed pgvector embeddings (cosine similarity over numpy arrays) -
  this is what `/matches` actually uses in production, since embeddings are computed once by the
  `resume_parse` / `posting_embed` workers and simply read back here.
- `TfidfBackend` is the baseline arm required by the plan: it fits a fresh `TfidfVectorizer` over the
  resume text plus every candidate posting's text on the fly and ranks by cosine similarity. It needs
  no persisted embeddings, so it is exercised directly by a unit test rather than wired into the API -
  keeping `/matches` thin while still proving the baseline is callable through the identical interface.
"""

from dataclasses import dataclass  # lightweight value objects passed into both backends
from typing import Protocol  # structural typing so a backend needs no explicit inheritance

from ml.matching.similarity import cosine_similarity  # shared cosine helper, used by SbertBackend

__all__ = ["PostingForMatch", "MatchingBackend", "SbertBackend", "TfidfBackend", "get_backend"]


@dataclass
class PostingForMatch:
    """One job posting's data as needed by a matching backend, decoupled from the ORM model.

    `text` is the concatenated title/description/required_skills string used by `TfidfBackend`
    (and by the worker that computed `embedding` for `SbertBackend`); `embedding` is `None` until
    the `posting_embed` worker has run.
    """

    posting_id: str
    text: str
    embedding: list[float] | None = None


class MatchingBackend(Protocol):
    """Common ranking interface: given one resume and several postings, return a similarity score
    per posting, in the same order as the input list."""

    def rank(
        self,
        resume_text: str,
        resume_embedding: list[float] | None,
        postings: list[PostingForMatch],
    ) -> list[float]:
        """Return one similarity score per posting, aligned by index with `postings`."""
        ...


class SbertBackend:
    """Production backend: cosine similarity between precomputed pgvector embeddings.

    Postings without an embedding yet (worker still running, or embedding failed) score 0.0 rather
    than raising, so a partially-embedded batch degrades gracefully instead of 500ing the request.
    """

    def rank(
        self,
        resume_text: str,  # unused here; SBERT ranking only needs the precomputed vectors
        resume_embedding: list[float] | None,
        postings: list[PostingForMatch],
    ) -> list[float]:
        del resume_text  # not needed once embeddings exist; kept in the signature for interface parity
        if resume_embedding is None:
            return [0.0 for _ in postings]  # caller is expected to guard against this case earlier
        return [
            cosine_similarity(resume_embedding, posting.embedding) if posting.embedding is not None else 0.0
            for posting in postings
        ]


class TfidfBackend:
    """Baseline backend: fits `TfidfVectorizer` over `[resume_text] + posting_texts` on the fly.

    No persistence, no pgvector - this exists purely so the plan's "TF-IDF baseline behind the same
    interface" requirement is satisfiable and testable, not because the product API calls it today.
    """

    def rank(
        self,
        resume_text: str,
        resume_embedding: list[float] | None,
        postings: list[PostingForMatch],
    ) -> list[float]:
        del resume_embedding  # TF-IDF never uses precomputed vectors; it re-derives similarity from raw text
        if not postings:
            return []
        # Deferred import: scikit-learn is a real dependency of this package, but importing it lazily
        # keeps `SbertBackend`-only call sites (the common case) from paying for it at module import time.
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as sk_cosine_similarity

        corpus = [resume_text] + [posting.text for posting in postings]
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform(corpus)
        resume_vector = matrix[0:1]  # row 0 is the resume; keep it 2D for cosine_similarity
        posting_vectors = matrix[1:]  # remaining rows are the postings, same order as `postings`
        scores = sk_cosine_similarity(resume_vector, posting_vectors)[0]
        return [float(score) for score in scores]


def get_backend(name: str = "sbert") -> MatchingBackend:
    """Factory so callers (and tests) can select a backend by name instead of importing the class."""
    if name == "sbert":
        return SbertBackend()
    if name == "tfidf":
        return TfidfBackend()
    raise ValueError(f"unknown matching backend: {name!r}")
