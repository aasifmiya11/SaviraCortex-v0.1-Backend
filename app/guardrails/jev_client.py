from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class JEVGatewayError(RuntimeError):
    """Raised when the configured JEV gateway cannot return a trustworthy judgment."""


class JEVGatewayClient:
    """Synchronous client for the authenticated SaviraCortex API-gateway JEV endpoint."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = (base_url or settings.JEV_GATEWAY_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.JEV_GATEWAY_API_KEY
        self.timeout_seconds = timeout_seconds or settings.JEV_TIMEOUT_SECONDS
        self.http_client = http_client

    def judge(
        self,
        *,
        task: str,
        state: dict[str, Any],
        questions: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise JEVGatewayError(
                "JEV is enabled but the backend gateway API key is not configured."
            )
        if task not in {"ingestion", "runtime"}:
            raise ValueError("JEV task must be 'ingestion' or 'runtime'.")

        payload = {"task": task, "state": state, "questions": questions}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            if self.http_client is not None:
                response = self.http_client.post(
                    f"{self.base_url}/judge",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/judge",
                        headers=headers,
                        json=payload,
                    )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JEVGatewayError(
                "The JEV gateway did not return a valid judgment."
            ) from exc

        if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
            raise JEVGatewayError("The JEV gateway response has no typed answers.")
        result["_provider"] = response.headers.get("X-JEV-Provider")
        result["_model"] = response.headers.get("X-JEV-Model")
        result["_fallback"] = response.headers.get("X-JEV-Fallback") == "true"
        return result
