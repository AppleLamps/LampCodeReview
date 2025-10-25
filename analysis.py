# Thin wrapper module for analysis helpers.
# Delegates to utils to avoid behavior changes while enabling modular imports.

from typing import List, Dict, Any

from utils import (
    detect_dependencies,
    detect_redundancy,
    detect_project_context,
    prioritize_files,
)

__all__ = [
    "detect_dependencies",
    "detect_redundancy",
    "detect_project_context",
    "prioritize_files",
]
