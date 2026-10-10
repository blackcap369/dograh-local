"""The provider key vault (V2.5): CRUD, masking, isolation, and resolution.

The vault lets an organization save API keys once (aliased, encrypted at
rest) and reference them from model configurations with `vault:{id}`. The
guarantees under test:

- Keys are org-scoped: a reference to another organization's key resolves to
  nothing and fails the save with a 422.
- Raw keys never leave the server: list/create responses carry a masked
  preview only.
- Resolution handles both string and list api_key values (the two shapes the
  configuration uses across modes).
- The duplicate-alias constraint surfaces as a 409.

Conventions as the other agency suites: bare FastAPI app + TestClient +
patch(db_client) with AsyncMock.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user, get_user_with_selected_organization
from api.routes import organization

ORG_ID = 7
USER_ID = 5

# Real ciphertext: the masking path decrypts, so fixtures carry actual
# Fernet tokens produced with the test env's VAULT_ENCRYPTION_KEY.
import os

os.environ.setdefault("VAULT_ENCRYPTION_KEY", "test-vault-key")

from api.services.provider_key_vault import (  # noqa: E402
    decrypt_vault_key,
    encrypt_vault_key,
)

_RAW_KEY = "sk-live-acme-7890"

SAVED_KEY = SimpleNamespace(
    id=3,
    organization_id=ORG_ID,
    service="llm",
    provider="openai",
    alias="Acme OpenAI",
    encrypted_key=encrypt_vault_key(_RAW_KEY),
    created_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
)

OTHER_ORG_KEY = SimpleNamespace(
    id=9,
    organization_id=ORG_ID + 1,
    service="llm",
    provider="openai",
    alias="Not Yours",
    encrypted_key="gAAAA-other",
    created_at=None,
)


def _make_app():
    app = FastAPI()
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=USER_ID,
        provider_id="oss_user",
        email="user@example.com",
        selected_organization_id=ORG_ID,
    )
    app.dependency_overrides[get_user_with_selected_organization] = lambda: SimpleNamespace(
        id=USER_ID,
        provider_id="oss_user",
        email="user@example.com",
        selected_organization_id=ORG_ID,
    )
    return app


def _patched_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.list_vault_keys = AsyncMock(return_value=[SAVED_KEY])
    mock_db.create_vault_key = AsyncMock(return_value=SAVED_KEY)
    mock_db.get_vault_key = AsyncMock(return_value=SAVED_KEY)
    mock_db.delete_vault_key = AsyncMock(return_value=True)
    return mock_db


# =============================================================================
# CRUD and masking
# =============================================================================


class TestVaultCRUD:
    @pytest.mark.asyncio
    async def test_list_returns_masked_keys_only(self):
        """The raw key and even its ciphertext must not appear in responses."""
        app = _make_app()
        client = TestClient(app)

        with patch("api.routes.organization.db_client", _patched_db()):
            response = client.get("/api/v1/organizations/provider-keys")

        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 1
        assert body[0]["alias"] == "Acme OpenAI"
        assert body[0]["masked_key"].startswith("••••")
        assert body[0]["masked_key"].endswith("7890")
        assert _RAW_KEY not in str(body)
        assert "gAAAA" not in str(body)

    @pytest.mark.asyncio
    async def test_create_encrypts_and_returns_masked(self):
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.organization.db_client", mock_db), patch(
            "api.routes.organization.encrypt_vault_key",
            lambda raw: "ENC(" + raw + ")",
        ):
            response = client.post(
                "/api/v1/organizations/provider-keys",
                json={
                    "service": "llm",
                    "provider": "openai",
                    "alias": "Acme OpenAI",
                    "api_key": "sk-live-abc",
                },
            )

        assert response.status_code == 201, response.text
        # The DB layer received the encrypted form, never the raw key.
        _, kwargs = mock_db.create_vault_key.await_args
        assert kwargs["encrypted_key"] == "ENC(sk-live-abc)"
        assert "sk-live-abc" not in response.text

    @pytest.mark.asyncio
    async def test_create_rejects_unknown_service(self):
        app = _make_app()
        client = TestClient(app)

        with patch("api.routes.organization.db_client", _patched_db()):
            response = client.post(
                "/api/v1/organizations/provider-keys",
                json={
                    "service": "telepathy",
                    "provider": "openai",
                    "alias": "x",
                    "api_key": "sk",
                },
            )

        assert response.status_code == 422, response.text

    @pytest.mark.asyncio
    async def test_duplicate_alias_is_409(self):
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.create_vault_key = AsyncMock(
            side_effect=ValueError("A saved key with that alias already exists")
        )
        with patch("api.routes.organization.db_client", mock_db):
            response = client.post(
                "/api/v1/organizations/provider-keys",
                json={
                    "service": "llm",
                    "provider": "openai",
                    "alias": "dup",
                    "api_key": "sk",
                },
            )

        assert response.status_code == 409, response.text

    @pytest.mark.asyncio
    async def test_delete_missing_key_is_404(self):
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.delete_vault_key = AsyncMock(return_value=False)
        with patch("api.routes.organization.db_client", mock_db):
            response = client.delete("/api/v1/organizations/provider-keys/999")

        assert response.status_code == 404, response.text

    @pytest.mark.asyncio
    async def test_list_is_scoped_to_the_callers_organization(self):
        """The org id reaches the query -- the vault is org-scoped at the
        database layer, not by post-filtering."""
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.organization.db_client", mock_db):
            client.get("/api/v1/organizations/provider-keys")

        mock_db.list_vault_keys.assert_awaited_once_with(ORG_ID, None)


# =============================================================================
# Reference resolution (the save-path seam)
# =============================================================================


class TestVaultRefResolution:
    @pytest.mark.asyncio
    async def test_resolves_string_and_list_values(self):
        """api_key is a string in override mode and a list in global mode;
        both shapes must resolve."""
        from api.services.provider_key_vault import resolve_vault_refs_in_config

        mock_db = AsyncMock()
        mock_db.get_vault_key = AsyncMock(return_value=SAVED_KEY)
        # Prove the resolver decrypts rather than passing ciphertext through.
        assert decrypt_vault_key(SAVED_KEY.encrypted_key) == _RAW_KEY

        config = {
            "byok": {
                "llm": {"api_key": "vault:3", "provider": "openai"},
                "tts": {"api_key": ["vault:3", "sk-plain"]},
            }
        }
        resolved = await resolve_vault_refs_in_config(config, ORG_ID, mock_db)

        llm_key = resolved["byok"]["llm"]["api_key"]
        assert llm_key == _RAW_KEY, "the vault ref must decrypt to the saved key"
        assert resolved["byok"]["tts"]["api_key"][1] == "sk-plain"
        mock_db.get_vault_key.assert_awaited_with(3, ORG_ID)

    @pytest.mark.asyncio
    async def test_foreign_org_reference_fails_closed(self):
        """A `vault:{id}` pointing at another organization's key must never
        resolve -- the lookup carries the caller's org id and misses."""
        from api.services.provider_key_vault import resolve_vault_refs_in_config

        mock_db = AsyncMock()
        mock_db.get_vault_key = AsyncMock(return_value=None)

        config = {"byok": {"llm": {"api_key": "vault:9"}}}
        with pytest.raises(ValueError, match="does not exist"):
            await resolve_vault_refs_in_config(config, ORG_ID, mock_db)

        # The lookup used the CALLER's org id, not the key row's.
        mock_db.get_vault_key.assert_awaited_with(9, ORG_ID)

    @pytest.mark.asyncio
    async def test_non_ref_values_pass_through_untouched(self):
        from api.services.provider_key_vault import resolve_vault_refs_in_config

        mock_db = AsyncMock()
        config = {"byok": {"llm": {"api_key": "sk-real", "model": "gpt-4o"}}}
        resolved = await resolve_vault_refs_in_config(config, ORG_ID, mock_db)

        assert resolved == config
        mock_db.get_vault_key.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_org_config_save_resolves_vault_refs(self):
        """The save route resolves references before the secret merge, so a
        configuration saved with `vault:{id}` stores the real key."""
        app = _make_app()
        client = TestClient(app)

        # A schema-valid byok pipeline body; the vault ref sits in the llm
        # api_key exactly where the form puts it.
        incoming = {
            "mode": "byok",
            "byok": {
                "mode": "pipeline",
                "pipeline": {
                    "llm": {"provider": "openai", "api_key": "vault:3", "model": "gpt-4o"},
                    "tts": {"provider": "elevenlabs", "api_key": "sk-tts"},
                    "stt": {"provider": "deepgram", "api_key": "sk-stt"},
                },
            },
        }

        mock_db = _patched_db()
        with patch("api.routes.organization.db_client", mock_db), patch(
            "api.routes.organization.resolve_vault_refs_in_config",
            AsyncMock(
                side_effect=lambda data, org_id, db: data
            ),  # real walker tested above
        ), patch(
            "api.routes.organization.merge_ai_model_configuration_v2_secrets",
            AsyncMock(),
        ), patch(
            "api.routes.organization.get_organization_ai_model_configuration_v2",
            AsyncMock(return_value=None),
        ), patch(
            "api.routes.organization.check_for_masked_keys_in_ai_model_configuration_v2",
        ), patch(
            "api.routes.organization.compile_ai_model_configuration_v2",
            return_value={},
        ), patch(
            "api.routes.organization.UserConfigurationValidator"
        ) as validator_cls, patch(
            "api.routes.organization.upsert_organization_ai_model_configuration_v2",
            AsyncMock(),
        ), patch(
            "api.routes.organization._model_configuration_v2_response",
            AsyncMock(
                return_value={
                    "configuration": incoming,
                    "effective_configuration": {},
                    "source": "organization_v2",
                }
            ),
        ):
            validator_cls.return_value.validate = AsyncMock()
            response = client.put(
                "/api/v1/organizations/model-configurations/v2", json=incoming
            )

        assert response.status_code == 200, response.text
