"""SQLite-backed deterministic index kept alongside a Chroma collection."""

import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .models import LocalIndexEntry, LocalSearchResult, MatchType, QueryAnalysis, RetrievalItem
from .path_normalizer import api_key, normalize_api_path
from .retrieval_patterns import (
    API_PATH_PATTERN, DATA_TESTID_PATTERN, ENV_EXCLUDE_WORDS, ENV_GETENV_PATTERN,
    ENV_PROCESS_PATTERN, ENV_TEMPLATE_PATTERN, FRAMEWORKS, HTTP_METHOD_PATTERN,
    JS_TS_FUNCTION_PATTERN, PYTHON_CLASS_PATTERN, PYTHON_FUNCTION_PATTERN,
    QUALIFIED_SYMBOL_PATTERN, TEST_ID_PATTERN, TOKEN_PATTERN,
)

logger = logging.getLogger(__name__)


class LocalIndex:
    """Persistent local index for exact entities and lightweight keyword candidates."""

    def __init__(self, persist_directory: str):
        os.makedirs(persist_directory, exist_ok=True)
        self.db_path = os.path.join(persist_directory, "local_retrieval.sqlite3")
        self._initialize_schema()

    @contextmanager
    def _connect(self):
        """Commit or roll back every operation and always close SQLite handles on Windows."""
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

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS local_documents (
                    collection_name TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_id TEXT DEFAULT '',
                    commit_sha TEXT DEFAULT '',
                    line_start INTEGER DEFAULT 0,
                    line_end INTEGER DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (collection_name, chunk_id)
                );
                CREATE TABLE IF NOT EXISTS local_terms (
                    collection_name TEXT NOT NULL,
                    term TEXT NOT NULL,
                    term_type TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    PRIMARY KEY (collection_name, term, term_type, chunk_id)
                );
                CREATE INDEX IF NOT EXISTS idx_local_documents_source
                    ON local_documents(collection_name, source);
                CREATE INDEX IF NOT EXISTS idx_local_terms_lookup
                    ON local_terms(collection_name, term_type, term);
                CREATE TABLE IF NOT EXISTS index_operations (
                    operation_id TEXT PRIMARY KEY,
                    collection_name TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Ensure columns exist if table was created in an earlier schema version
            existing_cols = {row[1] for row in connection.execute("PRAGMA table_info(local_documents)").fetchall()}
            for col, col_type in [
                ("source_id", "TEXT DEFAULT ''"),
                ("commit_sha", "TEXT DEFAULT ''"),
                ("line_start", "INTEGER DEFAULT 0"),
                ("line_end", "INTEGER DEFAULT 0"),
            ]:
                if col not in existing_cols:
                    try:
                        connection.execute(f"ALTER TABLE local_documents ADD COLUMN {col} {col_type}")
                    except Exception:
                        pass

    def add_documents(
        self, documents: list[str], metadatas: Optional[list[dict]], ids: list[str], collection_name: str
    ) -> None:
        """Upsert chunks after Chroma accepts them; repeated imports are idempotent."""
        metadata_list = metadatas or [{} for _ in documents]
        entries = [
            self._build_entry(document, metadata_list[index] or {}, str(ids[index]), collection_name)
            for index, document in enumerate(documents)
        ]
        now = datetime.now(timezone.utc).isoformat()
        operation_id = hashlib.sha256(f"{collection_name}:{now}:{len(entries)}".encode()).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO index_operations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (operation_id, collection_name, "upsert", "PENDING", str(len(entries)), now, now),
            )
            for entry in entries:
                old = connection.execute(
                    "SELECT content_hash, version FROM local_documents WHERE collection_name=? AND chunk_id=?",
                    (collection_name, entry.chunk_id),
                ).fetchone()
                if old and old["content_hash"] == entry.content_hash:
                    continue
                version = (old["version"] + 1) if old else 1
                connection.execute(
                    "DELETE FROM local_terms WHERE collection_name=? AND chunk_id=?", (collection_name, entry.chunk_id)
                )
                connection.execute(
                    """INSERT OR REPLACE INTO local_documents
                    (collection_name, chunk_id, document_id, source, content, content_type, content_hash,
                     source_id, commit_sha, line_start, line_end, version, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (collection_name, entry.chunk_id, entry.document_id, entry.source, entry.content,
                     entry.content_type, entry.content_hash, entry.source_id, entry.commit_sha,
                     entry.line_start, entry.line_end, version, now),
                )
                for term, term_type in self._terms_for_entry(entry):
                    connection.execute(
                        "INSERT OR IGNORE INTO local_terms VALUES (?, ?, ?, ?)",
                        (collection_name, term.lower(), term_type, entry.chunk_id),
                    )
            connection.execute(
                "UPDATE index_operations SET status='COMPLETED', updated_at=? WHERE operation_id=?", (now, operation_id)
            )

    def clear(self, collection_name: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM local_terms WHERE collection_name=?", (collection_name,))
            connection.execute("DELETE FROM local_documents WHERE collection_name=?", (collection_name,))
            connection.execute("DELETE FROM index_operations WHERE collection_name=?", (collection_name,))

    def search(self, analysis: QueryAnalysis, collection_name: str, limit: int = 5) -> LocalSearchResult:
        scores: dict[str, tuple[float, list[str]]] = {}
        exact_entity_requested = bool(analysis.test_ids or analysis.api_paths or analysis.symbols or analysis.config_keys)

        def collect(terms: Iterable[str], term_type: str, score: float, exact: bool = False) -> bool:
            found = False
            for term in terms:
                rows = self._find_terms(collection_name, term.lower(), term_type)
                for row in rows:
                    found = True
                    current_score, rules = scores.get(row["chunk_id"], (0.0, []))
                    scores[row["chunk_id"]] = (max(current_score, score), rules + [f"{term_type}:{term}"])
            return found

        exact_found = False
        exact_found |= collect(analysis.test_ids, "test_id", 1.00, True)
        if analysis.api_paths:
            if analysis.api_methods:
                exact_found |= collect(
                    [api_key(method, path) for method in analysis.api_methods for path in analysis.api_paths],
                    "api_key", 1.00, True,
                )
            exact_found |= collect(analysis.api_paths, "api_path", 0.88, True)
        exact_found |= collect(analysis.symbols, "qualified_symbol", 0.98, True)
        exact_found |= collect(analysis.symbols, "symbol", 0.90, True)
        exact_found |= collect(analysis.config_keys, "config_key", 0.90, True)
        for keyword in analysis.keywords:
            collect([keyword], "keyword", 0.45)

        if not scores:
            return LocalSearchResult(exact_entity_requested=exact_entity_requested)
        rows = self._get_documents(collection_name, scores.keys())
        items = []
        for row in rows:
            score, rules = scores[row["chunk_id"]]
            row_keys = row.keys() if hasattr(row, "keys") else []
            meta = {
                "type": row["content_type"],
                "source_id": row["source_id"] if "source_id" in row_keys else "",
                "commit_sha": row["commit_sha"] if "commit_sha" in row_keys else "",
                "line_start": row["line_start"] if "line_start" in row_keys else 0,
                "line_end": row["line_end"] if "line_end" in row_keys else 0,
                "content_hash": row["content_hash"] if "content_hash" in row_keys else "",
            }
            items.append(RetrievalItem(
                document_id=row["document_id"], chunk_id=row["chunk_id"], source=row["source"],
                content=row["content"], metadata=meta, local_score=score,
                match_rules=list(dict.fromkeys(rules)),
            ))
        items.sort(key=lambda item: item.local_score or 0.0, reverse=True)
        items = items[:limit]
        match_type = MatchType.EXACT if exact_found else MatchType.PARTIAL
        unique = match_type == MatchType.EXACT and len(items) == 1
        for rank, item in enumerate(items, 1):
            item.local_rank = rank
        return LocalSearchResult(items=items, match_type=match_type, unique=unique,
                                 exact_entity_requested=exact_entity_requested)

    def _find_terms(self, collection_name: str, term: str, term_type: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                "SELECT chunk_id FROM local_terms WHERE collection_name=? AND term=? AND term_type=?",
                (collection_name, term, term_type),
            ).fetchall()

    def _get_documents(self, collection_name: str, chunk_ids: Iterable[str]) -> list[sqlite3.Row]:
        ids = list(chunk_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as connection:
            return connection.execute(
                f"SELECT * FROM local_documents WHERE collection_name=? AND chunk_id IN ({placeholders})",
                [collection_name, *ids],
            ).fetchall()

    def _build_entry(self, content: str, metadata: dict[str, Any], chunk_id: str, collection_name: str) -> LocalIndexEntry:
        source = str(metadata.get("source", "unknown"))
        content_type = str(metadata.get("type", metadata.get("document_type", "document")))
        source_id = str(metadata.get("source_id", ""))
        commit_sha = str(metadata.get("commit_sha", ""))
        try:
            line_start = int(metadata.get("line_start", 0))
            line_end = int(metadata.get("line_end", 0))
        except (ValueError, TypeError):
            line_start, line_end = 0, 0
        if not source_id and source != "unknown":
            from ..evidence.ids import compute_source_id
            source_id = compute_source_id(metadata.get("repository"), commit_sha, source)

        methods = [method.upper() for method in HTTP_METHOD_PATTERN.findall(content)]
        paths = list(dict.fromkeys(normalize_api_path(path) for path in API_PATH_PATTERN.findall(content)))
        symbols = PYTHON_CLASS_PATTERN.findall(content) + PYTHON_FUNCTION_PATTERN.findall(content) + JS_TS_FUNCTION_PATTERN.findall(content)
        qualified = QUALIFIED_SYMBOL_PATTERN.findall(content)
        config_keys = self._extract_config_keys(content)
        keywords = self._extract_keywords(content)
        return LocalIndexEntry(
            collection_name=collection_name, document_id=chunk_id, chunk_id=chunk_id, source=source,
            content=content, content_type=content_type, keywords=keywords, symbols=list(dict.fromkeys(symbols)),
            qualified_symbols=list(dict.fromkeys(qualified)), api_paths=paths, api_methods=methods,
            api_keys=[api_key(method, path) for method in methods for path in paths],
            test_ids=[item.upper() for item in TEST_ID_PATTERN.findall(content)],
            selectors=DATA_TESTID_PATTERN.findall(content), config_keys=config_keys,
            frameworks=[token.lower() for token in keywords if token.lower() in FRAMEWORKS],
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_id=source_id, commit_sha=commit_sha, line_start=line_start, line_end=line_end,
        )

    def _terms_for_entry(self, entry: LocalIndexEntry) -> Iterable[tuple[str, str]]:
        groups = {
            "keyword": entry.keywords, "symbol": entry.symbols, "qualified_symbol": entry.qualified_symbols,
            "api_path": entry.api_paths, "api_key": entry.api_keys, "test_id": entry.test_ids,
            "selector": entry.selectors, "config_key": entry.config_keys, "framework": entry.frameworks,
        }
        for term_type, terms in groups.items():
            for term in terms:
                if term:
                    yield term, term_type

    def _extract_config_keys(self, content: str) -> list[str]:
        values = ENV_GETENV_PATTERN.findall(content) + ENV_PROCESS_PATTERN.findall(content) + ENV_TEMPLATE_PATTERN.findall(content)
        return list(dict.fromkeys(value for value in values if value not in ENV_EXCLUDE_WORDS))

    def _extract_keywords(self, content: str) -> list[str]:
        tokens = [token.lower() for token in TOKEN_PATTERN.findall(content)]
        return list(dict.fromkeys(tokens))
