from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from file_processing import process_uploaded_files
from prompt import construct_user_prompt
from openrouter_client import validate_and_estimate_tokens

# Request history directory for diagnostics
HISTORY_DIR = Path(".code_review_history")


def _generate_request_id(uploaded_files: List[Any]) -> str:
    """Generate a unique request ID based on file contents and timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    content_hash = ""
    if uploaded_files:
        first_file = uploaded_files[0]
        try:
            data = first_file.read() if hasattr(first_file, 'read') else b""
            content_hash = hashlib.md5(str(data).encode()[:1000]).hexdigest()[:8]
        except Exception:
            content_hash = "unknown"
    return f"req_{timestamp}_{content_hash}"


def _log_request_to_history(
    request_id: str,
    user_prompt: str,
    review_mode: str,
    selected_model: str,
    file_count: int,
    estimated_tokens: int,
) -> None:
    """Log request details to history for diagnostics."""
    try:
        HISTORY_DIR.mkdir(exist_ok=True)
        log_entry = {
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "review_mode": review_mode,
            "selected_model": selected_model,
            "file_count": file_count,
            "estimated_tokens": estimated_tokens,
            "prompt_length_chars": len(user_prompt),
            "prompt_excerpt": user_prompt[:500] + ("..." if len(user_prompt) > 500 else ""),
        }
        log_file = HISTORY_DIR / f"{request_id}.json"
        log_file.write_text(json.dumps(log_entry, indent=2), encoding="utf-8")
    except Exception as e:
        # Best-effort logging — don't block the request
        pass


def prepare_review(
    uploaded_files: List[Any],
    review_mode: str,
    selected_model: str,
    requested_focus: Optional[str] = None,
    summary_mode: Optional[bool] = None,
    max_file_chars: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], List[str], str, str, Tuple[bool, str, int]]:
    """Prepare code review payload: process files, build prompt, and validate size.

    Args:
        uploaded_files: Files uploaded by the user.
        review_mode: One of "Standard Review", "Refactor", "IDE Implementation Instructions".
        selected_model: OpenRouter model identifier.
        requested_focus: Optional override for the focus directive sent to the model.
        summary_mode: If None, auto-decide based on estimated size; if True/False, override.
        max_file_chars: Optional per-file char cap for the user prompt.

    Returns:
        (code_contents, warnings, user_prompt, request_id, (is_valid, size_message, estimated_tokens))
    """
    from config import DEFAULT_MAX_FILE_CHARS, SUMMARY_MODE_TRIGGER_CHARS
    code_contents, warnings = process_uploaded_files(uploaded_files)

    # Default focus directives by mode
    if requested_focus is None:
        if review_mode == "Refactor":
            requested_focus = (
                "Perform a refactor-focused review ONLY. For each refactor opportunity, "
                "produce a structured plan with the following fields:\n"
                "  - **Target file(s)**: explicit paths\n"
                "  - **Smell**: which code smell (long method, shotgun surgery, primitive obsession, etc.)\n"
                "  - **Proposed change**: high-level summary in 1-2 sentences\n"
                "  - **Risk level**: Low / Medium / High with one-line justification\n"
                "  - **Migration steps**: numbered incremental steps that preserve behavior\n"
                "  - **Verification**: tests / manual checks to confirm correctness\n"
                "Prioritize: (1) split large files (utils.py, app.py) into focused modules, "
                "(2) extract repeated helpers into a shared module, "
                "(3) replace inline logic with reusable functions, "
                "(4) reduce coupling between UI and processing layers, "
                "(5) ensure shared utilities live in one place and are imported."
            )
        elif review_mode == "IDE Implementation Instructions":
            requested_focus = (
                "Produce step-by-step IDE-friendly implementation instructions for the recommended changes. "
                "For each change: cite the file, describe the exact edit (before/after snippets), explain why, and "
                "list the risk and any test/verification step required."
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
        "Submission time": datetime.now().isoformat(timespec='seconds'),
    }

    user_prompt = construct_user_prompt(
        code_contents,
        warnings=warnings,
        review_context=review_context,
        summary_mode=bool(summary_mode) if summary_mode is not None else False,
        max_file_chars=max_file_chars or DEFAULT_MAX_FILE_CHARS,
    )

    # Auto-decide summary mode if user didn't override
    if summary_mode is None:
        total_chars = len(user_prompt)
        if total_chars > SUMMARY_MODE_TRIGGER_CHARS:
            user_prompt = construct_user_prompt(
                code_contents,
                warnings=warnings,
                review_context=review_context,
                summary_mode=True,
                max_file_chars=max_file_chars or DEFAULT_MAX_FILE_CHARS,
            )

    # Get validation with system prompt for accurate token count
    from config import SYSTEM_PROMPT, IDE_INSTRUCTIONS_PROMPT, REFACTOR_SYSTEM_PROMPT
    if review_mode == "IDE Implementation Instructions":
        system_prompt = IDE_INSTRUCTIONS_PROMPT
    elif review_mode == "Refactor":
        system_prompt = REFACTOR_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    validation = validate_and_estimate_tokens(user_prompt, system_prompt)
    is_valid = validation["is_valid"]
    size_message = validation.get("error") or validation.get("warning") or f"Request size OK: ~{validation['estimated_tokens']:,} tokens"
    estimated_tokens = validation["estimated_tokens"]

    # Generate request ID and log to history
    request_id = _generate_request_id(uploaded_files)
    _log_request_to_history(
        request_id=request_id,
        user_prompt=user_prompt,
        review_mode=review_mode,
        selected_model=selected_model,
        file_count=len(code_contents),
        estimated_tokens=estimated_tokens,
    )

    return code_contents, warnings, user_prompt, request_id, (is_valid, size_message, estimated_tokens)
