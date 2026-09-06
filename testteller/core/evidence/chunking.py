"""Line-aware chunking for documents and code, producing SourceChunk instances."""

from __future__ import annotations

import ast
from typing import List, Optional
from .ids import compute_chunk_id, compute_content_hash
from .models import SourceChunk


class LineAwareChunker:
    """Chunks documents or source files while tracking exact line ranges and content hashes."""

    def __init__(
        self,
        max_lines_per_chunk: int = 60,
        overlap_lines: int = 5,
    ):
        self.max_lines_per_chunk = max_lines_per_chunk
        self.overlap_lines = max(0, min(overlap_lines, max_lines_per_chunk // 2))

    def chunk_text(
        self,
        text: str,
        source_id: str,
        file_type: str = "text",
    ) -> List[SourceChunk]:
        """Split text into line-aware SourceChunk instances."""
        if not text:
            return []

        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        if total_lines == 0:
            return []

        if file_type == "python":
            ast_chunks = self._chunk_python_ast(text, lines, source_id)
            if ast_chunks:
                return ast_chunks

        # Standard sliding window chunker preserving line numbers (1-indexed)
        chunks: List[SourceChunk] = []
        start_idx = 0

        while start_idx < total_lines:
            end_idx = min(start_idx + self.max_lines_per_chunk, total_lines)
            chunk_lines = lines[start_idx:end_idx]
            chunk_text = "".join(chunk_lines)

            line_start = start_idx + 1
            line_end = end_idx
            content_hash = compute_content_hash(chunk_text)
            chunk_id = compute_chunk_id(source_id, line_start, line_end, content_hash)

            chunks.append(
                SourceChunk(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    text=chunk_text,
                    line_start=line_start,
                    line_end=line_end,
                    content_hash=content_hash,
                    metadata={"file_type": file_type},
                )
            )

            if end_idx >= total_lines:
                break
            start_idx += (self.max_lines_per_chunk - self.overlap_lines)

        return chunks

    def _chunk_python_ast(
        self,
        text: str,
        lines: List[str],
        source_id: str,
    ) -> Optional[List[SourceChunk]]:
        """Attempt to split Python code along top-level class/function boundaries."""
        try:
            tree = ast.parse(text)
        except Exception:
            return None

        chunks: List[SourceChunk] = []
        last_end = 0

        # Collect top-level statements
        for node in tree.body:
            node_start = getattr(node, "lineno", None)
            node_end = getattr(node, "end_lineno", None)
            if node_start is None or node_end is None:
                continue

            # If there's header / import code before this node, capture it
            if node_start > last_end + 1 and last_end == 0:
                header_lines = lines[0 : node_start - 1]
                if header_lines:
                    header_text = "".join(header_lines)
                    content_hash = compute_content_hash(header_text)
                    c_id = compute_chunk_id(source_id, 1, node_start - 1, content_hash)
                    chunks.append(
                        SourceChunk(
                            chunk_id=c_id,
                            source_id=source_id,
                            text=header_text,
                            line_start=1,
                            line_end=node_start - 1,
                            content_hash=content_hash,
                            metadata={"file_type": "python", "scope": "module_header"},
                        )
                    )

            chunk_lines = lines[node_start - 1 : node_end]
            chunk_text = "".join(chunk_lines)
            content_hash = compute_content_hash(chunk_text)
            chunk_id = compute_chunk_id(source_id, node_start, node_end, content_hash)

            scope_name = getattr(node, "name", node.__class__.__name__)
            chunks.append(
                SourceChunk(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    text=chunk_text,
                    line_start=node_start,
                    line_end=node_end,
                    content_hash=content_hash,
                    metadata={"file_type": "python", "scope": scope_name},
                )
            )
            last_end = node_end

        # Capture any trailing lines
        if last_end < len(lines) and last_end > 0:
            tail_lines = lines[last_end:]
            tail_text = "".join(tail_lines)
            content_hash = compute_content_hash(tail_text)
            c_id = compute_chunk_id(source_id, last_end + 1, len(lines), content_hash)
            chunks.append(
                SourceChunk(
                    chunk_id=c_id,
                    source_id=source_id,
                    text=tail_text,
                    line_start=last_end + 1,
                    line_end=len(lines),
                    content_hash=content_hash,
                    metadata={"file_type": "python", "scope": "module_footer"},
                )
            )

        return chunks if chunks else None
