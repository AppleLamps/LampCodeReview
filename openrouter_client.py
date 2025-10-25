import json
import logging
from typing import Generator

import requests

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def stream_chat(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 30,
) -> Generator[str, None, None]:
    """Stream chat completions from OpenRouter.
    Minimal client wrapper to centralize headers, payload, and streaming.
    """
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
