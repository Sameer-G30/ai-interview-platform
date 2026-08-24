"""Unit tests for `ml/matching`: cosine similarity, skill-gap diff, and both ranking backends.

No live Postgres/Redis needed here (unlike the other test modules) - `SbertBackend`/`TfidfBackend`
are pure functions over plain lists/dataclasses, so these run fast and offline. The one exception is
`test_embed_texts_with_real_model`, which downloads/loads the actual `all-MiniLM-L6-v2` weights and
is skipped (not failed) when that isn't possible offline, per the plan's instruction that a single
real-model smoke test is fine as long as it doesn't break CI/offline dev.
"""

import pytest  # pytest.mark.skip / raises
from ml.matching import PostingForMatch, SbertBackend, TfidfBackend, get_backend
from ml.matching.similarity import cosine_similarity, skill_gap


def test_cosine_similarity_identical_vectors_is_one() -> None:
    vector = [1.0, 2.0, 3.0]
    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors_is_negative_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_is_zero_not_a_crash() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_similarity_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        cosine_similarity([1.0, 2.0], [1.0])


def test_skill_gap_splits_matched_and_missing_case_insensitively() -> None:
    matched, missing = skill_gap(
        resume_skills=["python", "Docker", "SQL"],
        required_skills=["Python", "Kubernetes", "SQL"],
    )
    assert matched == ["Python", "SQL"]  # required's casing is preserved
    assert missing == ["Kubernetes"]


def test_skill_gap_empty_required_is_no_gap() -> None:
    matched, missing = skill_gap(resume_skills=["Python"], required_skills=[])
    assert matched == []
    assert missing == []


def test_sbert_backend_ranks_by_cosine_similarity() -> None:
    resume_embedding = [1.0, 0.0, 0.0]
    postings = [
        PostingForMatch(posting_id="close", text="close", embedding=[0.9, 0.1, 0.0]),
        PostingForMatch(posting_id="far", text="far", embedding=[0.0, 1.0, 0.0]),
        PostingForMatch(posting_id="unembedded", text="none", embedding=None),
    ]
    scores = SbertBackend().rank(resume_text="ignored", resume_embedding=resume_embedding, postings=postings)
    assert scores[0] > scores[1]  # "close" is more aligned with the resume vector than "far"
    assert scores[2] == 0.0  # missing embedding degrades to 0.0 rather than raising


def test_sbert_backend_with_no_resume_embedding_scores_everything_zero() -> None:
    postings = [PostingForMatch(posting_id="p1", text="x", embedding=[1.0, 0.0])]
    scores = SbertBackend().rank(resume_text="ignored", resume_embedding=None, postings=postings)
    assert scores == [0.0]


def test_tfidf_backend_ranks_shared_vocabulary_higher() -> None:
    """The baseline arm, called directly through the same MatchingBackend interface as SbertBackend."""
    resume_text = "experienced python backend engineer building rest apis with postgresql and docker"
    postings = [
        PostingForMatch(
            posting_id="close",
            text="python backend engineer building rest apis with postgresql and docker experience",
        ),
        PostingForMatch(posting_id="far", text="marine biologist studying coral reef ecosystems"),
    ]
    scores = TfidfBackend().rank(resume_text=resume_text, resume_embedding=None, postings=postings)
    assert len(scores) == 2
    assert scores[0] > scores[1]


def test_tfidf_backend_handles_empty_postings_list() -> None:
    assert TfidfBackend().rank(resume_text="python", resume_embedding=None, postings=[]) == []


def test_get_backend_factory_returns_matching_types() -> None:
    assert isinstance(get_backend("sbert"), SbertBackend)
    assert isinstance(get_backend("tfidf"), TfidfBackend)
    with pytest.raises(ValueError, match="unknown matching backend"):
        get_backend("something-else")


def test_embed_texts_with_real_model() -> None:
    """One real-MiniLM smoke test: skipped (not failed) if the model cannot be loaded offline."""
    try:
        from ml.matching.embed import EMBEDDING_DIM, embed_texts
    except ImportError as exc:  # pragma: no cover - sentence-transformers is a hard dependency today
        pytest.skip(f"sentence-transformers not importable: {exc}")

    try:
        vectors = embed_texts(["python backend engineer", "marine biologist"])
    except Exception as exc:  # any load/download failure means "skip", not "fail the suite"
        pytest.skip(f"could not load all-MiniLM-L6-v2 (likely offline, no cached weights): {exc}")

    assert len(vectors) == 2
    assert len(vectors[0]) == EMBEDDING_DIM
    # Two unrelated sentences should not be near-identical vectors.
    assert cosine_similarity(vectors[0], vectors[1]) < 0.9
