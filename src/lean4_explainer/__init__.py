"""Source-level proofsite builder for Lean 4 projects."""

from .build import BuildSummary, build_site
from .config import Config, load_config
from .errors import ExplainerError
from .render import file_page, folder_pages
from .scan import Declaration, FileSummary, LeanFile, parse_source, scan_file, summarize
from .version import __version__

__all__ = [
    "BuildSummary",
    "Config",
    "Declaration",
    "ExplainerError",
    "FileSummary",
    "LeanFile",
    "build_site",
    "file_page",
    "folder_pages",
    "load_config",
    "parse_source",
    "scan_file",
    "summarize",
    "__version__",
]
