

"""Tests de JWTClaimsAuthentication: la identidad del actor se arma
100% desde los claims del token, sin ningún acceso a BD."""
import pytest
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import AccessToken

from core.auth.jwt_claims_authentication import JWTClaimsAuthentication, TokenClaimsUser


def _make_request(auth_header=None):
    factory = APIRequestFactory()
    kwargs = {"HTTP_AUTHORIZATION": auth_header} if auth_header is not None else {}
    return factory.get("/", **kwargs)


def _make_token(
    *, user_id=1, username="tech1", role="TECNICO",
    include_username=True, include_role=True, is_active_technician=None,
):
    token = AccessToken()
    token["user_id"] = user_id
    if include_username:
        token["username"] = username
    if include_role:
        token["role"] = role
    if is_active_technician is not None:
        token["is_active_technician"] = is_active_technician
    return str(token)


class TestJWTClaimsAuthentication:
    def test_valid_token_builds_token_claims_user_without_db(self):
        raw = _make_token(user_id=7, username="tecnico7", role="TECNICO", is_active_technician=False)
        request = _make_request(f"Bearer {raw}")

        user, validated_token = JWTClaimsAuthentication().authenticate(request)

        assert isinstance(user, TokenClaimsUser)
        assert user.id == 7
        assert user.username == "tecnico7"
        assert user.role == "TECNICO"
        assert user.is_authenticated is True
        assert user.is_anonymous is False
        assert user.is_active_technician is False

    def test_is_active_technician_defaults_true_when_claim_absent(self):
        """Compatibilidad hacia atrás: un token emitido antes de agregar
        el claim no debe romper, se asume técnico activo por default."""
        raw = _make_token()
        request = _make_request(f"Bearer {raw}")

        user, _ = JWTClaimsAuthentication().authenticate(request)
        assert user.is_active_technician is True

    def test_missing_role_claim_rejected(self):
        raw = _make_token(include_role=False)
        request = _make_request(f"Bearer {raw}")

        with pytest.raises(AuthenticationFailed):
            JWTClaimsAuthentication().authenticate(request)

    def test_missing_username_claim_rejected(self):
        raw = _make_token(include_username=False)
        request = _make_request(f"Bearer {raw}")

        with pytest.raises(AuthenticationFailed):
            JWTClaimsAuthentication().authenticate(request)

    def test_no_auth_header_returns_none(self):
        request = _make_request(None)
        assert JWTClaimsAuthentication().authenticate(request) is None

    def test_malformed_header_rejected(self):
        request = _make_request("Bearer")
        with pytest.raises(AuthenticationFailed):
            JWTClaimsAuthentication().authenticate(request)

    def test_invalid_token_rejected(self):
        request = _make_request("Bearer not-a-real-token")
        with pytest.raises(InvalidToken):
            JWTClaimsAuthentication().authenticate(request)
