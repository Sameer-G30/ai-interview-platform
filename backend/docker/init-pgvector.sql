-- Runs automatically on the *first* container start (docker-entrypoint-initdb.d convention).
-- Enables the pgvector extension so `vector` columns/types are available for SBERT embeddings.
CREATE EXTENSION IF NOT EXISTS vector;
