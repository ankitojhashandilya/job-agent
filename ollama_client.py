# ollama_client.py

import json
import os
import re
import time
import urllib.request
from urllib.error import URLError
from urllib.parse import urlsplit

from config import (
    OLLAMA_MODEL,
    OLLAMA_OPTIONS,
    OLLAMA_TIMEOUT,
    OLLAMA_URL,
)


def _clean_keys(obj):
    """
    Recursively cleans malformed keys that sometimes
    come back from Qwen, for example:

    '\n    "score"' -> 'score'
    """

    if isinstance(obj, dict):
        cleaned = {}

        for key, value in obj.items():
            if isinstance(key, str):
                new_key = key.replace("\n", "").replace("\r", "").strip().strip('"').strip("'")
            else:
                new_key = key

            cleaned[new_key] = _clean_keys(value)

        return cleaned

    if isinstance(obj, list):
        return [_clean_keys(x) for x in obj]

    return obj


def _parse_json_response(text: str) -> dict:
    """
    Parses JSON returned by Qwen.

    Handles:
    - Pure JSON
    - JSON wrapped in markdown fences
    - Extra explanatory text
    - Malformed keys
    """

    text = text.strip()

    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        re.DOTALL,
    )

    if fenced:
        text = fenced.group(1)

    try:
        data = json.loads(text)

    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1:
            raise ValueError(f"Qwen did not return JSON:\n{text}")

        data = json.loads(text[start : end + 1])

    return _clean_keys(data)


def generate_json(
    prompt: str,
    retries: int = 3,
) -> dict:
    """
    Sends prompt to Ollama and returns parsed JSON.
    """

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "options": OLLAMA_OPTIONS,
        "keep_alive": "30m",
    }
    # AI Assistant shares its /api/chat configuration with child processes.
    # Ollama's chat endpoint requires messages and returns message.content;
    # the standalone job-agent default uses /api/generate and response.
    is_chat = urlsplit(OLLAMA_URL).path.rstrip("/").endswith("/api/chat")
    if is_chat:
        payload.pop("prompt")
        payload["messages"] = [{"role": "user", "content": prompt}]

    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):
        try:
            request = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(
                request,
                timeout=OLLAMA_TIMEOUT,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))

            raw_response = (
                (result.get("message") or {}).get("content", "")
                if is_chat
                else result.get("response", "")
            )

            #
            # Debug
            #
            if os.getenv("JOB_AGENT_DEBUG_LLM", "").lower() in {"1", "true"}:
                print(raw_response[:1500])

            parsed = _parse_json_response(raw_response)

            #
            # Debug
            #

            return parsed

        except (
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            last_error = error

            print(f"[Ollama] Attempt {attempt}/{retries} failed:")
            print(error)

            if attempt < retries:
                time.sleep(2)

    raise RuntimeError(f"Ollama failed after {retries} attempts.\nLast error: {last_error}")
