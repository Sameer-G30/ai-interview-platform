"""Pydantic response models for the `/matches` endpoint."""

import uuid  # posting/resume ids

from pydantic import BaseModel  # response models only; GET /matches takes a query param, not a JSON body


class MatchOut(BaseModel):
    """One ranked posting: SBERT cosine similarity to the resume plus its ESCO skill-gap diff."""

    posting_id: uuid.UUID
    title: str
    score: float  # cosine similarity in [-1, 1], practically [0, 1] for SBERT sentence embeddings
    matched_skills: list[str]  # required skills the resume already has (sorted ESCO preferred labels)
    missing_skills: list[str]  # required skills the resume is missing (sorted ESCO preferred labels)


class MatchListOut(BaseModel):
    """Full response for `GET /matches`: which resume was used, plus postings ranked best-first."""

    resume_id: uuid.UUID  # the parsed resume this ranking was computed against
    matches: list[MatchOut]  # sorted by score descending
