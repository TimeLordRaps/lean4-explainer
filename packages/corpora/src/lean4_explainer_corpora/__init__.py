"""Corpus registry, fetch and showcase extension for lean4-explainer."""

from .extension import CorporaExtension, __version__
from .registry import EXTRAS, Corpus, activate, installed, select

__all__ = ["EXTRAS", "CorporaExtension", "Corpus", "__version__", "activate", "installed", "select"]
