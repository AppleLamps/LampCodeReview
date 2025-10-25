from typing import Any, Dict, List, Tuple

from file_processing import process_uploaded_files
from prompt import construct_user_prompt
from reviewer import validate_and_estimate_tokens


def prepare_review(
    uploaded_files: List[Any],
    review_mode: str,
    selected_model: str,
) -> Tuple[List[Dict[str, str]], List[str], str, Tuple[bool, str, int]]:
    """Prepare code review payload: process files, build prompt, and validate size.

    Returns:
        (code_contents, warnings, user_prompt, (is_valid, size_message, estimated_tokens))
    """
    code_contents, warnings = process_uploaded_files(uploaded_files)

    if review_mode == "Refactor":
        requested_focus = (
            "Perform a refactor-focused review ONLY. Identify files and modules that should be refactored, "
            "modularized, or reorganized to improve cohesion, reduce coupling, and increase testability. "
            "Propose an incremental plan that preserves behavior and quality (no feature changes). Include: "
            "(1) files to split or merge, (2) helper/function extraction opportunities, (3) suggested module layout, "
            "(4) high-level migration steps with minimal risk, (5) notes on path normalization and shared utilities."
        )
    else:
        requested_focus = (
            "Identify improvements to this application's code review pipeline, "
            "file handling, and prompting strategy while addressing code-level issues."
        )

    review_context = {
        "Review mode": review_mode,
        "Selected model": selected_model,
        "Requested focus": requested_focus,
    }

    user_prompt = construct_user_prompt(
        code_contents,
        warnings=warnings,
        review_context=review_context,
    )

    is_valid, size_message, estimated_tokens = validate_and_estimate_tokens(user_prompt)

    return code_contents, warnings, user_prompt, (is_valid, size_message, estimated_tokens)
