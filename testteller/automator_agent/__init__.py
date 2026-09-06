"""
TestTeller RAG-Enhanced Automator Agent Package.

This package provides RAG-enhanced test automation generation using vector store knowledge:
- Complete working test code generation (no templates or TODOs)
- Real application context discovery from vector stores
- Multi-language and framework support
- Quality validation and assessment
"""

def __getattr__(name: str):
    if name == "automate_command":
        from .cli import automate_command
        return automate_command
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["automate_command"]