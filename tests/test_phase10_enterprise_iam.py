"""Phase 10 — Enterprise IAM & SSO — Test Suite.

All tests are self-contained: no network calls, no real Vault/IdP.
HTTP layer is stubbed with AsyncMock.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ["IRONCORE_EDITION"] = "enterprise"

from ironcore.enterprise.iam.sso_provider import (
    SSOConfig,
    SSOManager,
    SSOProvider,
    SSOUserInfo,
    _decode_jwt_claims_unverified,
    generate_pkce_pair,
)
from ironcore.enterprise.iam.vault_client import (
    CyberArkClient,
    DynamicCredential,
    VaultSecretsManager,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_sso(provider: SSOProvider = SSOProvider.AZURE_ENTRA, http_client=None, **kw) -> SSOManager:
    cfg = SSOConfig(
        provider=provider,
        client_id="app-client-id",
        client_secret="secret",
        tenant_id="my-tenant",
        redirect_uri="https://ironcore.internal/auth/callback",
        group_role_mapping={"IT-Admins": "admin", "RiskManagement": "approver"},
        **kw,
    )
    return SSOManager(provider=provider, config=cfg, http_client=http_client)


def _make_jwt(claims: Dict[str, Any]) -> str:
    """Create a fake JWT (unsigned) for testing claim extraction."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


def _vault(http_client: Any = None, **kw) -> VaultSecretsManager:
    defaults = dict(
        vault_url="https://vault.test:8200",
        role_id="role",
        secret_id="secret",
        http_client=http_client,
    )
    defaults.update(kw)
    return VaultSecretsManager(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
#  TestPKCE
# ══════════════════════════════════════════════════════════════════════════════

class TestPKCE:
    def test_generates_verifier_and_challenge(self) -> None:
        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_challenge_is_sha256_of_verifier(self) -> None:
        verifier, challenge = generate_pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == expected

    def test_pair_is_unique_each_call(self) -> None:
        pairs = {generate_pkce_pair()[0] for _ in range(10)}
        assert len(pairs) == 10

    def test_manager_exposes_pkce_helper(self) -> None:
        sso = _make_sso()
        verifier, challenge = sso.generate_pkce_pair()
        assert verifier and challenge


# ══════════════════════════════════════════════════════════════════════════════
#  TestSSOProvider — enum & config
# ══════════════════════════════════════════════════════════════════════════════

class TestSSOProvider:
    def test_all_provider_values_are_strings(self) -> None:
        for p in SSOProvider:
            assert isinstance(p.value, str)

    def test_sso_config_defaults(self) -> None:
        cfg = SSOConfig(
            provider=SSOProvider.OKTA,
            client_id="cid",
            client_secret="cs",
        )
        assert "openid" in cfg.scopes
        assert cfg.required_approvals if hasattr(cfg, "required_approvals") else True


# ══════════════════════════════════════════════════════════════════════════════
#  TestSSOManager — authorization URL
# ══════════════════════════════════════════════════════════════════════════════

class TestSSOManagerAuthURL:
    def test_azure_auth_url_contains_tenant(self) -> None:
        sso = _make_sso(SSOProvider.AZURE_ENTRA)
        url = sso.get_authorization_url("state123", "challenge456")
        assert "login.microsoftonline.com" in url
        assert "my-tenant" in url

    def test_auth_url_contains_client_id(self) -> None:
        sso = _make_sso()
        url = sso.get_authorization_url("s", "c")
        assert "app-client-id" in url

    def test_auth_url_contains_code_challenge(self) -> None:
        sso = _make_sso()
        _, challenge = generate_pkce_pair()
        url = sso.get_authorization_url("state", challenge)
        assert challenge in url

    def test_auth_url_contains_s256_method(self) -> None:
        sso = _make_sso()
        url = sso.get_authorization_url("s", "c")
        assert "S256" in url

    def test_okta_auth_url_contains_domain(self) -> None:
        cfg = SSOConfig(
            provider=SSOProvider.OKTA,
            client_id="cid",
            client_secret="cs",
            domain="myorg.okta.com",
            redirect_uri="https://app.internal/callback",
        )
        sso = SSOManager(SSOProvider.OKTA, cfg, http_client=None)
        url = sso.get_authorization_url("s", "c")
        assert "myorg.okta.com" in url

    def test_adfs_auth_url(self) -> None:
        cfg = SSOConfig(
            provider=SSOProvider.ACTIVE_DIRECTORY,
            client_id="cid",
            client_secret="cs",
            domain="adfs.bank.internal",
            redirect_uri="https://app.internal/callback",
        )
        sso = SSOManager(SSOProvider.ACTIVE_DIRECTORY, cfg, http_client=None)
        url = sso.get_authorization_url("s", "c")
        assert "adfs.bank.internal" in url

    def test_generic_oidc_without_discovery_url_raises(self) -> None:
        with pytest.raises(ValueError, match="discovery_url"):
            cfg = SSOConfig(
                provider=SSOProvider.GENERIC_OIDC,
                client_id="cid",
                client_secret="cs",
                redirect_uri="https://app.internal/callback",
            )
            SSOManager(SSOProvider.GENERIC_OIDC, cfg, http_client=None)

    def test_generic_oidc_with_discovery_url_ok(self) -> None:
        cfg = SSOConfig(
            provider=SSOProvider.GENERIC_OIDC,
            client_id="cid",
            client_secret="cs",
            redirect_uri="https://app.internal/callback",
            discovery_url="https://sso.myorg.com/oidc",
        )
        sso = SSOManager(SSOProvider.GENERIC_OIDC, cfg, http_client=None)
        url = sso.get_authorization_url("s", "c")
        assert "sso.myorg.com" in url


# ══════════════════════════════════════════════════════════════════════════════
#  TestSSOManagerExchangeCode
# ══════════════════════════════════════════════════════════════════════════════

class TestSSOManagerExchangeCode:
    @pytest.mark.asyncio
    async def test_no_http_client_returns_stub(self) -> None:
        sso = _make_sso()
        user = await sso.exchange_code("code1", "state1", "verifier1")
        assert isinstance(user, SSOUserInfo)
        assert user.email == "stub@example.com"

    @pytest.mark.asyncio
    async def test_exchange_with_http_client(self) -> None:
        claims = {"sub": "user-123", "email": "alice@bank.com", "name": "Alice"}
        id_token = _make_jwt(claims)
        token_resp = MagicMock()
        token_resp.json.return_value = {
            "access_token": "at-abc",
            "id_token": id_token,
            "expires_in": 3600,
        }
        groups_resp = MagicMock()
        groups_resp.json.return_value = {"value": [{"displayName": "IT-Admins"}]}

        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=token_resp)
        mock_http.get = AsyncMock(return_value=groups_resp)

        sso = _make_sso(http_client=mock_http)
        user = await sso.exchange_code("code1", "state1", "verifier1")

        assert user.sub == "user-123"
        assert user.email == "alice@bank.com"
        assert user.access_token == "at-abc"

    @pytest.mark.asyncio
    async def test_exchange_maps_groups_to_roles(self) -> None:
        claims = {"sub": "u1", "email": "u@b.com", "name": "User"}
        id_token = _make_jwt(claims)
        token_resp = MagicMock()
        token_resp.json.return_value = {
            "access_token": "at", "id_token": id_token, "expires_in": 3600
        }
        groups_resp = MagicMock()
        groups_resp.json.return_value = {"value": [{"displayName": "IT-Admins"}, {"displayName": "Unknown"}]}

        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=token_resp)
        mock_http.get = AsyncMock(return_value=groups_resp)

        sso = _make_sso(http_client=mock_http)
        user = await sso.exchange_code("code", "state", "verifier")

        assert "admin" in user.roles
        assert "approver" not in user.roles  # "Unknown" group has no mapping

    @pytest.mark.asyncio
    async def test_exchange_error_response_raises(self) -> None:
        token_resp = MagicMock()
        token_resp.json.return_value = {"error": "invalid_grant", "error_description": "Code expired"}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=token_resp)

        sso = _make_sso(http_client=mock_http)
        with pytest.raises(ValueError, match="Code expired"):
            await sso.exchange_code("bad-code", "state", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_missing_sub_raises(self) -> None:
        id_token = _make_jwt({"email": "u@b.com"})  # no 'sub'
        token_resp = MagicMock()
        token_resp.json.return_value = {
            "access_token": "at", "id_token": id_token, "expires_in": 3600
        }
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=token_resp)
        # groups call shouldn't be reached
        mock_http.get = AsyncMock(return_value=MagicMock(json=lambda: {"value": []}))

        sso = _make_sso(http_client=mock_http)
        with pytest.raises(ValueError, match="sub"):
            await sso.exchange_code("code", "state", "verifier")


# ══════════════════════════════════════════════════════════════════════════════
#  TestGroupRoleMapping
# ══════════════════════════════════════════════════════════════════════════════

class TestGroupRoleMapping:
    def test_known_group_maps_to_role(self) -> None:
        sso = _make_sso()
        roles = sso._map_groups_to_roles(["IT-Admins"])
        assert "admin" in roles

    def test_unknown_group_not_in_roles(self) -> None:
        sso = _make_sso()
        roles = sso._map_groups_to_roles(["SomeOtherGroup"])
        assert roles == []

    def test_multiple_groups_multiple_roles(self) -> None:
        sso = _make_sso()
        roles = sso._map_groups_to_roles(["IT-Admins", "RiskManagement"])
        assert "admin" in roles
        assert "approver" in roles

    def test_duplicate_roles_deduplicated(self) -> None:
        sso = _make_sso()
        roles = sso._map_groups_to_roles(["IT-Admins", "IT-Admins"])
        assert roles.count("admin") == 1


# ══════════════════════════════════════════════════════════════════════════════
#  TestJWTDecodeUnverified
# ══════════════════════════════════════════════════════════════════════════════

class TestJWTDecode:
    def test_decode_valid_jwt(self) -> None:
        claims = {"sub": "u1", "email": "u@b.com", "name": "User"}
        token = _make_jwt(claims)
        extracted = _decode_jwt_claims_unverified(token)
        assert extracted["sub"] == "u1"
        assert extracted["email"] == "u@b.com"

    def test_decode_invalid_returns_empty(self) -> None:
        assert _decode_jwt_claims_unverified("not.a.jwt") == {}

    def test_decode_empty_returns_empty(self) -> None:
        assert _decode_jwt_claims_unverified("") == {}

    def test_decode_single_part_returns_empty(self) -> None:
        assert _decode_jwt_claims_unverified("onlyonepart") == {}


# ══════════════════════════════════════════════════════════════════════════════
#  TestSSOEditionGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestSSOEditionGuard:
    def test_community_edition_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            _make_sso()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")

    def test_enterprise_edition_ok(self) -> None:
        sso = _make_sso()
        assert sso is not None


# ══════════════════════════════════════════════════════════════════════════════
#  TestSSOFromEnv
# ══════════════════════════════════════════════════════════════════════════════

class TestSSOFromEnv:
    def test_from_env_azure(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SSO_PROVIDER", "azure_entra")
        monkeypatch.setenv("IRONCORE_SSO_CLIENT_ID", "my-client")
        monkeypatch.setenv("IRONCORE_SSO_CLIENT_SECRET", "my-secret")
        monkeypatch.setenv("IRONCORE_SSO_TENANT_ID", "my-tenant")
        sso = SSOManager.from_env()
        assert sso._provider == SSOProvider.AZURE_ENTRA
        assert sso._config.client_id == "my-client"

    def test_from_env_okta(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SSO_PROVIDER", "okta")
        monkeypatch.setenv("IRONCORE_SSO_CLIENT_ID", "cid")
        monkeypatch.setenv("IRONCORE_SSO_CLIENT_SECRET", "cs")
        monkeypatch.setenv("IRONCORE_SSO_DOMAIN", "myorg.okta.com")
        monkeypatch.delenv("IRONCORE_SSO_TENANT_ID", raising=False)
        sso = SSOManager.from_env()
        assert sso._provider == SSOProvider.OKTA


# ══════════════════════════════════════════════════════════════════════════════
#  TestVaultSecretsManager
# ══════════════════════════════════════════════════════════════════════════════

class TestVaultSecretsManager:
    @pytest.mark.asyncio
    async def test_get_secret_no_client_returns_stub(self) -> None:
        v = _vault()
        result = await v.get_secret("llm/anthropic_api_key")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_secret_with_http_client(self) -> None:
        secret_resp = MagicMock()
        secret_resp.json.return_value = {"data": {"data": {"value": "sk-real-key"}}}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            json=lambda: {"auth": {"client_token": "tok", "lease_duration": 3600}}
        ))
        mock_http.get = AsyncMock(return_value=secret_resp)

        v = _vault(http_client=mock_http)
        result = await v.get_secret("llm/key")
        assert result == "sk-real-key"

    @pytest.mark.asyncio
    async def test_get_secret_missing_raises(self) -> None:
        empty_resp = MagicMock()
        empty_resp.json.return_value = {"data": {"data": {}}}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            json=lambda: {"auth": {"client_token": "tok", "lease_duration": 3600}}
        ))
        mock_http.get = AsyncMock(return_value=empty_resp)

        v = _vault(http_client=mock_http)
        with pytest.raises(KeyError, match="llm/missing"):
            await v.get_secret("llm/missing")

    @pytest.mark.asyncio
    async def test_dynamic_credential_no_client_returns_stub(self) -> None:
        v = _vault()
        cred = await v.get_dynamic_credential("db-readonly")
        assert isinstance(cred, DynamicCredential)
        assert cred.lease_id != ""
        assert cred.lease_duration > 0

    @pytest.mark.asyncio
    async def test_dynamic_credential_with_http_client(self) -> None:
        cred_resp = MagicMock()
        cred_resp.json.return_value = {
            "data": {"password": "temp-pw-xyz"},
            "lease_id": "database/creds/db-ro/abc123",
            "lease_duration": 600,
            "renewable": True,
        }
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            json=lambda: {"auth": {"client_token": "tok", "lease_duration": 3600}}
        ))
        mock_http.get = AsyncMock(return_value=cred_resp)

        v = _vault(http_client=mock_http)
        cred = await v.get_dynamic_credential("db-readonly")
        assert cred.value == "temp-pw-xyz"
        assert cred.lease_id == "database/creds/db-ro/abc123"

    @pytest.mark.asyncio
    async def test_revoke_credential_no_client_noop(self) -> None:
        v = _vault()
        # Should not raise
        await v.revoke_credential("database/creds/role/lease-123")

    @pytest.mark.asyncio
    async def test_revoke_credential_calls_http(self) -> None:
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            json=lambda: {"auth": {"client_token": "tok", "lease_duration": 3600}}
        ))
        mock_http.put = AsyncMock(return_value=MagicMock())

        v = _vault(http_client=mock_http)
        v._vault_token = "tok"
        v._token_expires_at = time.time() + 3600
        await v.revoke_credential("database/creds/role/lease-abc")
        mock_http.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_renew_token_updates_expiry(self) -> None:
        renew_resp = MagicMock()
        renew_resp.json.return_value = {"auth": {"lease_duration": 7200}}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=renew_resp)

        v = _vault(http_client=mock_http)
        v._vault_token = "existing-token"
        v._token_expires_at = time.time() + 60

        before = v._token_expires_at
        await v.renew_token()
        assert v._token_expires_at > before

    @pytest.mark.asyncio
    async def test_authenticate_caches_token(self) -> None:
        auth_resp = MagicMock()
        auth_resp.json.return_value = {
            "auth": {"client_token": "new-token", "lease_duration": 1800}
        }
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=auth_resp)

        v = _vault(http_client=mock_http)
        await v._authenticate()
        assert v._vault_token == "new-token"
        # Second call with valid token should NOT call authenticate again
        mock_http.post.reset_mock()
        await v._ensure_token()
        mock_http.post.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
#  TestVaultEditionGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestVaultEditionGuard:
    def test_community_edition_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            VaultSecretsManager()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")

    def test_enterprise_edition_ok(self) -> None:
        v = _vault()
        assert v is not None


# ══════════════════════════════════════════════════════════════════════════════
#  TestVaultFromEnv
# ══════════════════════════════════════════════════════════════════════════════

class TestVaultFromEnv:
    def test_from_env_url(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_VAULT_URL", "https://vault.mybank.com:8200")
        monkeypatch.setenv("IRONCORE_VAULT_ROLE_ID", "my-role")
        monkeypatch.setenv("IRONCORE_VAULT_SECRET_ID", "my-secret")
        v = VaultSecretsManager.from_env()
        assert v._vault_url == "https://vault.mybank.com:8200"
        assert v._role_id == "my-role"

    def test_from_env_mount_path(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_VAULT_MOUNT_PATH", "kv/ironcore")
        v = VaultSecretsManager.from_env()
        assert v._mount_path == "kv/ironcore"

    def test_from_env_namespace(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_VAULT_NAMESPACE", "bank-prod")
        v = VaultSecretsManager.from_env()
        assert v._namespace == "bank-prod"


# ══════════════════════════════════════════════════════════════════════════════
#  TestCyberArkClient
# ══════════════════════════════════════════════════════════════════════════════

class TestCyberArkClient:
    def test_edition_guard_community_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            CyberArkClient(base_url="https://cyberark.test", app_id="app")
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")

    @pytest.mark.asyncio
    async def test_get_credentials_no_client_returns_stub(self) -> None:
        ca = CyberArkClient(
            base_url="https://cyberark.test", app_id="IronCore", http_client=None
        )
        result = await ca.get_account_credentials("LLM-Safe", "anthropic-key")
        assert isinstance(result, str)
        assert "cyberark" in result.lower()

    @pytest.mark.asyncio
    async def test_get_credentials_with_http_client(self) -> None:
        cred_resp = MagicMock()
        cred_resp.json.return_value = {"Content": "real-api-key-abc123"}
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=cred_resp)

        ca = CyberArkClient(
            base_url="https://cyberark.test", app_id="IronCore", http_client=mock_http
        )
        result = await ca.get_account_credentials("LLM-Safe", "anthropic-key")
        assert result == "real-api-key-abc123"

    @pytest.mark.asyncio
    async def test_get_credentials_empty_response_raises(self) -> None:
        empty_resp = MagicMock()
        empty_resp.json.return_value = {"Content": ""}
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=empty_resp)

        ca = CyberArkClient(
            base_url="https://cyberark.test", app_id="IronCore", http_client=mock_http
        )
        with pytest.raises(KeyError, match="No credential"):
            await ca.get_account_credentials("Safe", "MissingObject")

    def test_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_CYBERARK_URL", "https://cyberark.mybank.com")
        monkeypatch.setenv("IRONCORE_CYBERARK_APP_ID", "IronCoreApp")
        ca = CyberArkClient.from_env()
        assert ca._base_url == "https://cyberark.mybank.com"
        assert ca._app_id == "IronCoreApp"


# ══════════════════════════════════════════════════════════════════════════════
#  TestDynamicCredential model
# ══════════════════════════════════════════════════════════════════════════════

class TestDynamicCredential:
    def test_fields(self) -> None:
        cred = DynamicCredential(
            value="temp-pass",
            lease_id="db/creds/role/abc",
            lease_duration=600,
            renewable=True,
        )
        assert cred.value == "temp-pass"
        assert cred.lease_duration == 600
        assert cred.renewable is True

    def test_default_renewable_true(self) -> None:
        cred = DynamicCredential(value="v", lease_id="l", lease_duration=60)
        assert cred.renewable is True


# ══════════════════════════════════════════════════════════════════════════════
#  TestIntegration — SSO + Vault in a realistic flow
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    @pytest.mark.asyncio
    async def test_vault_jit_pattern(self) -> None:
        """Fetch secret → use it → no persistent cache."""
        v = _vault()
        secret = await v.get_secret("sso/client_secret")
        assert secret  # not empty
        # After consumption, revoke (noop in stub)
        await v.revoke_credential("fake-lease-id")  # should not raise

    @pytest.mark.asyncio
    async def test_sso_full_stub_flow(self) -> None:
        """Full login flow with stub HTTP client."""
        sso = _make_sso()
        verifier, challenge = sso.generate_pkce_pair()
        url = sso.get_authorization_url("state-abc", challenge)
        assert "state-abc" in url

        # Simulate callback with code
        user = await sso.exchange_code("auth-code-xyz", "state-abc", verifier)
        assert user.sub.startswith("stub|")
        assert user.email == "stub@example.com"
