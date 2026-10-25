<!-- Skip to main content -->
---

title: Key Management Service (KMS) Documentation
description: FraiseQL's Key Management Service provides unified encryption/decryption across multiple KMS providers:
keywords: []
tags: ["documentation", "reference"]
---

# Key Management Service (KMS) Documentation

**Status:** ✅ Production Ready
**Topic**: Encryption Key Management
**Performance**: Microseconds (local), 50-200ms (per-request KMS)

---

## Overview

FraiseQL's Key Management Service provides unified encryption/decryption across multiple KMS providers:

- **Multiple Providers**: HashiCorp Vault, AWS KMS, GCP Cloud KMS, Local (dev)
- **Two Usage Patterns**: Startup-time initialization (fast) or per-request (secure)
- **Envelope Encryption**: Local AES-256-GCM with a data key wrapped by the KMS master key
- **Provider Tracking**: `decrypt()` uses the provider recorded in the `EncryptedData`
- **Key Rotation**: Replace the cached data key, or rotate the master key in the provider
- **Field Encryption**: Convenient methods for encrypting individual string or bytes fields

---

## Quick Start

### Vault Setup (Recommended)

```python
import os

from fraiseql.security.kms import KeyManager, VaultKMSProvider, VaultConfig

# Configure Vault provider
vault_config = VaultConfig(
    vault_addr="https://vault.example.com:8200",
    token=os.getenv("VAULT_TOKEN"),
    mount_path="transit",  # Default: transit
    namespace="your-namespace"  # Optional (Vault Enterprise)
)

# Create KMS with Vault
key_manager = KeyManager(
    providers={"vault": VaultKMSProvider(vault_config)},
    default_provider="vault",
    default_key_id="app-encryption-key"
)

# Initialize (generates cached data key)
await key_manager.initialize()
```

### AWS KMS Setup

```python
from fraiseql.security.kms import KeyManager, AWSKMSProvider, AWSKMSConfig

# Configure AWS KMS: credentials come from the boto3 default chain
# (IAM role, environment variables, ~/.aws), or from a named profile
aws_config = AWSKMSConfig(
    region_name="us-east-1",
    profile_name=None,  # e.g. "dev" for a local AWS profile
)

key_manager = KeyManager(
    providers={"aws": AWSKMSProvider(aws_config)},
    default_provider="aws",
    default_key_id="arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
)

await key_manager.initialize()
```

### GCP Cloud KMS Setup

```python
from fraiseql.security.kms import KeyManager, GCPKMSProvider, GCPKMSConfig

# Configure GCP KMS: credentials come from Application Default Credentials
# (GOOGLE_APPLICATION_CREDENTIALS, gcloud, or the workload's service account)
gcp_config = GCPKMSConfig(
    project_id="my-project",
    location="global",
    key_ring="my-keyring",
)

key_manager = KeyManager(
    providers={"gcp": GCPKMSProvider(gcp_config)},
    default_provider="gcp",
    default_key_id="my-key"  # the crypto key name inside key_ring
)

await key_manager.initialize()
```

### Using KMS in GraphQL

Initialize the key manager in the app's lifespan and put it in the GraphQL context
with `context_getter`; fraiseql merges what it returns into its default context
(`db`, `user`, ...):

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from fraiseql.fastapi import create_fraiseql_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    await key_manager.initialize()  # one KMS call at startup
    yield


async def get_context(request: Request) -> dict:
    return {"key_manager": key_manager}


app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[Customer, ApiKeyCreated],
    queries=[customer],
    mutations=[create_customer, generate_api_key],
    context_getter=get_context,
    lifespan=lifespan,
)
```

Resolvers then read `info.context["key_manager"]`; see
[Integration with GraphQL](#integration-with-graphql) for the mutations.

---

## Architecture

### Two Usage Patterns

FraiseQL KMS supports two distinct patterns depending on your security needs:

#### Pattern 1: Startup-Time Initialization (Recommended)

**Best for**: High-throughput applications, short-lived encrypted data

```python
# At startup: Contact KMS once to get data key
await key_manager.initialize()

# In request handlers: Use cached key (no KMS latency)
encrypted = key_manager.local_encrypt(data)  # Microseconds
decrypted = key_manager.local_decrypt(encrypted)  # Microseconds

# Periodically: replace the cached data key
await key_manager.rotate_data_key()
```

**Performance**:

- `initialize()`: 50-200ms (one-time at startup)
- `local_encrypt()`: < 1 microsecond
- `local_decrypt()`: < 1 microsecond
- `rotate_data_key()`: 50-200ms

**Envelope Encryption**:

```text
KMS stores: Master key (never leaves KMS)
KMS returns: A new AES-256 data key, plus that key wrapped by the master key
Application RAM: The plaintext data key, until the next initialize()/rotate_data_key()
```

The cached data key lives only in memory: `rotate_data_key()` (and a process
restart) replaces it, and `local_decrypt()` can no longer decrypt what the previous
key encrypted. Use `local_encrypt()` for data that doesn't outlive the key; for data
you persist, use `encrypt()` / `encrypt_field()` (Pattern 2), whose `EncryptedData`
records the KMS key, or keep a `DataKeyPair`'s wrapped key with the data
([Generate Data Key Pair](#generate-data-key-pair)).

#### Pattern 2: Per-Request KMS (High Security)

**Best for**: Secrets management, high-security keys, rare encryption

```python
# Every request: Contact KMS for encryption
encrypted = await key_manager.encrypt(
    plaintext,  # bytes
    key_id="high-security-key",
    context={"purpose": "api_key_encryption"}
)

# Decryption with context
plaintext = await key_manager.decrypt(encrypted, context={"purpose": "api_key_encryption"})
```

**Performance**:

- `encrypt()`: 50-200ms (contacts KMS)
- `decrypt()`: 50-200ms (contacts KMS)

**Use Cases**:

- API key encryption (rare, high-security)
- Credential storage (infrequent)
- Persisted sensitive fields
- Not suitable for response data (too slow)

### Local Encryption Algorithm

FraiseQL uses **AES-256-GCM** for local encryption:

```text
Plaintext
    ↓
Generate random 96-bit nonce
    ↓
Encrypt with AES-256-GCM (cached data key)
    ↓
Ciphertext with 128-bit authentication tag appended
    ↓
Serialize: nonce + ciphertext + auth_tag
    ↓
Encrypted bytes
```

**Security Properties**:

- **Confidentiality**: AES-256 (256-bit key)
- **Authenticity**: GCM authentication tag
- **Uniqueness**: Random nonce per encryption
- **No padding needed**: GCM stream cipher

---

## Supported KMS Providers

### HashiCorp Vault (Recommended)

**Best for**: Self-hosted, multi-cloud, fine-grained access control

```python
from fraiseql.security.kms import VaultConfig, VaultKMSProvider

config = VaultConfig(
    vault_addr="https://vault.example.com:8200",
    token=os.getenv("VAULT_TOKEN"),
    mount_path="transit",           # Custom: default is "transit"
    namespace="my-namespace",       # Optional
    verify_tls=True,                # TLS verification (default: True)
    timeout=30.0,                   # HTTP timeout in seconds (default: 30.0)
)

provider = VaultKMSProvider(config)
```

**Vault Setup** (one-time):

```bash
# Enable transit secrets engine
vault secrets enable transit

# Create encryption key
vault write -f transit/keys/app-encryption-key

# Create policy for application (fraiseql POSTs to these endpoints)
vault policy write app - <<EOF
path "transit/encrypt/app-encryption-key" {
  capabilities = ["update"]
}
path "transit/decrypt/app-encryption-key" {
  capabilities = ["update"]
}
path "transit/datakey/plaintext/app-encryption-key" {
  capabilities = ["update"]
}
EOF

# Generate AppRole credentials
vault auth enable approle
vault write auth/approle/role/app policies="app"
```

**Authentication**: `VaultKMSProvider` sends `VaultConfig.token` with each request.
Obtain the token however your deployment logs in to Vault (Kubernetes auth, AppRole,
...), and pass it in.

### AWS KMS

**Best for**: AWS-native deployments, AWS IAM integration

```python
from fraiseql.security.kms import AWSKMSConfig, AWSKMSProvider

config = AWSKMSConfig(
    region_name="us-east-1",  # Default: "us-east-1"
    profile_name=None,        # Optional named profile; else the boto3 default chain
)

provider = AWSKMSProvider(config)  # requires boto3
```

**Key ID Formats**:

```text
arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012
alias/my-encryption-key
12345678-1234-1234-1234-123456789012
```

**Permissions Required**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/*"
    }
  ]
}
```

### GCP Cloud KMS

**Best for**: GCP-native deployments, multi-region

```python
from fraiseql.security.kms import GCPKMSConfig, GCPKMSProvider

config = GCPKMSConfig(
    project_id="my-project",
    location="global",  # or "us", "eu", etc.
    key_ring="my-keyring",
)

provider = GCPKMSProvider(config)  # requires google-cloud-kms: pip install "fraiseql[kms-gcp]"
```

**Key ID Format**: pass the crypto key's name (`my-key`); the provider builds the
resource path from the config:

```text
projects/my-project/locations/global/keyRings/my-keyring/cryptoKeys/my-key
```

### Local Development KMS

**Best for**: Development, testing (not production!)

```python
from fraiseql.security.kms import LocalKMSConfig, LocalKMSProvider

config = LocalKMSConfig(
    master_key=b"development-master-key-32-bytes!"  # 32 bytes; default: random per process
)

provider = LocalKMSProvider(config)
```

**Warning**: Local KMS keeps its master key in memory and is NOT suitable for production!

---

## Core Models

### KeyReference

Immutable reference to a key:

```python
@dataclass(frozen=True)
class KeyReference:
    provider: str              # "vault", "aws", "gcp", "local"
    key_id: str                # Provider-specific key ID
    key_alias: str | None      # Human-readable alias
    purpose: KeyPurpose        # ENCRYPT_DECRYPT, SIGN_VERIFY or MAC
    created_at: datetime       # When key was created

    @property
    def qualified_id(self) -> str:
        return f"{provider}:{key_id}"
```

### EncryptedData

Immutable encrypted data with metadata:

```python
@dataclass(frozen=True)
class EncryptedData:
    ciphertext: bytes           # Encrypted data (provider format)
    key_reference: KeyReference # Which key was used
    algorithm: str              # Provider-specific algorithm
    encrypted_at: datetime      # When encrypted
    context: dict[str, str]     # Additional authenticated data (optional)

    def to_dict(self) -> dict:
        """Serialize for storage (ciphertext as hex)"""
        return {
            "ciphertext": self.ciphertext.hex(),
            "key_id": self.key_reference.qualified_id,  # "provider:key_id"
            "algorithm": self.algorithm,
            "encrypted_at": self.encrypted_at.isoformat(),
            "context": self.context
        }
```

There is no `from_dict`; [Reading Stored Ciphertext](#reading-stored-ciphertext)
shows how to rebuild an `EncryptedData` from what `to_dict()` stored.

### DataKeyPair

For envelope encryption:

```python
@dataclass(frozen=True)
class DataKeyPair:
    plaintext_key: bytes        # Use immediately, never persist
    encrypted_key: EncryptedData # Persist alongside data
    key_reference: KeyReference
```

### RotationPolicy

Key rotation configuration, returned by a provider's `get_rotation_policy()`:

```python
@dataclass(frozen=True)
class RotationPolicy:
    enabled: bool
    rotation_period_days: int
    last_rotation: datetime | None
    next_rotation: datetime | None
```

---

## API Methods

### Initialization

```python
# Generate cached data key via KMS
await key_manager.initialize()

# Check if initialized
if key_manager.has_cached_data_key():
    print("Ready to encrypt/decrypt")
```

### Hot-Path Encryption (No KMS)

```python
# Encrypt with cached key (microseconds)
encrypted_bytes = key_manager.local_encrypt(plaintext_bytes)

# Decrypt with cached key (microseconds)
plaintext_bytes = key_manager.local_decrypt(encrypted_bytes)
```

Both raise `RuntimeError` until `initialize()` has run.

### Per-Request Encryption (With KMS)

```python
# Encrypt via KMS
encrypted_data = await key_manager.encrypt(
    secret_string.encode(),
    key_id="api-key-encryption-key",
    provider="vault",  # Optional: explicit provider
    context={          # Optional: authenticated data
        "purpose": "api_key_storage",
        "environment": "production"
    }
)

# Store encrypted_data.to_dict() in a JSONB column (see Integration with GraphQL)
stored = encrypted_data.to_dict()

# Decrypt via KMS (uses the provider in encrypted_data.key_reference)
plaintext = await key_manager.decrypt(encrypted_data)
```

### Field Encryption

```python
# Encrypt a field (str or bytes)
encrypted_value = await key_manager.encrypt_field(
    "123-45-6789",
    key_id="default-key",
)

# Decrypt a field: returns str if a str was encrypted, bytes otherwise
value = await key_manager.decrypt_field(encrypted_value)
```

### Key Rotation

```python
# Replace the cached data key (local_decrypt can't read data the old key encrypted)
await key_manager.rotate_data_key()

# Rotate the master key in the provider, and read its rotation policy
provider = key_manager.get_provider("vault")
await provider.rotate_key("app-encryption-key")
policy = await provider.get_rotation_policy("app-encryption-key")
print(f"Rotation enabled: {policy.enabled}, next: {policy.next_rotation}")
```

### Generate Data Key Pair

```python
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# For envelope encryption
key_pair = await key_manager.generate_data_key(key_id="master-key")

# Use plaintext_key for encryption, then drop it
nonce = secrets.token_bytes(12)
ciphertext = AESGCM(key_pair.plaintext_key).encrypt(nonce, data, None)

# Store key_pair.encrypted_key.to_dict() with nonce and ciphertext

# Later: Decrypt the wrapped key to get plaintext_key again
plaintext_key = await key_manager.decrypt(key_pair.encrypted_key)
data = AESGCM(plaintext_key).decrypt(nonce, ciphertext, None)
```

---

## Algorithm Mapping

| Provider | Algorithm String | Actual Algorithm | Notes |
|----------|------------------|------------------|-------|
| Vault | `aes256-gcm96` | AES-256-GCM (96-bit IV) | Transit engine default |
| AWS KMS | `SYMMETRIC_DEFAULT` | AES-256-GCM | AWS managed |
| GCP KMS | `GOOGLE_SYMMETRIC_ENCRYPTION` | AES-256-GCM | GCP managed |
| Local | `AES-256-GCM` | AES-256-GCM (local) | Development only |

A wrapped data key (`DataKeyPair.encrypted_key`) has the algorithm `data-key`.

**Note**: Algorithm strings are provider-scoped. Don't compare algorithm strings from different providers - they're different implementations.

---

## Security Best Practices

### 1. Use Vault for Production

Vault is the recommended provider for production:

```python
# GOOD - Vault with TLS verification
vault_provider = VaultKMSProvider(
    VaultConfig(
        vault_addr="https://vault.secure.example.com",
        token=os.getenv("VAULT_TOKEN"),
        verify_tls=True
    )
)

# BAD - Local KMS in production
local_provider = LocalKMSProvider(...)  # Development only!
```

### 2. Rotate Keys Regularly

Rotate master keys in the provider (Vault, AWS and GCP keep old key versions, so
existing ciphertext still decrypts), on the provider's schedule or with
`provider.rotate_key(key_id)`. Replace the cached data key with
`rotate_data_key()` only as often as the data `local_encrypt()` produced can be
discarded.

### 3. Use Encryption Context

Add additional authenticated data (AAD); the same context is needed to decrypt:

```python
# GOOD - Context binds the ciphertext to its use
encrypted = await key_manager.encrypt(
    secret,  # bytes
    context={
        "purpose": "jwt_signing_key",
        "environment": "production",
        "customer": "customer-123"
    }
)

# BAD - No context (less secure)
encrypted = await key_manager.encrypt(secret)
```

### 4. Separate Key Per Purpose

Use different keys for different purposes:

```python
# GOOD - Key per purpose
api_key_encryption = await key_manager.encrypt_field(
    api_key,
    key_id="api-key-encryption-key"
)
tax_id_encryption = await key_manager.encrypt_field(
    tax_id,
    key_id="customer-pii-key"
)

# BAD - Single key for everything
secret = await key_manager.encrypt_field(api_key, key_id="universal-key")
pii = await key_manager.encrypt_field(tax_id, key_id="universal-key")
```

Store password hashes (bcrypt, argon2), not encrypted passwords.

### 5. Never Log Plaintext Keys

Prevent accidental key exposure:

```python
# GOOD - Don't log secrets
try:
    decrypted = await key_manager.decrypt(encrypted_data)
except DecryptionError as e:
    logger.error(f"Decryption failed: {e}")  # Don't log plaintext

# BAD - Logs plaintext key
logger.debug(f"Decrypted key: {decrypted_key}")  # SECURITY RISK!
```

### 6. Verify TLS Certificates

Keep TLS verification on for Vault (the default):

```python
# GOOD - TLS verification enabled
vault_config = VaultConfig(
    vault_addr="https://vault.example.com",
    token=os.getenv("VAULT_TOKEN"),
    verify_tls=True
)

# BAD - TLS verification disabled
vault_config = VaultConfig(
    vault_addr="https://vault.example.com",
    token=os.getenv("VAULT_TOKEN"),
    verify_tls=False  # Security risk!
)
```

---

## Integration with GraphQL

These mutations store ciphertext through PostgreSQL functions, with the app from
[Using KMS in GraphQL](#using-kms-in-graphql) putting `key_manager` in the context.

```sql
CREATE TABLE tb_customer (
    pk_customer BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    tax_id JSONB NOT NULL  -- EncryptedData.to_dict(), never the plaintext
);

CREATE FUNCTION fn_create_customer(input JSONB, OUT id UUID) AS $$
BEGIN
    INSERT INTO tb_customer (email, tax_id)
    VALUES (input->>'email', input->'tax_id')
    RETURNING tb_customer.id INTO id;
END;
$$ LANGUAGE plpgsql;

CREATE VIEW v_customer AS
SELECT id, jsonb_build_object('id', id, 'email', email) AS data
FROM tb_customer;

CREATE TABLE tb_api_key (
    pk_api_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    encrypted_key JSONB NOT NULL  -- EncryptedData.to_dict()
);

CREATE FUNCTION fn_create_api_key(input JSONB, OUT id UUID) AS $$
BEGIN
    INSERT INTO tb_api_key (user_id, name, encrypted_key)
    VALUES ((input->>'user_id')::uuid, input->>'name', input->'encrypted_key')
    RETURNING tb_api_key.id INTO id;
END;
$$ LANGUAGE plpgsql;
```

### Sensitive Field Encryption

```python
import fraiseql
from fraiseql.types import ID


@fraiseql.type(sql_source="v_customer", jsonb_column="data")
class Customer:
    id: ID
    email: str


@fraiseql.query
async def customer(info, id: ID) -> Customer | None:
    db = info.context["db"]
    return await db.find_one("v_customer", mandatory_filters={"id": id})


@fraiseql.mutation
async def create_customer(info, email: str, tax_id: str) -> Customer:
    key_manager = info.context["key_manager"]
    db = info.context["db"]

    # Encrypt with KMS; the ciphertext is stored, never the plaintext
    encrypted_tax_id = await key_manager.encrypt_field(
        tax_id,
        key_id="customer-pii-key",
        context={"purpose": "tax_id"},
    )

    # fn_create_customer(input jsonb, OUT id uuid) inserts into tb_customer
    result = await db.execute_function(
        "fn_create_customer",
        {"email": email, "tax_id": encrypted_tax_id.to_dict()},
    )
    return await db.find_one(
        "v_customer", "createCustomer", info, mandatory_filters={"id": result["id"]}
    )
```

### API Key Encryption

```python
import secrets


@fraiseql.type
class ApiKeyCreated:
    id: ID
    api_key: str  # returned once, at creation


@fraiseql.mutation
async def generate_api_key(info, user_id: ID, name: str) -> ApiKeyCreated:
    key_manager = info.context["key_manager"]
    db = info.context["db"]

    # Generate random API key
    api_key = secrets.token_urlsafe(32)

    # Encrypt with KMS
    encrypted_key = await key_manager.encrypt_field(
        api_key,
        key_id="api-key-encryption-key",
        context={"user_id": str(user_id)},
    )

    # Store the encrypted key (never the plaintext)
    result = await db.execute_function(
        "fn_create_api_key",
        {"user_id": str(user_id), "name": name, "encrypted_key": encrypted_key.to_dict()},
    )

    # Return the plaintext key ONLY at creation time
    return ApiKeyCreated(id=result["id"], api_key=api_key)
```

### Reading Stored Ciphertext

`to_dict()` keeps everything `decrypt()` needs; rebuild the `EncryptedData` from the
stored JSONB:

```python
from datetime import datetime

from fraiseql.security.kms import EncryptedData, KeyPurpose, KeyReference


def encrypted_data_from_dict(data: dict) -> EncryptedData:
    """Rebuild the EncryptedData that to_dict() serialized."""
    provider, key_id = data["key_id"].split(":", 1)  # qualified id "provider:key_id"
    encrypted_at = datetime.fromisoformat(data["encrypted_at"])
    return EncryptedData(
        ciphertext=bytes.fromhex(data["ciphertext"]),
        key_reference=KeyReference(
            provider=provider,
            key_id=key_id,
            key_alias=None,
            purpose=KeyPurpose.ENCRYPT_DECRYPT,
            created_at=encrypted_at,
        ),
        algorithm=data["algorithm"],
        encrypted_at=encrypted_at,
        context=data["context"],
    )


# e.g. with the tax_id column of a tb_customer row
tax_id = await key_manager.decrypt_field(encrypted_data_from_dict(row["tax_id"]))
```

---

## Exception Handling

FraiseQL KMS defines specific exceptions, all subclasses of `KMSError`:

```python
from fraiseql.security.kms import (
    KMSError,
    EncryptionError,
    DecryptionError,
    KeyNotFoundError,
    KeyRotationError,
    ProviderConnectionError
)
```

The provider operations surface one exception each, with the specific cause
(`KeyNotFoundError`, `ProviderConnectionError`, a client library error) chained as
`__cause__`:

| Operation | Raises |
|-----------|--------|
| `encrypt()`, `encrypt_field()`, `generate_data_key()`, `initialize()`, `rotate_data_key()` | `EncryptionError` |
| `decrypt()`, `decrypt_field()` | `DecryptionError` |
| `provider.rotate_key()` | `KeyRotationError` |
| `local_encrypt()` / `local_decrypt()` before `initialize()` | `RuntimeError` |
| `local_decrypt()` of tampered data or data from another data key | `cryptography.exceptions.InvalidTag` |
| unknown `provider=` name | `ValueError` |

```python
try:
    encrypted = await key_manager.encrypt(data)
except EncryptionError as e:
    if isinstance(e.__cause__, KeyNotFoundError):
        logger.error("Key not found in KMS")
    elif isinstance(e.__cause__, ProviderConnectionError):
        logger.error("KMS provider unreachable")
    else:
        logger.error(f"Encryption failed: {e}")
```

---

## Troubleshooting

### Vault Connection Issues

```python
# Check connection
try:
    await key_manager.initialize()
    print("Vault connected")
except EncryptionError as e:
    print(f"Cannot get a data key from Vault: {e.__cause__!r}")
    # Check:
    # 1. Vault URL is correct
    # 2. Vault is running
    # 3. Network/firewall allows connection
    # 4. TLS certificate is valid
    # 5. The token's policy allows transit/datakey/plaintext/<key>
```

### Key Rotation Status

```python
# Ask the provider for the master key's rotation policy
policy = await key_manager.get_provider("vault").get_rotation_policy("app-encryption-key")

if not policy.enabled:
    print("Automatic rotation is off for this key")
elif policy.last_rotation is None:
    print("Never rotated")
```

### Decryption Errors

```python
# Common causes:
# 1. Wrong key used
# 2. Encrypted with different provider
# 3. Data corruption
# 4. Context mismatch

try:
    await key_manager.decrypt(encrypted_data)
except DecryptionError:
    # Inspect encrypted_data
    print(f"Provider: {encrypted_data.key_reference.provider}")
    print(f"Algorithm: {encrypted_data.algorithm}")
    print(f"Context: {encrypted_data.context}")
```

---

## Performance Tuning

### Request Timeout

If `initialize()` or `encrypt()` times out against Vault, raise the HTTP timeout:

```python
vault_config = VaultConfig(
    vault_addr="https://vault.example.com:8200",
    token=os.getenv("VAULT_TOKEN"),
    timeout=10.0,  # seconds (default: 30.0)
)
```

### Rotation Frequency

A shorter cached-data-key lifetime limits how much data one key protects, but each
`rotate_data_key()` is a KMS call and makes earlier `local_encrypt()` output
unreadable: pick the interval from how long that data must stay readable.

### Caching Strategy

Decrypted secrets that are reused (for example a third-party API key the app calls
with) can be cached in memory to save KMS calls; don't cache decrypted passwords or
per-user tokens, decrypt them on demand.

---

## Compliance & Standards

FraiseQL KMS supports:

- **NIST 800-53**: Encryption controls (SC-7, SC-12, SC-13)
- **PCI-DSS**: Encryption at rest (Requirement 3.4)
- **HIPAA**: Encryption key management (§164.312(a)(2)(i))
- **ISO 27001**: Cryptography management (A.10.1)
- **SOC 2**: Encryption controls
- **FedRAMP**: FIPS-approved algorithms

---

## Summary

FraiseQL KMS provides:

✅ **Multiple providers** - Vault, AWS, GCP, Local
✅ **Two patterns** - Fast (local) and secure (per-request)
✅ **Envelope encryption** - Local AES-256-GCM with a KMS-wrapped data key
✅ **Provider tracking** - `EncryptedData` records the provider and key that encrypted it
✅ **Key rotation** - Cached data key replacement and provider master-key rotation
✅ **Field encryption** - Convenient API for common use cases
✅ **Compliance-ready** - NIST, PCI-DSS, HIPAA, ISO 27001
✅ **Production-grade** - Microsecond latency (cached), 50-200ms (per-request)

Perfect for encrypting sensitive data in production applications.
