import json
import logging
from typing import Generator, Dict, Any

import requests

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Token estimation: roughly 0.25 tokens per character for code
ESTIMATED_TOKENS_PER_CHAR = 0.25
MAX_REQUEST_TOKENS = 200000


def stream_chat(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 30,
) -> Generator[str, None, None]:
    """Stream chat completions from OpenRouter."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": f"AI Code Review ({model})",
    }

    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": True,
        "temperature": 0.1,
    }

    response = requests.post(API_URL, headers=headers, json=data, stream=True, timeout=timeout)
    response.raise_for_status()

    for line in response.iter_lines():
        if not line:
            continue
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.warning(f"Failed to decode response line as UTF-8: {e}")
            continue

        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                if "choices" in chunk and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON chunk: {e}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected streaming chunk structure: {e}")
                continue


def validate_and_estimate_tokens(user_prompt: str, system_prompt: str = "") -> Dict[str, Any]:
    """
    Validate request size and estimate token count.
    
    Returns: dict with validation result, token estimates, and warnings
    """
    if not user_prompt:
        return {
            "is_valid": False,
            "error": "Prompt is empty",
            "estimated_tokens": 0,
            "warning": None,
        }
    
    total_chars = len(user_prompt) + len(system_prompt)
    estimated_tokens = int(total_chars * ESTIMATED_TOKENS_PER_CHAR)
    
    if estimated_tokens > MAX_REQUEST_TOKENS:
        return {
            "is_valid": False,
            "error": f"Request too large: ~{estimated_tokens} tokens (limit: {MAX_REQUEST_TOKENS}). Try uploading fewer or smaller files.",
            "estimated_tokens": estimated_tokens,
            "warning": None,
        }
    
    if estimated_tokens > MAX_REQUEST_TOKENS * 0.75:
        return {
            "is_valid": True,
            "error": None,
            "estimated_tokens": estimated_tokens,
            "warning": f"Large request: ~{estimated_tokens} tokens (limit: {MAX_REQUEST_TOKENS}). Response may be truncated.",
        }
    
    return {
        "is_valid": True,
        "error": None,
        "estimated_tokens": estimated_tokens,
        "warning": f"Request size OK: ~{estimated_tokens} tokens",
    }


def estimate_cost(tokens: int, model: str) -> float:
    """Rough cost estimate in USD based on model pricing."""
    model_costs = {
        "grok": 0.0005,
        "gpt-5": 0.01,
        "gpt-4": 0.03,
        "claude": 0.015,
        "gemini": 0.001,
        "default": 0.002,
    }
    
    model_lower = model.lower()
    cost_per_1k = model_costs.get("default", 0.002)
    for key, cost in model_costs.items():
        if key in model_lower:
            cost_per_1k = cost
            break
    
    return (tokens / 1000) * cost_per_1k