import requests
import json
import logging
import uuid
import os
import threading
from typing import Generator, Optional
from datetime import datetime
from pathlib import Path
from config import SYSTEM_PROMPT, IDE_INSTRUCTIONS_PROMPT, REFACTOR_SYSTEM_PROMPT
from openrouter_client import stream_chat, validate_and_estimate_tokens

logger = logging.getLogger(__name__)

# Request history tracking
HISTORY_DIR = Path(".code_review_history")


def _ensure_history_dir() -> Optional[Path]:
    """Ensure history directory exists."""
    try:
        HISTORY_DIR.mkdir(exist_ok=True)
        return HISTORY_DIR
    except Exception as e:
        logger.warning(f"Could not create history directory: {e}")
        return None


def log_request(request_id: str, model: str, estimated_tokens: int, file_count: int) -> None:
    """Log a request to history for diagnostics."""
    try:
        history_dir = _ensure_history_dir()
        if not history_dir:
            return

        log_entry = {
            'request_id': request_id,
            'timestamp': datetime.now().isoformat(),
            'model': model,
            'estimated_tokens': estimated_tokens,
            'file_count': file_count
        }

        log_file = history_dir / f"{request_id}.json"
        with open(log_file, 'w') as f:
            json.dump(log_entry, f, indent=2)

        logger.info(f"Request {request_id} logged to history")
    except Exception as e:
        logger.warning(f"Could not log request: {e}")


class StreamCancellationToken:
    """Lightweight cancellation token for streaming responses."""
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


def stream_grok_review(
    api_key: str,
    user_prompt: str,
    use_ide_instructions: bool = False,
    model: str = "x-ai/grok-4",
    file_count: int = 0,
    review_mode: str = "Standard Review",
    cancel_token: Optional[StreamCancellationToken] = None,
) -> Generator[str, None, None]:
    """Stream the Grok review response with request validation and logging.

    Args:
        cancel_token: Optional token to allow the caller to cancel the stream
                      mid-flight. Checked between chunks.
    """
    # Generate request ID for tracking
    request_id = str(uuid.uuid4())[:8]

    # Validate inputs
    if not api_key or not isinstance(api_key, str):
        yield "❌ **Error**: Invalid API key provided."
        return

    if not user_prompt or not isinstance(user_prompt, str):
        yield "❌ **Error**: Invalid prompt provided."
        return

    if cancel_token is None:
        cancel_token = StreamCancellationToken()

    if use_ide_instructions or review_mode == "IDE Implementation Instructions":
        system_prompt = IDE_INSTRUCTIONS_PROMPT
    elif review_mode == "Refactor":
        system_prompt = REFACTOR_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT

    # Validate with both prompts for accurate token count
    validation = validate_and_estimate_tokens(user_prompt, system_prompt, model=model)

    # Log the request
    log_request(request_id, model, validation["estimated_tokens"], file_count)

    if not validation["is_valid"]:
        yield f"❌ **Request Too Large**: {validation['error']}"
        return

    if validation.get("warning") and "Large request" in validation["warning"]:
        yield f"{validation['warning']}\n\n"

    # Show request ID for diagnostics
    yield f"*Request ID: `{request_id}`*\n\n"

    try:
        chunk_count = 0
        for content in stream_chat(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout=60,
        ):
            chunk_count += 1
            if cancel_token.cancelled:
                yield "\n\n⏹️ **Stream cancelled by user.**"
                logger.info(f"Request {request_id} cancelled after {chunk_count} chunks")
                return
            yield content
    except requests.exceptions.HTTPError as e:
        error_code = e.response.status_code
        try:
            error_detail = e.response.json().get('error', {}).get('message', '')
        except:
            error_detail = ''

        if error_code == 401:
            yield "❌ **Authentication Error**: Invalid API key. Please verify your OpenRouter credentials at https://openrouter.ai/keys"
        elif error_code == 429:
            yield "⏱️ **Rate Limit Exceeded**: Too many requests. Please wait a few minutes or check your OpenRouter quota at https://openrouter.ai/activity"
        elif error_code == 402:
            yield "💳 **Payment Required**: Insufficient credits. Please add credits to your OpenRouter account."
        elif error_code == 503:
            yield "🔧 **Service Unavailable**: The AI model is temporarily unavailable. Please try again in a few minutes."
        else:
            detail = f" - {error_detail}" if error_detail else ""
            yield f"❌ **HTTP Error {error_code}**: {str(e)}{detail}\n\nPlease check the OpenRouter status page or try a different model."
        logger.error(f"HTTP Error {error_code} from OpenRouter: {e}")
    except requests.exceptions.Timeout as e:
        yield "⏱️ **Timeout Error**: The request took too long (60 seconds). Please try again with smaller files or check your internet connection."
        logger.error(f"Request timeout: {e}")
    except requests.exceptions.ConnectionError as e:
        yield "🌐 **Connection Error**: Could not connect to OpenRouter. Please check your internet connection and try again."
        logger.error(f"Connection error: {e}")
    except requests.exceptions.RequestException as e:
        yield f"❌ **Network Error**: {str(e)}\n\nPlease check your internet connection and try again."
        logger.error(f"Request exception: {e}")
    except Exception as e:
        yield f"❌ **Unexpected Error**: An unexpected error occurred: {str(e)}\n\nPlease try again or contact support."
        logger.error(f"Unexpected error in stream_grok_review: {e}")