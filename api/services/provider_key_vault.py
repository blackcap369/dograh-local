"""Provider-key vault: encryption and vault-reference resolution.

Two jobs, and the isolation of both is the whole feature:

- Encrypt/decrypt/mask vault keys. Keys are encrypted at rest with Fernet
  keyed from VAULT_ENCRYPTION_KEY (falling back to OSS_JWT_SECRET -- both are
  operator-held secrets of this self-hosted instance). List responses carry
  only a masked preview; the raw key never leaves the server after save.
- Resolve `vault:{id}` references inside submitted model configurations. The
  frontend never sees the raw key: picking a saved key puts the opaque
  reference into the config, and the save path resolves it here. Resolution
  validates that the key belongs to the CALLER'S organization, so a
  cross-tenant reference fails closed.
"""

import base64
import hashlib
import os
import re

from cryptography.fernet import Fernet, InvalidToken

from api.db.models import ProviderKeyVaultModel

VAULT_REF_PATTERN = re.compile(r"^vault:(\d+)$")

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        secret = os.getenv("VAULT_ENCRYPTION_KEY") or os.getenv("OSS_JWT_SECRET")
        if not secret:
            raise ValueError(
                "VAULT_ENCRYPTION_KEY (or OSS_JWT_SECRET) must be set to use "
                "the provider key vault"
            )
        digest = hashlib.sha256(secret.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt_vault_key(raw_key: str) -> str:
    return _get_fernet().encrypt(raw_key.encode()).decode()


def decrypt_vault_key(encrypted_key: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted_key.encode()).decode()
    except Exception as exc:
        # InvalidToken, malformed base64, anything: a stored row that cannot
        # be decrypted must fail loudly rather than silently resolve to a
        # wrong key inside a live agent configuration. The usual cause is
        # VAULT_ENCRYPTION_KEY being rotated under stored rows.
        raise ValueError(
            "A saved API key could not be decrypted. If VAULT_ENCRYPTION_KEY "
            "was changed, saved keys must be re-entered."
        ) from exc


def mask_vault_key(encrypted_key: str) -> str:
    """A stable, non-reversible preview for list responses."""
    decrypted = decrypt_vault_key(encrypted_key)
    if len(decrypted) <= 8:
        return "••••"
    return f"••••{decrypted[-4:]}"


def vault_key_response_row(row: ProviderKeyVaultModel) -> dict:
    """The masked shape the list/create endpoints return."""
    return {
        "id": row.id,
        "service": row.service,
        "provider": row.provider,
        "alias": row.alias,
        "masked_key": mask_vault_key(row.encrypted_key),
        "created_at": getattr(row, "created_at", None),
    }


def extract_vault_ref(value: str) -> int | None:
    """The id inside a `vault:{id}` string, or None for anything else."""
    match = VAULT_REF_PATTERN.match(value.strip()) if isinstance(value, str) else None
    return int(match.group(1)) if match else None


async def resolve_vault_refs_in_config(
    config: dict, organization_id: int, db_client
) -> dict:
    """Walk a submitted configuration and replace every `vault:{id}` string
    with the decrypted key -- but only when the key belongs to the caller's
    organization. Handles str and list-of-str values (api_key is both
    depending on mode).
    """

    async def resolve_one(value: str) -> str:
        ref = extract_vault_ref(value)
        if ref is None:
            return value
        row = await db_client.get_vault_key(ref, organization_id)
        if row is None:
            raise ValueError(
                f"Saved API key {ref} does not exist in this organization"
            )
        return decrypt_vault_key(row.encrypted_key)

    async def walk(node):
        if isinstance(node, dict):
            return {key: await walk(val) for key, val in node.items()}
        if isinstance(node, list):
            return [await walk(item) for item in node]
        if isinstance(node, str) and VAULT_REF_PATTERN.match(node.strip()):
            return await resolve_one(node)
        return node

    return await walk(config)
