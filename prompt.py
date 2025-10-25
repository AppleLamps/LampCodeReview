# Thin wrapper module for prompt construction.
# Delegates to utils.construct_user_prompt to preserve behavior.

from typing import List, Dict, Any, Optional

from utils import construct_user_prompt

__all__ = ["construct_user_prompt"]
