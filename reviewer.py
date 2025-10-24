import requests
import json
import logging
import uuid
import os
from typing import Generator, Tuple, Optional
from datetime import datetime
from pathlib import Path
from config import SYSTEM_PROMPT, IDE_INSTRUCTIONS_PROMPT

logger = logging.getLogger(__name__)

# Token estimation: roughly 0.25 tokens per character for code
ESTIMATED_TOKENS_PER_CHAR = 0.25
MAX_REQUEST_TOKENS = 200000  # Increased limit for larger codebases

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


def validate_and_estimate_tokens(user_prompt: str) -> Tuple[bool, str, int]:
    """
    Validate request size and estimate token count.
    
    Returns: (is_valid, message, estimated_tokens)
    """
    if not user_prompt:
        return False, "Prompt is empty", 0
    
    estimated_tokens = int(len(user_prompt) * ESTIMATED_TOKENS_PER_CHAR)
    
    if estimated_tokens > MAX_REQUEST_TOKENS:
        return (
            False,
            f"Request too large: ~{estimated_tokens} tokens (limit: {MAX_REQUEST_TOKENS}). "
            f"Try uploading fewer or smaller files.",
            estimated_tokens
        )
    
    if estimated_tokens > MAX_REQUEST_TOKENS * 0.75:  # Warn at 75% of limit
        return (
            True,
            f"⚠️ Large request: ~{estimated_tokens} tokens (limit: {MAX_REQUEST_TOKENS}). "
            f"Response may be truncated.",
            estimated_tokens
        )
    
    return True, f"✅ Request size OK: ~{estimated_tokens} tokens", estimated_tokens


def stream_grok_review(
    api_key: str,
    user_prompt: str,
    use_ide_instructions: bool = False,
    model: str = "x-ai/grok-4",
    file_count: int = 0,
) -> Generator[str, None, None]:
    """Stream the Grok review response with request validation and logging."""
    # Generate request ID for tracking
    request_id = str(uuid.uuid4())[:8]
    
    # Validate inputs
    if not api_key or not isinstance(api_key, str):
        yield "❌ **Error**: Invalid API key provided."
        return
    
    if not user_prompt or not isinstance(user_prompt, str):
        yield "❌ **Error**: Invalid prompt provided."
        return
    
    # Validate request size
    is_valid, size_message, estimated_tokens = validate_and_estimate_tokens(user_prompt)
    logger.info(f"Request {request_id} validation: {size_message}")
    
    # Log the request
    log_request(request_id, model, estimated_tokens, file_count)
    
    if not is_valid:
        yield f"❌ **Request Too Large**: {size_message}"
        return
    
    if "⚠️" in size_message:
        yield f"{size_message}\n\n"
    
    # Show request ID for diagnostics
    yield f"*Request ID: `{request_id}`*\n\n"
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": f"AI Code Review ({model})",
    }

    system_prompt = IDE_INSTRUCTIONS_PROMPT if use_ide_instructions else SYSTEM_PROMPT

    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": True,
        "temperature": 0.1
    }

    try:
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=30)
        response.raise_for_status()

        chunk_count = 0
        for line in response.iter_lines():
            try:
                if line:
                    try:
                        line = line.decode('utf-8')
                    except UnicodeDecodeError as e:
                        logger.warning(f"Failed to decode response line as UTF-8: {e}")
                        continue

                    if line.startswith('data: '):
                        line = line[6:]  # Remove 'data: ' prefix
                        if line.strip() == '[DONE]':
                            break
                        try:
                            chunk = json.loads(line)
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    chunk_count += 1
                                    yield delta['content']
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse JSON chunk: {e}")
                            continue
                        except (KeyError, IndexError, TypeError) as e:
                            logger.warning(f"Unexpected response structure: {e}")
                            continue
            except Exception as e:
                logger.error(f"Error processing stream line: {e}")
                continue
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
        yield "⏱️ **Timeout Error**: The request took too long (30 seconds). Please try again with smaller files or check your internet connection."
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