"""Run zotero-mcp over streamable HTTP behind GitHub OAuth, allowing only
the GitHub logins listed in ZMCP_ALLOWED_GITHUB_LOGINS.

zotero-mcp keeps any FastMCP auth provider already set on its server object
when ZOTERO_MCP_AUTH_TOKEN is unset, so this wrapper sets one and then hands
off to zotero-mcp's own `serve` command. No zotero-mcp code is modified.

Required environment (see zotero-mcp.env.example):
  ZMCP_PUBLIC_URL               e.g. https://zotero-mcp.austin-unowitz.com
  ZMCP_GITHUB_CLIENT_ID / ZMCP_GITHUB_CLIENT_SECRET   (GitHub OAuth App)
  ZMCP_ALLOWED_GITHUB_LOGINS    comma-separated, e.g. Unowa001
  ZMCP_JWT_SIGNING_KEY          long random string (keeps sign-ins valid across restarts)
  ZOTERO_API_KEY, ZOTERO_LIBRARY_ID, ZOTERO_LIBRARY_TYPE=user, ZOTERO_LOCAL=false
"""
from __future__ import annotations

import logging
import os
import sys

from fastmcp.server.auth.providers.github import GitHubProvider

log = logging.getLogger("zotero-oauth")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing required environment variable {name}")
    return value


def _find_login(claims: dict | None) -> str | None:
    """GitHub login from the token claims, wherever FastMCP put it."""
    if not isinstance(claims, dict):
        return None
    for key in ("login", "preferred_username"):
        if isinstance(claims.get(key), str):
            return claims[key]
    for nested in ("upstream_claims", "github_user_data"):
        found = _find_login(claims.get(nested))
        if found:
            return found
    return None


class AllowlistGitHubProvider(GitHubProvider):
    """GitHubProvider that rejects every GitHub account not on the allowlist.

    Fails closed: a token whose login can't be found is rejected.
    """

    def __init__(self, *, allowed_logins: set[str], **kwargs):
        super().__init__(**kwargs)
        self._allowed = {login.lower() for login in allowed_logins}

    async def load_access_token(self, token: str):  # type: ignore[override]
        access = await super().load_access_token(token)
        if access is None:
            return None
        login = _find_login(getattr(access, "claims", None))
        if login is None or login.lower() not in self._allowed:
            log.warning("Rejected token for GitHub login %r", login)
            return None
        return access


def main() -> None:
    port = os.environ.get("ZMCP_PORT", "8765")
    allowed = {s.strip() for s in _env("ZMCP_ALLOWED_GITHUB_LOGINS").split(",") if s.strip()}

    from zotero_mcp.server import mcp  # the server object zotero-mcp serves

    mcp.auth = AllowlistGitHubProvider(
        allowed_logins=allowed,
        client_id=_env("ZMCP_GITHUB_CLIENT_ID"),
        client_secret=_env("ZMCP_GITHUB_CLIENT_SECRET"),
        base_url=_env("ZMCP_PUBLIC_URL"),
        jwt_signing_key=_env("ZMCP_JWT_SIGNING_KEY"),
        required_scopes=["read:user"],
    )

    # A shared bearer token would replace OAuth; make sure none is set.
    os.environ.pop("ZOTERO_MCP_AUTH_TOKEN", None)

    from zotero_mcp.cli import main as zotero_main

    sys.argv = [
        "zotero-mcp", "serve",
        "--transport", "streamable-http",
        "--host", "127.0.0.1",
        "--port", port,
    ]
    zotero_main()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
