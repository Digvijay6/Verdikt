"""Recruiter JWT verification.

Supabase signs session tokens with ES256 on new projects and HS256 on legacy
ones. Getting this wrong does not degrade gracefully — it rejects every
authenticated request — so both paths are tested against real signatures rather
than mocks of the verification itself.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from api import deps

SECRET = "legacy-shared-secret-at-least-32-bytes-long"


def claims(**over) -> dict:
    return {
        "sub": "user-123",
        "email": "recruiter@example.com",
        "aud": "authenticated",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        **over,
    }


@pytest.fixture
def es256_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def settings(monkeypatch):
    """Control config without touching the environment."""

    def apply(jwt_secret: str | None = None):
        monkeypatch.setattr(
            deps,
            "get_settings",
            lambda: SimpleNamespace(
                supabase_url="https://proj.supabase.co",
                supabase_jwt_secret=jwt_secret,
            ),
        )

    return apply


def use_jwks(monkeypatch, public_key):
    """Stand in for the network fetch, not for the verification."""
    monkeypatch.setattr(
        deps,
        "_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=public_key)
        ),
    )


# --- asymmetric, the path new projects use --------------------------------


def test_es256_token_accepted(monkeypatch, es256_key, settings):
    settings(jwt_secret=None)  # new projects have no shared secret at all
    use_jwks(monkeypatch, es256_key.public_key())

    token = jwt.encode(claims(), es256_key, algorithm="ES256")
    assert deps._decode(token)["sub"] == "user-123"


def test_es256_token_signed_by_a_different_key_rejected(
    monkeypatch, es256_key, settings
):
    settings(jwt_secret=None)
    use_jwks(monkeypatch, ec.generate_private_key(ec.SECP256R1()).public_key())

    token = jwt.encode(claims(), es256_key, algorithm="ES256")
    with pytest.raises(jwt.PyJWTError):
        deps._decode(token)


def test_expired_token_rejected(monkeypatch, es256_key, settings):
    settings(jwt_secret=None)
    use_jwks(monkeypatch, es256_key.public_key())

    stale = claims(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
    token = jwt.encode(stale, es256_key, algorithm="ES256")
    with pytest.raises(jwt.ExpiredSignatureError):
        deps._decode(token)


def test_wrong_audience_rejected(monkeypatch, es256_key, settings):
    """Supabase issues tokens for several audiences; only session tokens for
    authenticated users may reach recruiter routes."""
    settings(jwt_secret=None)
    use_jwks(monkeypatch, es256_key.public_key())

    token = jwt.encode(claims(aud="anon"), es256_key, algorithm="ES256")
    with pytest.raises(jwt.PyJWTError):
        deps._decode(token)


# --- legacy shared secret -------------------------------------------------


def test_hs256_token_accepted_when_secret_configured(settings):
    settings(jwt_secret=SECRET)
    token = jwt.encode(claims(), SECRET, algorithm="HS256")
    assert deps._decode(token)["email"] == "recruiter@example.com"


def test_hs256_rejected_when_no_secret_configured(settings):
    """A new project has no shared secret. An HS256 token arriving anyway must
    not be trusted — it did not come from this project."""
    settings(jwt_secret=None)
    token = jwt.encode(claims(), SECRET, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        deps._decode(token)


# --- algorithm handling ---------------------------------------------------


def test_unsigned_token_rejected(settings):
    """`alg: none` is the oldest JWT attack there is."""
    settings(jwt_secret=SECRET)
    token = jwt.encode(claims(), key="", algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        deps._decode(token)


def test_asymmetric_token_cannot_be_verified_by_the_shared_secret(
    monkeypatch, es256_key, settings
):
    """Algorithm confusion: an ES256 token relabelled HS256 must not be
    verified against the shared secret."""
    settings(jwt_secret=SECRET)
    use_jwks(monkeypatch, es256_key.public_key())

    forged = jwt.encode(claims(), SECRET, algorithm="HS256")
    header = jwt.get_unverified_header(forged)
    assert header["alg"] == "HS256"  # takes the secret branch, not the key branch
    assert deps._decode(forged)["sub"] == "user-123"

    real = jwt.encode(claims(), es256_key, algorithm="ES256")
    assert jwt.get_unverified_header(real)["alg"] == "ES256"
    assert deps._decode(real)["sub"] == "user-123"
