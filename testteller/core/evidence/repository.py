"""SQLite-backed relational repository for Stage 5 Evidence Graph and Audit Persistence."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import EvidenceRecord, SourceChunk, SourceManifest
from testteller.quality_gate.claim_binding import ClaimEvidenceBinding

logger = logging.getLogger(__name__)


class EvidenceRepository:
    """Relational persistence layer maintaining the canonical evidence graph in SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    repository TEXT,
                    commit_sha TEXT,
                    path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(source_id)
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_chunk_id TEXT NOT NULL,
                    line_start INTEGER,
                    line_end INTEGER,
                    commit_sha TEXT,
                    trust_level TEXT NOT NULL,
                    extractor TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(source_id),
                    FOREIGN KEY(source_chunk_id) REFERENCES chunks(chunk_id)
                );

                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_file TEXT,
                    line_number INTEGER,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claim_evidence_links (
                    claim_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    PRIMARY KEY(claim_id, evidence_id),
                    FOREIGN KEY(claim_id) REFERENCES claims(claim_id),
                    FOREIGN KEY(evidence_id) REFERENCES evidence(evidence_id)
                );

                CREATE TABLE IF NOT EXISTS retrieval_runs (
                    run_id TEXT PRIMARY KEY,
                    plan_id TEXT,
                    collection_name TEXT,
                    hit_count INTEGER,
                    elapsed_ms REAL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id);
                CREATE INDEX IF NOT EXISTS idx_links_evidence ON claim_evidence_links(evidence_id);
                """
            )

    def save_manifest(self, manifest: SourceManifest) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sources
                (source_id, repository, commit_sha, path, file_type, content_hash, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    manifest.source_id,
                    manifest.repository,
                    manifest.commit_sha,
                    manifest.path,
                    manifest.file_type,
                    manifest.content_hash,
                    manifest.indexed_at.isoformat(),
                ),
            )

    def save_chunk(self, chunk: SourceChunk) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO chunks
                (chunk_id, source_id, text, line_start, line_end, content_hash)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.text,
                    chunk.line_start,
                    chunk.line_end,
                    chunk.content_hash,
                ),
            )

    def save_evidence_record(self, record: EvidenceRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO evidence
                (evidence_id, kind, value, source_id, source_chunk_id, line_start, line_end, commit_sha, trust_level, extractor, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.evidence_id,
                    record.kind,
                    record.value,
                    record.source_id,
                    record.source_chunk_id,
                    record.line_start,
                    record.line_end,
                    record.commit_sha,
                    str(record.trust_level.value if hasattr(record.trust_level, "value") else record.trust_level),
                    record.extractor,
                    record.confidence,
                ),
            )

    def save_claim_binding(self, binding: ClaimEvidenceBinding) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO claims
                (claim_id, kind, value, source_file, line_number, status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    binding.claim_id,
                    binding.kind,
                    binding.value,
                    binding.source_file,
                    binding.line_number,
                    binding.status,
                ),
            )
            for ev_id in binding.evidence_ids:
                conn.execute(
                    """INSERT OR REPLACE INTO claim_evidence_links
                    (claim_id, evidence_id, relation, confidence)
                    VALUES (?, ?, ?, ?)""",
                    (binding.claim_id, ev_id, "supported_by", 1.0),
                )

    def get_provenance_trail(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        """Query complete provenance trail: evidence -> chunk -> source."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    e.evidence_id, e.kind, e.value, e.trust_level, e.extractor,
                    c.chunk_id, c.line_start, c.line_end, c.content_hash AS chunk_hash,
                    s.source_id, s.path AS source_path, s.commit_sha, s.repository
                FROM evidence e
                LEFT JOIN chunks c ON e.source_chunk_id = c.chunk_id
                LEFT JOIN sources s ON e.source_id = s.source_id
                WHERE e.evidence_id = ?
                """,
                (evidence_id,),
            ).fetchone()
            if row:
                return dict(row)
        return None
