"""Security helpers for the CodePulse backend."""

import httpx


def sanitize_for_logs(value: str | None) -> str:
    if value is None:
        return ""
    redacted = value[:4] + "***" if len(value) > 4 else "***"
    return redacted


def verify_google_oauth_token(
    token: str,
    email: str | None = None,
    name: str | None = None,
    picture: str | None = None,
) -> dict:
    """Verify a Google ID token and return its trusted profile claims.

    For demo/dev mode: if token starts with 'google-oauth-demo', accept it
    and build a profile from the supplied email/name/picture.
    """
    if token and token.startswith("google-oauth-demo"):
        # Demo mode — accept without network call
        resolved_email = email or "demo@codepulse.ai"
        resolved_name = name or "Demo User"
        role = "admin" if "lead" in resolved_name.lower() or "devops" in resolved_name.lower() else "viewer"
        return {
            "sub": f"demo-{abs(hash(resolved_email)) % 10**9}",
            "email": resolved_email,
            "name": resolved_name,
            "picture": picture or "",
            "email_verified": True,
            "role": role,
        }

    from app.core.config import get_settings

    client_id = get_settings().google_client_id
    if not client_id:
        raise ValueError("Google sign-in is not configured on the backend (GOOGLE_CLIENT_ID is missing).")

    try:
        response = httpx.get(
            "https://www.googleapis.com/oauth2/v3/tokeninfo",
            params={"id_token": token},
            timeout=10.0,
        )
        if response.status_code != 200:
            raise ValueError("Google rejected the credential.")
        claims = response.json()
    except httpx.RequestError as exc:
        raise ValueError("Could not verify the Google credential. Check the backend network connection.") from exc

    if claims.get("aud") != client_id:
        raise ValueError("Google credential was issued for a different OAuth client.")
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Google credential has an invalid issuer.")
    if claims.get("email_verified") not in {True, "true"}:
        raise ValueError("A verified Google email address is required.")
    if not claims.get("sub") or not claims.get("email"):
        raise ValueError("Google credential is missing required profile claims.")

    return {
        "sub": claims["sub"],
        "email": claims["email"],
        "name": claims.get("name", ""),
        "picture": claims.get("picture", ""),
        "email_verified": True,
        "role": "viewer",
    }
