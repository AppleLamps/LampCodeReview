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


def _generate_request_id(code_contents: List[Dict[str, str]]) -> str:
    """Generate a unique request ID based on processed file contents."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    content_hash = ""
    if code_contents:
        m = hashlib.md5()
        for item in sorted(code_contents, key=lambda x: x['filename']):
            m.update(item['filename'].encode())
            m.update(str(len(item['content'])).encode())
            m.update(item['content'][:200].encode())
        content_hash = m.hexdigest()[:8]
    return f"req_{timestamp}_{content_hash}"


def _log_request_to_history(
    request_id: str,
    review_mode: str,
    selected_model: str,
    file_count: int,
    estimated_tokens: int,
    prompt_length_chars: int,
) -> None:
    """Log request metadata to history for diagnostics."""
    try:
        HISTORY_DIR.mkdir(exist_ok=True)
        log_entry = {
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "review_mode": review_mode,
            "selected_model": selected_model,
            "file_count": file_count,
            "estimated_tokens": estimated_tokens,
            "prompt_length_chars": prompt_length_chars,
        }
        log_file = HISTORY_DIR / f"{request_id}.json"
        log_file.write_text(json.dumps(log_entry, indent=2), encoding="utf-8")
    except Exception:
        pass


def prepare_review(
    uploaded_files: List[Any],
    review_mode: str,
    selected_model: str,
    requested_focus: Optional[str] = None,
    summary_mode: Optional[bool] = None,
    max_file_chars: Optional[int] = None,
) -> Tuple[List[Dict[str, str]], List[str], str, str, Tuple[bool, str, int]]:
    """Prepare code review payload: process files, build prompt, and validate size."""
    from config import DEFAULT_MAX_FILE_CHARS, SUMMARY_MODE_TRIGGER_CHARS, MAX_FILE_SIZE

    code_contents, warnings = process_uploaded_files(uploaded_files)
    max_file_cap = max_file_chars or DEFAULT_MAX_FILE_CHARS

    # Estimate total content chars to decide summary mode before building prompt
    def _estimate_content_chars(contents: List[Dict[str, str]]) -> int:
        total = 0
        for item in contents:
            chars = len(item['content'])
            if max_file_cap and chars > max_file_cap:
                total += max_file_cap
            else:
                total += chars
        return total

    auto_summary = summary_mode
    if auto_summary is None:
        estimated_content = _estimate_content_chars(code_contents)
        # Rough overhead: ~2K chars per file for metadata/stats/headers
        estimated_overhead = len(code_contents) * 2000 + 5000
        estimated_total = estimated_content + estimated_overhead
        auto_summary = estimated_total > SUMMARY_MODE_TRIGGER_CHARS

    # ... (focus directive defaults remain the same)

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
        summary_mode=bool(auto_summary),
        max_file_chars=max_file_cap,
    )

    # Get validation with system prompt for accurate token count
    from config import SYSTEM_PROMPT, IDE_INSTRUCTIONS_PROMPT, REFACTOR_SYSTEM_PROMPT
    if review_mode == "IDE Implementation Instructions":
        system_prompt = IDE_INSTRUCTIONS_PROMPT
    elif review_mode == "Refactor":
        system_prompt = REFACTOR_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    validation = validate_and_estimate_tokens(user_prompt, system_prompt, model=selected_model)
    is_valid = validation["is_valid"]
    size_message = validation.get("error") or validation.get("warning") or f"Request size OK: ~{validation['estimated_tokens']:,} tokens"
    estimated_tokens = validation["estimated_tokens"]

    # Generate request ID and log to history
    request_id = _generate_request_id(code_contents)
    _log_request_to_history(
        request_id=request_id,
        review_mode=review_mode,
        selected_model=selected_model,
        file_count=len(code_contents),
        estimated_tokens=estimated_tokens,
        prompt_length_chars=len(user_prompt),
    )

    return code_contents, warnings, user_prompt, request_id, (is_valid, size_message, estimated_tokens)
