"""Browser-local storage bridge for sensitive session preferences."""

from pathlib import Path
from typing import Literal, Optional

import streamlit.components.v1 as components


_COMPONENT_PATH = Path(__file__).resolve().parent / "components" / "browser_storage"
_browser_storage = components.declare_component(
    "browser_storage",
    path=_COMPONENT_PATH,
)


def browser_api_key(
    action: Literal["load", "save", "clear"] = "load",
    value: str = "",
) -> Optional[str]:
    """Load, save, or clear the OpenRouter key in this browser only."""
    return _browser_storage(
        action=action,
        storage_key="lamp_code_review_openrouter_api_key",
        value=value,
        default="",
        key="browser_openrouter_api_key_storage",
    )
