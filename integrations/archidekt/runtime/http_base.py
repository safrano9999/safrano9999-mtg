from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import RuntimeSettings
from .request_gate import ArchidektRequestGate


LOGGER = logging.getLogger("archidekt_commander_mcp.clients")


_AUTH_SCHEME_HEADERS = {"bearer": "Bearer", "jwt": "JWT"}
_AUTH_SCHEME_NAMES = frozenset(_AUTH_SCHEME_HEADERS)


def _configured_auth_scheme() -> str:
    raw = os.environ.get("ARCHIDEKT_MCP_AUTH_SCHEME", "jwt").strip().lower()
    try:
        return _AUTH_SCHEME_HEADERS[raw]
    except KeyError as error:
        raise ValueError(
            "ARCHIDEKT_MCP_AUTH_SCHEME must be either 'bearer' or 'jwt'"
        ) from error


def _endpoint_auth_scheme(url: str) -> str:
    """Return the scheme required by an Archidekt endpoint.

    The configured scheme remains the default for endpoints where Archidekt
    accepts either form.  These two routes are the known exceptions: the
    personal v3 listing requires Bearer, while the curated identity route
    requires JWT for the same token.
    """
    path = urlsplit(url).path.rstrip("/") + "/"
    if path.startswith("/api/decks/v3/"):
        return "Bearer"
    if path.startswith("/api/decks/curated/"):
        return "JWT"
    return _configured_auth_scheme()


def _auth_headers(token: str | None, scheme: str | None = None) -> dict[str, str]:
    if not token:
        return {}
    selected = scheme
    if selected is None:
        selected = _configured_auth_scheme()
    selected = _AUTH_SCHEME_HEADERS.get(selected.strip().lower(), selected)
    if selected not in _AUTH_SCHEME_HEADERS.values():
        raise ValueError("Auth scheme must be either 'bearer' or 'jwt'")
    return {"Authorization": f"{selected} {token}"}


def _json_headers(token: str | None) -> dict[str, str]:
    headers = _auth_headers(token)
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"
    return headers


class _ArchidektHttpClientBase:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: RuntimeSettings,
        request_gate: ArchidektRequestGate | None = None,
    ) -> None:
        self.http_client = http_client
        self.settings = settings
        self.request_gate = request_gate or ArchidektRequestGate.from_settings(settings)
        self._retry_sleep = self.request_gate._sleep

    @staticmethod
    def _auth_token_from_headers(headers: Any) -> str | None:
        if not headers:
            return None
        for name, value in dict(headers).items():
            if str(name).casefold() != "authorization":
                continue
            parts = str(value).strip().split(None, 1)
            if len(parts) == 2 and parts[0].casefold() in _AUTH_SCHEME_NAMES:
                return parts[1].strip() or None
        return None

    @staticmethod
    def _headers_with_auth_scheme(
        headers: Any,
        token: str,
        scheme: str,
    ) -> dict[str, str]:
        normalized = {
            str(name): str(value)
            for name, value in dict(headers or {}).items()
            if str(name).casefold() != "authorization"
        }
        normalized.update(_auth_headers(token, scheme=scheme))
        return normalized

    def _prepare_request_kwargs(
        self,
        url: str,
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None, str | None]:
        prepared = dict(kwargs)
        token = self._auth_token_from_headers(prepared.get("headers"))
        if token is None:
            return prepared, None, None
        scheme = _endpoint_auth_scheme(url)
        prepared["headers"] = self._headers_with_auth_scheme(
            prepared.get("headers"), token, scheme
        )
        return prepared, token, scheme

    @staticmethod
    def _auth_fallback_enabled() -> bool:
        raw = os.environ.get("ARCHIDEKT_MCP_AUTH_FALLBACK", "false")
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _alternate_auth_scheme(scheme: str) -> str:
        return "JWT" if scheme == "Bearer" else "Bearer"

    async def _request_archidekt(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        max_attempts = self.settings.archidekt_retry_max_attempts
        attempt = 0
        prepared_kwargs, token, primary_scheme = self._prepare_request_kwargs(url, kwargs)
        fallback_attempted = False

        while True:
            await self.request_gate.wait_for_slot()
            response = await self.http_client.request(method, url, **prepared_kwargs)
            if (
                response.status_code in {401, 403}
                and token
                and primary_scheme
                and not fallback_attempted
                and self._auth_fallback_enabled()
            ):
                fallback_attempted = True
                fallback_scheme = self._alternate_auth_scheme(primary_scheme)
                fallback_kwargs = dict(prepared_kwargs)
                fallback_kwargs["headers"] = self._headers_with_auth_scheme(
                    prepared_kwargs.get("headers"), token, fallback_scheme
                )
                LOGGER.info(
                    "Archidekt rejected %s auth for %s %s; retrying once with %s",
                    primary_scheme,
                    method,
                    url,
                    fallback_scheme,
                )
                await self.request_gate.wait_for_slot()
                response = await self.http_client.request(method, url, **fallback_kwargs)
            if response.status_code != 429 or attempt + 1 >= max_attempts:
                return response

            retry_delay_seconds = self._archidekt_retry_delay_seconds(response, attempt)
            LOGGER.warning(
                "Archidekt returned 429 for %s %s; retrying in %.3f seconds (attempt %d/%d)",
                method,
                url,
                retry_delay_seconds,
                attempt + 1,
                max_attempts - 1,
            )
            await self._retry_sleep(retry_delay_seconds)
            attempt += 1

    def _archidekt_retry_delay_seconds(
        self,
        response: httpx.Response,
        attempt: int,
    ) -> float:
        retry_after_seconds = self._parse_retry_after_seconds(response)
        if retry_after_seconds is not None:
            return retry_after_seconds
        return float(
            min(
                self.settings.archidekt_retry_base_delay_seconds * (2**attempt),
                8.0,
            )
        )

    def _parse_retry_after_seconds(self, response: httpx.Response) -> float | None:
        headers = getattr(response, "headers", None)
        if not headers:
            return None

        raw_retry_after = headers.get("Retry-After")
        if not isinstance(raw_retry_after, str):
            return None

        try:
            retry_after_seconds = float(raw_retry_after.strip())
        except (TypeError, ValueError):
            return None

        if retry_after_seconds < 0:
            return None
        return retry_after_seconds
