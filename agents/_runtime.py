#!/usr/bin/env python3
"""
Shared Anthropic runtime for the tutorial agent scripts.

This keeps environment loading, local proxy compatibility, diagnostics,
and transient 5xx retries in one place so each lesson stays focused on
its own agent concept.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from anthropic import Anthropic, APIStatusError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH, override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def is_loopback_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False

    parsed = urlparse(base_url)
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
MODEL = os.environ["MODEL_ID"]
RETRY_STATUS_CODES = {500, 502, 503, 504}
MAX_API_RETRIES = 3


def build_http_client(base_url: str | None = BASE_URL) -> httpx.Client:
    # 当上游是本地回环地址时，显式忽略系统代理环境变量。
    # 否则 httpx/Anthropic SDK 可能把 127.0.0.1 请求错误地送进外部代理。
    return httpx.Client(trust_env=not is_loopback_base_url(base_url))


def build_client() -> Anthropic:
    return Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url=BASE_URL,
        http_client=build_http_client(),
    )


client = build_client()


def format_api_status_error(e: APIStatusError) -> str:
    status_code = getattr(e, "status_code", None)
    request_id = getattr(e, "request_id", None)
    response = getattr(e, "response", None)

    body_text = None
    if response is not None:
        try:
            body_text = response.text
        except Exception:
            try:
                body_text = json.dumps(response.json(), ensure_ascii=False)
            except Exception:
                body_text = repr(response)

    body_text = (body_text or "").strip()
    if len(body_text) > 2000:
        body_text = body_text[:2000] + "...(truncated)"

    return (
        f"time={datetime.now().isoformat(timespec='seconds')}, "
        f"status={status_code}, request_id={request_id or '-'}, "
        f"model={MODEL}, base_url={BASE_URL or 'https://api.anthropic.com'}\n"
        f"response_body={body_text or '(empty)'}"
    )


def create_message_with_retry(**kwargs):
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            return client.messages.create(**kwargs)
        except APIStatusError as e:
            status_code = getattr(e, "status_code", None)
            debug_message = format_api_status_error(e)

            if status_code not in RETRY_STATUS_CODES or attempt == MAX_API_RETRIES:
                print(f"\033[31mAPI request failed:\n{debug_message}\033[0m")
                raise

            wait_seconds = attempt
            print(
                f"\033[33mHTTP {status_code}，{wait_seconds} 秒后重试 "
                f"({attempt}/{MAX_API_RETRIES})\n{debug_message}\033[0m"
            )
            time.sleep(wait_seconds)
