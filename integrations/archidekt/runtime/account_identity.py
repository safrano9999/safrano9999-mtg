from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token

from ..auth.provider import account_from_access_token
from ..schemas.accounts import ArchidektAccount, AuthenticatedAccount


LOGGER = logging.getLogger("archidekt_commander_mcp.server")


def account_from_auth_context() -> AuthenticatedAccount | None:
    return account_from_access_token(get_access_token())


def _server_account_from_env() -> ArchidektAccount | None:
    """Build credentials from the MCP-only environment, never from tool input."""
    username = os.environ.get("ARCHIDEKT_USERNAME", "").strip()
    password = os.environ.get("ARCHIDEKT_PASSWORD", "")
    if not username or not password:
        return None
    return ArchidektAccount(username=username, password=password)


class ArchidektAccountIdentity:
    def __init__(
        self,
        *,
        auth_client: Callable[[], Any],
        oauth_provider: Callable[[], Any | None],
        authenticated_deck_list_loader: Callable[
            [AuthenticatedAccount],
            Awaitable[tuple[AuthenticatedAccount, list[Any]]],
        ],
        logger: logging.Logger | None = None,
    ) -> None:
        self._auth_client = auth_client
        self._oauth_provider = oauth_provider
        self._authenticated_deck_list_loader = authenticated_deck_list_loader
        self._logger = logger or LOGGER

    async def resolve_optional_account(
        self,
        account: AuthenticatedAccount | ArchidektAccount | None,
    ) -> AuthenticatedAccount | None:
        context_account = account_from_auth_context()
        if context_account is not None:
            return context_account
        if account is None:
            return None

        configured = _server_account_from_env()
        if configured is None:
            raise RuntimeError(
                "Client-supplied Archidekt credentials are disabled; configure "
                "ARCHIDEKT_USERNAME and ARCHIDEKT_PASSWORD in the MCP environment."
            )
        return cast(AuthenticatedAccount, await self._auth_client().resolve_account(configured))

    async def coerce_account(
        self,
        account: AuthenticatedAccount | ArchidektAccount | None,
    ) -> AuthenticatedAccount:
        context_account = account_from_auth_context()
        if context_account is not None:
            return context_account

        configured = _server_account_from_env()
        if configured is None:
            raise RuntimeError(
                "Authenticated Archidekt access requires the MCP auth session or "
                "ARCHIDEKT_USERNAME and ARCHIDEKT_PASSWORD in the MCP environment."
            )
        return cast(AuthenticatedAccount, await self._auth_client().resolve_account(configured))

    async def ensure_account_identity(
        self,
        account: AuthenticatedAccount,
    ) -> AuthenticatedAccount:
        if account.username and account.user_id is not None:
            return account
        resolved_account, _ = await self._authenticated_deck_list_loader(account)
        return resolved_account

    async def renew_archidekt_account(
        self,
        account: AuthenticatedAccount,
    ) -> AuthenticatedAccount | None:
        provider = self._oauth_provider()
        session = None
        login_account: ArchidektAccount | None = None

        if provider is not None and account.auth_session_id:
            try:
                session = await provider.load_session(account.auth_session_id)
            except Exception as error:
                self._logger.warning("Unable to load the Archidekt auth session: %s", error)

            if (
                session is not None
                and session.archidekt_login_identifier
                and session.archidekt_login_password
            ):
                login_account = (
                    ArchidektAccount(
                        email=session.archidekt_login_identifier,
                        password=session.archidekt_login_password,
                    )
                    if session.archidekt_login_identifier_type == "email"
                    else ArchidektAccount(
                        username=session.archidekt_login_identifier,
                        password=session.archidekt_login_password,
                    )
                )

        if login_account is None:
            login_account = _server_account_from_env()
        if login_account is None:
            return None

        try:
            renewed = await self._auth_client().login(login_account)
            if provider is not None and session is not None:
                updated_session = await provider.replace_archidekt_session_token(
                    session.session_id,
                    archidekt_token=renewed.token,
                    archidekt_username=renewed.username,
                    archidekt_user_id=renewed.user_id,
                )
                auth_session_id = (
                    updated_session.session_id
                    if updated_session is not None
                    else account.auth_session_id
                )
            else:
                auth_session_id = account.auth_session_id

            self._logger.info("Renewed the server-side Archidekt login token")
            return AuthenticatedAccount(
                token=renewed.token,
                username=renewed.username,
                user_id=renewed.user_id,
                auth_session_id=auth_session_id,
            )
        except Exception as error:
            self._logger.warning("Archidekt login renewal failed: %s", error)
            return None

    async def renew_after_archidekt_auth_failure(
        self,
        account: AuthenticatedAccount,
        error: Exception,
    ) -> AuthenticatedAccount | None:
        if not self.is_archidekt_auth_failure(error):
            return None
        renewed = await self.renew_archidekt_account(account)
        if renewed is None:
            return None
        account.token = renewed.token
        account.username = renewed.username or account.username
        account.user_id = renewed.user_id if renewed.user_id is not None else account.user_id
        account.auth_session_id = renewed.auth_session_id or account.auth_session_id
        return account

    @staticmethod
    def is_archidekt_auth_failure(error: Exception) -> bool:
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {401, 403}
        return isinstance(error, RuntimeError) and "server-side redirect" in str(error)
