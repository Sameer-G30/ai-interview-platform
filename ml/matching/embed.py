"""SBERT text embeddings used by both resumes and job postings.

`all-MiniLM-L6-v2` is a small (~80MB), fast, 384-dimension sentence-transformers model - more than
enough quality for cosine-similarity ranking at this project's scale, and light enough to run on
CPU inside an ARQ worker without a GPU. The model is lazy-loaded and cached per process so a burst
of `posting_embed`/`resume_parse` jobs only pays the (multi-second) load cost once.
"""

from functools import lru_cache  # memoizes the loaded SentenceTransformer per process

# Model name kept as a module constant so tests/callers can assert on it without a magic string.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Output dimensionality of the default model; also the width of the pgvector columns this phase adds.
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model(model_name: str = DEFAULT_EMBEDDING_MODEL):
    """Load (and cache) the SentenceTransformer once per process; import is deferred to keep this
    module importable (e.g. for type checking or lightweight callers) without pulling in torch."""
    from sentence_transformers import SentenceTransformer  # heavy import; deferred until actually needed

    return SentenceTransformer(model_name)


def embed_texts(texts: list[str], model_name: str = DEFAULT_EMBEDDING_MODEL) -> list[list[float]]:
    """Embed a batch of strings into 384-d vectors using the shared SBERT model.

    Returns plain Python lists (not numpy arrays) so callers can write the result straight into a
    JSON-safe payload or hand it to pgvector's SQLAlchemy type without an extra conversion step.
    Empty input returns an empty list without loading the model at all, so callers (and tests) that
    never touch this path never pay the model-load cost.
    """
    if not texts:
        return []
    model = _get_model(model_name)
    vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=False)
    return [vector.tolist() for vector in vectors]


def embed_text(text: str, model_name: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
    """Convenience wrapper for embedding exactly one string (the common case for a single resume/posting)."""
    return embed_texts([text], model_name=model_name)[0]
