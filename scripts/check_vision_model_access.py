#!/usr/bin/env python3
"""Check Bedrock Mantle access to a vision-capable Chat Completions model.

Uses OPENAI_BASE_URL and OPENAI_API_KEY from backend/.env. Credentials are never
printed. The image test sends a generated 1x1 PNG, not user data.
"""

from __future__ import annotations

import argparse
import base64
import struct
import zlib
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

DEFAULT_MODEL = "writer.palmyra-vision-7b"
def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _test_image_data_url() -> str:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x40\x80\xc0\xff")
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")



def _message_from_error(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
        detail = payload.get("error", payload)
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("detail") or "No provider detail.")
        return str(detail)
    except Exception:
        return "The provider returned a non-JSON error response."


def _request(base_url: str, api_key: str, payload: dict, timeout: float) -> dict:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_stream(base_url: str, api_key: str, payload: dict, timeout: float) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    request = Request(
        endpoint,
        data=json.dumps({**payload, "stream": True}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    chunks: list[str] = []
    with urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = event.get("choices") or []
            if choices:
                delta = (choices[0].get("delta") or {}).get("content")
                if isinstance(delta, str):
                    chunks.append(delta)
    return "".join(chunks).strip()


def _report_http_error(stage: str, error: HTTPError) -> int:
    detail = _message_from_error(error)
    if error.code == 401:
        print(f"{stage}_AUTHENTICATION_FAILED (HTTP 401): verify the Bedrock API key.")
        return 3
    if error.code in (403, 404):
        print(
            f"{stage}_MODEL_ACCESS_DENIED (HTTP {error.code}): "
            f"{detail[:500]}"
        )
        return 4
    if error.code == 429:
        print(f"{stage}_RATE_LIMITED (HTTP 429): check Bedrock quotas and service access.")
        return 5
    print(f"{stage}_REQUEST_FAILED (HTTP {error.code}): {detail[:500]}")
    return 6


def _response_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        return " ".join(
            str(part.get("text", ""))
            for part in message
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    return str(message).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Bedrock Mantle model ID")
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout in seconds")
    parser.add_argument("--images", type=int, default=4, choices=range(1, 5), help="Number of test images to send (1-4)")
    args = parser.parse_args()

    load_dotenv()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not base_url or not api_key:
        missing = [
            name for name, value in (
                ("OPENAI_BASE_URL", base_url),
                ("OPENAI_API_KEY", api_key),
            ) if not value
        ]
        print("CONFIGURATION_MISSING: " + ", ".join(missing))
        return 2

    print(f"Provider endpoint: {urlparse(base_url).hostname or 'unknown host'}")
    print(f"Model under test: {args.model}")
    print("Step 1/2: checking model access with a text-only request...")
    try:
        text_result = _request(
            base_url,
            api_key,
            {
                "model": args.model,
                "messages": [{"role": "user", "content": "Reply with exactly: ACCESS_OK"}],
                "max_tokens": 20,
            },
            args.timeout,
        )
    except HTTPError as exc:
        return _report_http_error("TEXT", exc)
    except (URLError, TimeoutError, OSError) as exc:
        print(f"TEXT_CONNECTION_FAILED: {type(exc).__name__}: {exc}")
        return 7

    print("TEXT_ACCESS_OK")
    print(f"Text response: {_response_text(text_result)[:160] or '(empty response)'}")
    print(f"Step 2/2: checking {args.images} image(s) in one request...")
    try:
        image_text = _request_stream(
            base_url,
            api_key,
            {
                "model": args.model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Describe these {args.images} test images in one short phrase."},
                        *[
                            {"type": "image_url", "image_url": {"url": _test_image_data_url()}}
                            for _ in range(args.images)
                        ],
                    ],
                }],
                "max_tokens": 40,
            },
            args.timeout,
        )
    except HTTPError as exc:
        if exc.code == 400:
            print(f"IMAGE_INPUT_REJECTED (HTTP 400): {_message_from_error(exc)[:500]}")
            print("The model is reachable, but rejected the image input request.")
            return 8
        return _report_http_error("IMAGE", exc)
    except (URLError, TimeoutError, OSError) as exc:
        print(f"IMAGE_CONNECTION_FAILED: {type(exc).__name__}: {exc}")
        return 9

    print("VISION_ACCESS_OK")
    print(f"Vision response: {image_text[:240] or '(empty response)'}")
    print(f"RESULT: model access and {args.images}-image input both succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
