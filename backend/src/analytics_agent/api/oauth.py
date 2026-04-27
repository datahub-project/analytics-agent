"""
OAuth SSO support for data engine integrations.

Design principles:
- One master Fernet key (OAUTH_MASTER_KEY) encrypts all secrets/tokens at rest.
- Per-integration OAuth app config (client_id, client_secret, redirect_uri) is stored
  in the `settings` DB table at key "oauth_app:{engine_name}".
- Per-integration tokens stored at "oauth_token:{engine_name}".
- Adding a new integration requires no changes to config.py — only an admin UI entry
  and a provider-specific authorize/token-request URL mapping below.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

import httpx
import orjson
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from analytics_agent.db.base import get_session
from analytics_agent.db.repository import CredentialRepo, SettingsRepo

router = APIRouter(prefix="/api/oauth", tags=["oauth"])
logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 600  # 10 minutes

# ---------------------------------------------------------------------------
# Provider registry — extend here to support new integrations
# ---------------------------------------------------------------------------


def _snowflake_urls(account: str) -> dict[str, str]:
    base = f"https://{account}.snowflakecomputing.com"
    return {
        "authorize_url": f"{base}/oauth/authorize",
        "token_url": f"{base}/oauth/token-request",
        "default_scope": "session:role:PUBLIC",
    }


def _get_provider_urls(engine_type: str, connection_cfg: dict) -> dict[str, str]:
    """Return OAuth endpoint URLs for the given engine type."""
    if engine_type == "snowflake":
        account = connection_cfg.get("account", "")
        if not account:
            raise ValueError("SNOWFLAKE_ACCOUNT is not configured.")
        return _snowflake_urls(account)
    raise ValueError(f"OAuth not supported for engine type '{engine_type}'")


def _get_engine_type_and_cfg(engine_name: str) -> tuple[str, dict]:
    """Look up the engine type and connection config by engine name."""
    from analytics_agent.config import settings

    for cfg in settings.load_engines_config():
        if cfg.effective_name == engine_name:
            return cfg.type, cfg.connection
    raise ValueError(f"Engine '{engine_name}' not found in config.")


# ---------------------------------------------------------------------------
# Encryption helpers (one key for all integrations)
# ---------------------------------------------------------------------------


def _get_fernet():
    import os
    import re

    from cryptography.fernet import Fernet

    from analytics_agent.api.settings import _find_env_file
    from analytics_agent.config import settings

    key = settings.oauth_master_key.strip()
    if not key:
        key = Fernet.generate_key().decode()
        logger.warning("OAUTH_MASTER_KEY not set — auto-generating. Persist this key in .env.")
        env_path = _find_env_file()
        if env_path.exists():
            try:
                content = env_path.read_text()
                pat = re.compile(r"^OAUTH_MASTER_KEY=.*$", re.MULTILINE)
                line = f"OAUTH_MASTER_KEY={key}"
                content = (
                    pat.sub(line, content)
                    if pat.search(content)
                    else content.rstrip("\n") + f"\n{line}\n"
                )
                env_path.write_text(content)
            except Exception as exc:
                logger.warning(
                    "Could not persist OAUTH_MASTER_KEY to %s: %s — key is ephemeral this session",
                    env_path,
                    exc,
                )
        else:
            logger.warning(
                "No .env file found at %s — OAUTH_MASTER_KEY will not persist across restarts",
                env_path,
            )
        os.environ["OAUTH_MASTER_KEY"] = key

    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


# ---------------------------------------------------------------------------
# DB key helpers
# ---------------------------------------------------------------------------


def _app_key(engine_name: str) -> str:
    return f"oauth_app:{engine_name}"


def _token_key(engine_name: str) -> str:
    return f"oauth_token:{engine_name}"


def _state_key(nonce: str) -> str:
    return f"oauth_state:{nonce}"


# ---------------------------------------------------------------------------
# OAuth app config (client_id / client_secret per integration)
# ---------------------------------------------------------------------------


class OAuthAppConfig(BaseModel):
    client_id: str
    client_secret: str = ""  # empty means "unchanged" when updating
    redirect_uri: str = ""


async def _load_app_config(repo: SettingsRepo, engine_name: str) -> dict | None:
    raw = await repo.get(_app_key(engine_name))
    if not raw:
        return None
    try:
        data = orjson.loads(raw)
        if data.get("client_secret_enc"):
            data["client_secret"] = _decrypt(data["client_secret_enc"])
        return data
    except Exception:
        return None


async def _save_app_config(
    repo: SettingsRepo, engine_name: str, client_id: str, client_secret: str, redirect_uri: str
) -> None:
    data = {
        "client_id": client_id,
        "client_secret_enc": _encrypt(client_secret),
        "redirect_uri": redirect_uri,
    }
    await repo.set(_app_key(engine_name), orjson.dumps(data).decode())


# ---------------------------------------------------------------------------
# Credential helpers — now backed by integration_credentials table
# ---------------------------------------------------------------------------


async def _store_oauth_tokens(
    cred_repo: CredentialRepo,
    engine_name: str,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    username: str,
    token_type: str = "Bearer",
) -> None:
    import uuid

    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    metadata = {"token_type": token_type}
    if refresh_token:
        metadata["refresh_token_enc"] = _encrypt(refresh_token)
    await cred_repo.upsert(
        id=str(uuid.uuid4()),
        integration_name=engine_name,
        auth_type="oauth",
        username=username,
        secret_enc=_encrypt(access_token),
        metadata_enc=orjson.dumps(metadata).decode(),
        expires_at=expires_at,
    )


async def _refresh_oauth_token(
    cred_repo: CredentialRepo,
    settings_repo: SettingsRepo,
    engine_name: str,
    cred,
    app_cfg: dict,
    token_url: str,
) -> str | None:
    try:
        meta = orjson.loads(_decrypt(cred.metadata_enc)) if cred.metadata_enc else {}
        refresh_token = _decrypt(meta["refresh_token_enc"]) if meta.get("refresh_token_enc") else ""
    except Exception:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_cfg["client_id"],
                "client_secret": app_cfg["client_secret"],
            },
        )

    if resp.status_code != 200:
        logger.error("OAuth token refresh failed for %s: %s", engine_name, resp.text)
        return None

    token_resp = resp.json()
    new_access = token_resp.get("access_token", "")
    new_refresh = token_resp.get("refresh_token", refresh_token)
    expires_in = token_resp.get("expires_in", 600)
    if not new_access:
        return None

    await _store_oauth_tokens(
        cred_repo,
        engine_name,
        new_access,
        new_refresh,
        expires_in,
        username=cred.username or "",
        token_type="Bearer",
    )
    return new_access


# ---------------------------------------------------------------------------
# Public helper — called from chat.py before building the graph
# ---------------------------------------------------------------------------

_EXTERNALBROWSER_PREFIX = "__externalbrowser__:"
_PAT_PREFIX = "__pat__:"
_PRIVATE_KEY_PREFIX = "__private_key__:"


async def _renew_sso_session(cred, engine_name: str, cred_repo: CredentialRepo) -> str | None:
    """
    Use the stored master token to silently renew a Snowflake session.
    Returns a new session token, or None if renewal fails (user must re-auth via browser).
    """
    if not cred.metadata_enc:
        return None
    try:
        meta = orjson.loads(cred.metadata_enc)
        master_token = _decrypt(meta["master_token_enc"]) if meta.get("master_token_enc") else ""
        account = meta.get("account", "")
        username = cred.username or ""
    except Exception:
        return None

    if not master_token or not account:
        return None

    # Snowflake token renewal via REST
    url = f"https://{account}.snowflakecomputing.com/session/token-request"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f'Snowflake Token="{master_token}"',
                    "Content-Type": "application/json",
                },
                json={"REQUEST_TYPE": "RENEW", "oldSessionToken": ""},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        new_token = data.get("data", {}).get("sessionToken", "")
        if not new_token:
            return None

        # Reconnect with the new session token and cache it
        import snowflake.connector  # type: ignore

        conn = snowflake.connector.connect(
            account=account,
            user=username,
            authenticator="oauth",
            token=new_token,
            login_timeout=10,
        )
        from analytics_agent.engines.snowflake.engine import store_sso_connection

        store_sso_connection(account, username, conn)

        # Update stored session token
        meta["session_token_enc"] = _encrypt(new_token)
        import uuid

        await cred_repo.upsert(
            id=str(uuid.uuid4()),
            integration_name=engine_name,
            auth_type="sso_externalbrowser",
            username=username,
            metadata_enc=orjson.dumps(meta).decode(),
        )
        return new_token
    except Exception:
        return None


async def get_valid_access_token(engine_name: str, repo: SettingsRepo) -> str | None:
    """
    Return auth info for the engine:
    - "__externalbrowser__:<user>" if the user signed in via browser SSO
    - A decrypted OAuth access token string if signed in via OAuth app flow
    - None if no SSO is configured (fall back to password/key auth)
    """
    from analytics_agent.db.repository import CredentialRepo

    cred_repo = CredentialRepo(repo._session)
    cred = await cred_repo.get(engine_name)
    if not cred:
        return None

    if cred.auth_type == "sso_externalbrowser":
        # Try to silently renew using the stored master token first.
        # If the in-memory cache is already warm this short-circuits immediately.
        # If renewal succeeds the connection is re-cached and the sentinel is returned.
        # If renewal fails (master token expired too), fall back to browser re-auth sentinel.
        if cred.metadata_enc:
            renewed = await _renew_sso_session(cred, engine_name, cred_repo)
            if renewed:
                logger.debug("SSO session renewed via master token for %s", engine_name)
        return f"{_EXTERNALBROWSER_PREFIX}{cred.username or ''}"

    if cred.auth_type == "pat":
        try:
            token = _decrypt(cred.secret_enc) if cred.secret_enc else ""
            username = cred.username or ""
            return f"{_PAT_PREFIX}{username}|{token}" if token else None
        except Exception:
            return None

    if cred.auth_type == "private_key":
        try:
            pem = _decrypt(cred.secret_enc) if cred.secret_enc else ""
            user = cred.username or ""
            # Pack as __private_key__:<user>|<pem>
            return f"{_PRIVATE_KEY_PREFIX}{user}|{pem}" if pem else None
        except Exception:
            return None

    if cred.auth_type != "oauth":
        return None

    # OAuth app flow: check expiry and refresh if needed
    expires_at = cred.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at and datetime.now(UTC) >= expires_at - timedelta(seconds=60):
        app_cfg = await _load_app_config(repo, engine_name)
        if not app_cfg:
            return None
        try:
            engine_type, conn_cfg = _get_engine_type_and_cfg(engine_name)
            urls = _get_provider_urls(engine_type, conn_cfg)
        except Exception:
            return None
        return await _refresh_oauth_token(
            cred_repo, repo, engine_name, cred, app_cfg, urls["token_url"]
        )

    try:
        return _decrypt(cred.secret_enc) if cred.secret_enc else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/snowflake/{engine_name}/initiate")
async def initiate_oauth(engine_name: str, session: AsyncSession = Depends(get_session)):
    repo = SettingsRepo(session)
    app_cfg = await _load_app_config(repo, engine_name)
    if not app_cfg or not app_cfg.get("client_id"):
        raise HTTPException(
            status_code=400,
            detail=f"OAuth app not configured for '{engine_name}'. Configure client_id and client_secret in Settings first.",
        )

    try:
        engine_type, conn_cfg = _get_engine_type_and_cfg(engine_name)
        urls = _get_provider_urls(engine_type, conn_cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    redirect_uri = (
        app_cfg.get("redirect_uri") or "http://localhost:8100/api/oauth/snowflake/callback"
    )
    nonce = secrets.token_urlsafe(32)
    state_payload = orjson.dumps(
        {
            "engine_name": engine_name,
            "redirect_uri": redirect_uri,
            "token_url": urls["token_url"],
            "created_at": datetime.now(UTC).isoformat(),
        }
    ).decode()
    await repo.set(_state_key(nonce), state_payload)

    import urllib.parse

    auth_url = (
        f"{urls['authorize_url']}"
        f"?client_id={urllib.parse.quote(app_cfg['client_id'])}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(urls['default_scope'])}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&state={nonce}"
    )
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/snowflake/callback")
async def oauth_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    session: AsyncSession = Depends(get_session),
):
    repo = SettingsRepo(session)

    def _error_page(message: str) -> HTMLResponse:
        safe = message.replace("'", "\\'").replace("\n", " ")
        return HTMLResponse(
            content=f"""<!DOCTYPE html><html><body><script>
window.opener?.postMessage({{type:'snowflake_oauth_error',error:'{safe}'}}, '*');
window.close();
</script><p>Error: {message}</p></body></html>"""
        )

    if error:
        return _error_page(f"Snowflake denied access: {error}")
    if not code or not state:
        return _error_page("Missing code or state.")

    raw_state = await repo.get(_state_key(state))
    if not raw_state:
        return _error_page("Invalid or expired OAuth state. Please try again.")

    try:
        state_data = orjson.loads(raw_state)
        created_at = datetime.fromisoformat(state_data["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - created_at > timedelta(seconds=_STATE_TTL_SECONDS):
            await repo.delete(_state_key(state))
            return _error_page("OAuth state expired. Please try again.")
        engine_name = state_data["engine_name"]
        redirect_uri = state_data["redirect_uri"]
        token_url = state_data["token_url"]
    except Exception:
        return _error_page("Malformed OAuth state.")

    await repo.delete(_state_key(state))

    app_cfg = await _load_app_config(repo, engine_name)
    if not app_cfg:
        return _error_page(f"OAuth app config not found for engine '{engine_name}'.")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": app_cfg["client_id"],
                "client_secret": app_cfg["client_secret"],
                "redirect_uri": redirect_uri,
            },
        )

    if resp.status_code != 200:
        logger.error("Token exchange failed for %s: %s", engine_name, resp.text)
        return _error_page(f"Token exchange failed: {resp.text[:200]}")

    token_resp = resp.json()
    access_token = token_resp.get("access_token", "")
    refresh_token = token_resp.get("refresh_token", "")
    expires_in = token_resp.get("expires_in", 600)
    username = token_resp.get("username", "")
    token_type = token_resp.get("token_type", "Bearer")

    if not access_token:
        return _error_page("No access token in response.")

    cred_repo = CredentialRepo(repo._session)
    await _store_oauth_tokens(
        cred_repo, engine_name, access_token, refresh_token, expires_in, username, token_type
    )

    safe_engine = engine_name.replace("'", "\\'")
    safe_user = username.replace("'", "\\'")
    return HTMLResponse(
        content=f"""<!DOCTYPE html><html><body><script>
window.opener?.postMessage({{
  type: 'snowflake_oauth_success',
  engine: '{safe_engine}',
  username: '{safe_user}'
}}, '*');
window.close();
</script><p>Connected as {username}. You can close this window.</p></body></html>"""
    )


@router.get("/snowflake/{engine_name}/status")
async def oauth_status(engine_name: str, session: AsyncSession = Depends(get_session)):
    cred = await CredentialRepo(session).get(engine_name)
    if not cred:
        return {
            "oauth_available": False,
            "oauth_connected": False,
            "oauth_username": "",
            "oauth_expires_at": "",
            "oauth_expired": False,
        }
    return {
        "oauth_available": True,
        "oauth_connected": True,
        "oauth_username": cred.username or "",
        "oauth_expires_at": cred.expires_at.isoformat() if cred.expires_at else "",
        "oauth_expired": False,
    }


@router.delete("/snowflake/{engine_name}")
async def oauth_disconnect(engine_name: str, session: AsyncSession = Depends(get_session)):
    cred_repo = CredentialRepo(session)
    await cred_repo.delete(engine_name)
    return {"success": True, "message": "OAuth token removed."}


@router.put("/snowflake/{engine_name}/app")
async def configure_oauth_app(
    engine_name: str,
    body: OAuthAppConfig,
    session: AsyncSession = Depends(get_session),
):
    """Save (or update) the OAuth application credentials for an engine integration."""
    repo = SettingsRepo(session)

    # If client_secret is blank, preserve the existing one
    if not body.client_secret:
        existing = await _load_app_config(repo, engine_name)
        client_secret = existing["client_secret"] if existing else ""
    else:
        client_secret = body.client_secret

    if not body.client_id or not client_secret:
        raise HTTPException(status_code=400, detail="client_id and client_secret are required.")

    redirect_uri = body.redirect_uri or "http://localhost:8100/api/oauth/snowflake/callback"
    await _save_app_config(repo, engine_name, body.client_id, client_secret, redirect_uri)
    return {"success": True, "message": "OAuth app configuration saved."}


@router.delete("/snowflake/{engine_name}/app")
async def remove_oauth_app(engine_name: str, session: AsyncSession = Depends(get_session)):
    """Remove the OAuth app config AND any stored tokens for this engine."""
    repo = SettingsRepo(session)
    await repo.delete(_app_key(engine_name))
    cred_repo = CredentialRepo(session)
    await cred_repo.delete(engine_name)
    return {"success": True, "message": "OAuth app and tokens removed."}


class BrowserSsoRequest(BaseModel):
    account: str = ""  # override; falls back to engine config if blank
    user: str = ""  # optional hint; Snowflake fills it from the IdP token


class PatRequest(BaseModel):
    token: str
    username: str = ""


@router.put("/snowflake/{engine_name}/pat")
async def store_pat(
    engine_name: str, body: PatRequest, session: AsyncSession = Depends(get_session)
):
    """Store a Programmatic Access Token for a Snowflake connection."""
    import uuid

    if not body.token.strip():
        raise HTTPException(status_code=400, detail="token is required")
    cred_repo = CredentialRepo(session)
    await cred_repo.upsert(
        id=str(uuid.uuid4()),
        integration_name=engine_name,
        auth_type="pat",
        username=body.username or None,
        secret_enc=_encrypt(body.token.strip()),
    )
    return {"success": True, "message": "PAT stored."}


@router.post("/snowflake/{engine_name}/browser-sso")
async def browser_sso(
    engine_name: str,
    body: BrowserSsoRequest = BrowserSsoRequest(),
    session: AsyncSession = Depends(get_session),
):
    """
    Local-only: opens the system browser for Snowflake external browser SSO.
    No client_id/secret required — the connector handles the full OAuth dance.
    Blocks until the user authenticates (up to 120 seconds).
    """
    import asyncio
    import re as _re

    def _parse_account(raw: str) -> str:
        """Convert a Snowflake URL or raw account ID to the account identifier the connector expects."""
        s = raw.strip()
        # https://app.snowflake.com/<org>/<account>/...
        m = _re.search(r"app\.snowflake\.com/([^/]+)/([^/#?]+)", s, _re.IGNORECASE)
        if m:
            return f"{m.group(1)}-{m.group(2)}".lower()
        # https://<account>.snowflakecomputing.com
        m = _re.match(r"https?://([^.]+)\.snowflakecomputing\.com", s, _re.IGNORECASE)
        if m:
            return m.group(1)
        # Strip protocol and take first segment (handles plain account IDs)
        s = _re.sub(r"^https?://", "", s, flags=_re.IGNORECASE)
        return s.split(".")[0].split("/")[0]

    account = _parse_account(body.account) if body.account.strip() else ""
    user = body.user.strip()

    # Fall back to engine config for account (not user — SSO user ≠ service account)
    if not account:
        try:
            from analytics_agent.engines.factory import get_registry

            engine = get_registry().get(engine_name)
            if engine and hasattr(engine, "_cfg"):
                raw = engine._cfg.get("account", "")
                account = _parse_account(raw) if raw else ""
        except Exception:
            pass

    if not account:
        raise HTTPException(
            status_code=400,
            detail="Snowflake account not found. Enter it in the Account field above and save first.",
        )

    def _auth_in_browser() -> str:
        import snowflake.connector  # type: ignore

        connect_kwargs: dict = {
            "account": account,
            "authenticator": "externalbrowser",
            "login_timeout": 120,
        }
        if user:
            connect_kwargs["user"] = user

        try:
            conn = snowflake.connector.connect(**connect_kwargs)
        except Exception as e:
            err_str = str(e)
            # Try to extract the actual authenticated user from the error message
            # Snowflake returns something like "...user X differs from user Y..."
            import re as _re

            m = _re.search(
                r"currently logged in at the IDP[:\s]+([^\s.]+)", err_str, _re.IGNORECASE
            )
            if m:
                actual = m.group(1)
                raise Exception(
                    f"Username mismatch. You entered '{user}' but the IDP has you logged in as '{actual}'. "
                    f"Try again with username: {actual}"
                )
            raise

        cur = conn.cursor()
        cur.execute("SELECT CURRENT_USER()")
        row = cur.fetchone()
        snowflake_username = row[0] if row else (user or account)  # e.g. "SDAS"
        cur.close()

        # Keep connection alive in cache (keyed by account + IDP email, not Snowflake name)
        from analytics_agent.engines.snowflake.engine import store_sso_connection

        store_sso_connection(account, user or snowflake_username, conn)

        return snowflake_username

    try:
        snowflake_username = await asyncio.get_event_loop().run_in_executor(None, _auth_in_browser)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Browser SSO failed: {e}")

    import uuid

    cred_repo = CredentialRepo(session)
    # username = IDP email (used for externalbrowser reconnection next time)
    # snowflake_display = CURRENT_USER() result, stored in metadata for display only
    metadata = {"snowflake_user": snowflake_username} if snowflake_username != user else {}
    await cred_repo.upsert(
        id=str(uuid.uuid4()),
        integration_name=engine_name,
        auth_type="sso_externalbrowser",
        username=user or snowflake_username,  # IDP email for reconnection
        metadata_enc=orjson.dumps(metadata).decode() if metadata else None,
    )
    display_name = snowflake_username or user
    return {"success": True, "username": display_name}
