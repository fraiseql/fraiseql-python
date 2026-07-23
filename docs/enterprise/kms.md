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
- **Envelope Encryption**: Local AES-256-GCM with encrypted master key
- **Automatic Provider Selection**: Transparently detect and use appropriate provider
- **Key Rotation**: Automated key rotation with backward compatibility
- **Field Encryption**: Convenient methods for encrypting individual fields
- **Compliance-Ready**: Works with security policies and audit logging

---

## Quick Start

### Vault Setup (Recommended)

```python
from fraiseql.security.kms import KeyManager, VaultKMSProvider, VaultConfig

# Configure Vault provider
vault_config = VaultConfig(
    vault_addr="https://vault.example.com:8200",
    token=os.getenv("VAULT_TOKEN"),
    mount_path="transit",  # Default: transit
    namespace="your-namespace"  # Optional
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

# Configure AWS KMS
aws_config = AWSKMSConfig(
    region="us-east-1",
    access_key=os.getenv("AWS_ACCESS_KEY_ID"),
    secret_key=os.getenv("AWS_SECRET_ACCESS_KEY")
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

# Configure GCP KMS
gcp_config = GCPKMSConfig(
    project_id="my-project",
    location="global",
    key_ring="my-keyring",
    credentials_file="/path/to/service-account.json"
)

key_manager = KeyManager(
    providers={"gcp": GCPKMSProvider(gcp_config)},
    default_provider="gcp",
    default_key_id="projects/my-project/locations/global/keyRings/my-keyring/cryptoKeys/my-key"
)

await key_manager.initialize()
```

### Using KMS in GraphQL

```python
# Add to GraphQL context
async def get_context() -> dict:
    return {
        "key_manager": key_manager,
        # ... other context
    }

@strawberry.mutation
async def create_user(
    info: strawberry.types.Info,
    email: str,
    password: str
) -> User:
    # Encrypt sensitive field
    encrypted_password = await info.context["key_manager"].encrypt_field(
        password,
        key_id="app-encryption-key"
    )

    return create_user_record(email, encrypted_password)
```

---

## Architecture

### Two Usage Patterns

FraiseQL KMS supports two distinct patterns depending on your security needs:

#### Pattern 1: Startup-Time Initialization (Recommended)

**Best for**: High-throughput applications, response data encryption

```python
# At startup: Contact KMS once to get data key
await key_manager.initialize()

# In request handlers: Use cached key (no KMS latency)
encrypted = key_manager.local_encrypt(data)  # Microseconds
decrypted = key_manager.local_decrypt(encrypted)  # Microseconds

# Periodically: Rotate the data key
scheduler.add_job(key_manager.rotate_data_key, trigger="interval", hours=1)
```

**Performance**:

- `initialize()`: 50-200ms (one-time at startup)
- `local_encrypt()`: < 1 microsecond
- `local_decrypt()`: < 1 microsecond
- `rotate_data_key()`: 50-200ms (background task)

**Envelope Encryption**:

```text
KMS stores: Master key (never leaves KMS)
Application stores: Data key (AES-256) encrypted by master key
Application RAM: Decrypted data key (for current hour)
```

#### Pattern 2: Per-Request KMS (High Security)

**Best for**: Secrets management, high-security keys, rare encryption

```python
# Every request: Contact KMS for encryption
encrypted = await key_manager.encrypt(
    plaintext,
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
- Master password hashing (rare)
- Credential storage (infrequent)
- Not suitable for response data (too slow)

### Local Encryption Algorithm

FraiseQL uses **AES-256-GCM** for local encryption:

```text
Plaintext
    ↓
Generate random 96-bit nonce
    ↓
Encrypt with AES-256-GCM (16KB buffer)
    ↓
Compute authentication tag (128-bit)
    ↓
Serialize: nonce + ciphertext + auth_tag
    ↓
Encrypted data
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
    tls_verify=True,               # TLS verification (recommended)
    tls_ca_cert="/path/to/ca.pem"  # Optional CA cert
)

provider = VaultKMSProvider(config)
```

**Vault Setup** (one-time):

```bash
# Enable transit secrets engine
vault secrets enable transit

# Create encryption key
vault write -f transit/keys/app-encryption-key

# Create policy for application
vault policy write app - <<EOF
path "transit/encrypt/app-encryption-key" {
  capabilities = ["update"]
}
path "transit/decrypt/app-encryption-key" {
  capabilities = ["update"]
}
path "transit/datakey/plaintext/app-encryption-key" {
  capabilities = ["read"]
}
EOF

# Generate AppRole credentials
vault auth enable approle
vault write auth/approle/role/app policies="app"
```

**Authentication Methods**:

- Token (shown above)
- Kubernetes auth (in K8s cluster)
- AppRole auth (recommended for CI/CD)

### AWS KMS

**Best for**: AWS-native deployments, AWS IAM integration

```python
from fraiseql.security.kms import AWSKMSConfig, AWSKMSProvider

config = AWSKMSConfig(
    region="us-east-1",
    access_key=os.getenv("AWS_ACCESS_KEY_ID"),
    secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    # OR use IAM role (no explicit credentials needed)
)

provider = AWSKMSProvider(config)
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
    credentials_file="/path/to/service-account.json"
    # OR use application default credentials (no file needed)
)

provider = GCPKMSProvider(config)
```

**Key ID Format**:

```text
projects/my-project/locations/global/keyRings/my-keyring/cryptoKeys/my-key
```

### Local Development KMS

**Best for**: Development, testing (not production!)

```python
from fraiseql.security.kms import LocalKMSConfig, LocalKMSProvider

config = LocalKMSConfig(
    master_key=b"development-master-key-32-bytes!"  # 32-byte key
)

provider = LocalKMSProvider(config)
```

**Warning**: Local KMS stores everything in-memory and is NOT suitable for production!

---

## Core Models

### KeyReference

Immutable reference to a key:

```python
@dataclass(frozen=True)
class KeyReference:
    provider: str              # "vault", "aws", "gcp"
    key_id: str                # Provider-specific key ID
    key_alias: str | None      # Human-readable alias
    purpose: KeyPurpose        # ENCRYPT_DECRYPT or SIGN_VERIFY
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
    ciphertext: bytes           # Encrypted data (nonce + ciphertext + tag)
    key_reference: KeyReference # Which key was used
    algorithm: str              # Provider-specific algorithm
    encrypted_at: datetime      # When encrypted
    context: dict[str, str]     # Additional authenticated data (optional)

    def to_dict(self) -> dict:
        """Serialize for storage (ciphertext as hex)"""
        return {
            "ciphertext": self.ciphertext.hex(),
            "key_reference": {
                "provider": self.key_reference.provider,
                "key_id": self.key_reference.key_id,
            },
            "algorithm": self.algorithm,
            "encrypted_at": self.encrypted_at.isoformat(),
            "context": self.context
        }
```

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

Key rotation configuration:

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
if key_manager.is_initialized:
    print("Ready to encrypt/decrypt")
```

### Hot-Path Encryption (No KMS)

```python
# Encrypt with cached key (microseconds)
encrypted_bytes = key_manager.local_encrypt(plaintext_bytes)

# Decrypt with cached key (microseconds)
plaintext_bytes = key_manager.local_decrypt(encrypted_bytes)
```

### Per-Request Encryption (With KMS)

```python
# Encrypt via KMS
encrypted_data = await key_manager.encrypt(
    plaintext=secret_string.encode(),
    key_id="api-key-encryption-key",
    provider="vault",  # Optional: explicit provider
    context={          # Optional: authenticated data
        "purpose": "api_key_storage",
        "environment": "production"
    }
)

# Store encrypted_data in database
db.save(encrypted_data.to_dict())

# Decrypt via KMS (reads key_reference from encrypted_data)
plaintext = await key_manager.decrypt(encrypted_data)
```

### Field Encryption

```python
# Encrypt a field
encrypted_password = await key_manager.encrypt_field(
    value="my-password",
    key_id="default-key",
    field_type="text"  # text, bytes, json
)

# Decrypt a field
password = await key_manager.decrypt_field(
    encrypted_password,
    field_type="text"
)
```

### Key Rotation

```python
# Rotate the cached data key (background task)
await key_manager.rotate_data_key()

# Schedule rotation
scheduler.add_job(
    key_manager.rotate_data_key,
    trigger="interval",
    hours=1  # Rotate hourly
)

# Get rotation status
policy = key_manager.get_rotation_policy()
print(f"Next rotation: {policy.next_rotation}")
```

### Generate Data Key Pair

```python
# For envelope encryption
key_pair = await key_manager.generate_data_key(
    key_id="master-key",
    key_spec="AES_256"  # Size of data key
)

# Use plaintext_key for encryption
encrypted = key_pair.encrypt(data)

# Store encrypted_key with data
db.save(encrypted_key=key_pair.encrypted_key)

# Later: Decrypt to get plaintext_key again
decrypted_key = await key_manager.decrypt(key_pair.encrypted_key)
```

---

## Algorithm Mapping

| Provider | Algorithm String | Actual Algorithm | Notes |
|----------|------------------|------------------|-------|
| Vault | `aes256-gcm96` | AES-256-GCM (96-bit IV) | Transit engine default |
| AWS KMS | `SYMMETRIC_DEFAULT` | AES-256-GCM | AWS managed |
| GCP KMS | `GOOGLE_SYMMETRIC_ENCRYPTION` | AES-256-GCM | GCP managed |
| Local | `aes256-gcm96` | AES-256-GCM (local) | Development only |

**Note**: Algorithm strings are provider-scoped. Don't compare `aes256-gcm96` from different providers - they're different implementations.

---

## Security Best Practices

### 1. Use Vault for Production

Vault is the recommended provider for production:

```python
# GOOD - Vault with secure token rotation
vault_provider = VaultKMSProvider(
    VaultConfig(
        vault_addr="https://vault.secure.example.com",
        token=os.getenv("VAULT_TOKEN"),
        tls_verify=True
    )
)

# BAD - Local KMS in production
local_provider = LocalKMSProvider(...)  # Development only!
```

### 2. Rotate Keys Regularly

Set up automated key rotation:

```python
# GOOD - Hourly rotation
scheduler.add_job(
    key_manager.rotate_data_key,
    trigger="interval",
    hours=1
)

# BAD - Manual or no rotation
# (forgotten rotations = outdated keys)
```

### 3. Use Encryption Context

Add additional authenticated data (AAD):

```python
# GOOD - Context for key derivation
encrypted = await key_manager.encrypt(
    secret,
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
api_key_encryption = await key_manager.encrypt(
    api_key,
    key_id="api-key-encryption-key"
)
password_hashing = await key_manager.encrypt(
    password,
    key_id="password-hashing-key"
)

# BAD - Single key for everything
secret = await key_manager.encrypt(api_key, key_id="universal-key")
password = await key_manager.encrypt(password, key_id="universal-key")
```

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

Enable TLS verification for KMS:

```python
# GOOD - TLS verification enabled
vault_config = VaultConfig(
    vault_addr="https://vault.example.com",
    tls_verify=True,
    tls_ca_cert="/etc/ssl/certs/ca-bundle.crt"
)

# BAD - TLS verification disabled
vault_config = VaultConfig(
    vault_addr="https://vault.example.com",
    tls_verify=False  # Security risk!
)
```

---

## Integration with GraphQL

### User Password Encryption

```python
@strawberry.mutation
async def register_user(
    info: strawberry.types.Info,
    email: str,
    password: str
) -> User:
    key_manager = info.context["key_manager"]

    # Encrypt password with KMS
    encrypted_password = await key_manager.encrypt_field(
        password,
        key_id="password-encryption-key"
    )

    # Store encrypted password
    user = User(
        email=email,
        encrypted_password=encrypted_password.to_dict()
    )
    await db.save(user)

    return user
```

### API Key Encryption

```python
@strawberry.mutation
async def generate_api_key(
    info: strawberry.types.Info,
    user_id: UUID  # UUID v4 for GraphQL ID
) -> ApiKeyResponse:
    key_manager = info.context["key_manager"]

    # Generate random API key
    api_key = secrets.token_urlsafe(32)

    # Encrypt with KMS
    encrypted_key = await key_manager.encrypt_field(
        api_key,
        key_id="api-key-encryption-key",
        context={"user_id": user_id}
    )

    # Store encrypted key (never store plaintext!)
    db_key = ApiKey(
        user_id=user_id,
        encrypted_key=encrypted_key.to_dict(),
        name=f"API Key ({api_key[:8]}...)"
    )
    await db.save(db_key)

    # Return plaintext key ONLY at creation time
    return ApiKeyResponse(api_key=api_key)
```

---

## Exception Handling

FraiseQL KMS defines specific exceptions:

```python
from fraiseql.security.kms import (
    KMSError,
    EncryptionError,
    DecryptionError,
    KeyNotFoundError,
    KeyRotationError,
    ProviderConnectionError
)

try:
    encrypted = await key_manager.encrypt(data)
except KeyNotFoundError:
    # Key doesn't exist
    logger.error("Key not found in KMS")
except ProviderConnectionError:
    # Can't reach KMS provider
    logger.error("KMS provider unreachable")
except EncryptionError as e:
    # General encryption failure
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
except ProviderConnectionError:
    print("Cannot reach Vault")
    # Check:
    # 1. Vault URL is correct
    # 2. Vault is running
    # 3. Network/firewall allows connection
    # 4. TLS certificate is valid
```

### Key Rotation Failures

```python
# Monitor rotation status
policy = key_manager.get_rotation_policy()

if policy.last_rotation is None:
    print("Never rotated - initialize first")

time_since_rotation = datetime.now() - policy.last_rotation
if time_since_rotation > timedelta(hours=2):
    print("Rotation may be delayed")
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

### Initialization Timeout

If `initialize()` times out:

```python
# Increase timeout
key_manager = KeyManager(
    providers=providers,
    initialization_timeout=10  # 10 seconds
)
```

### Rotation Frequency

Balance between security and performance:

```python
# More frequent (more secure, slight overhead)
scheduler.add_job(key_manager.rotate_data_key, trigger="interval", hours=1)

# Less frequent (slight overhead reduction, older keys)
scheduler.add_job(key_manager.rotate_data_key, trigger="interval", hours=12)

# Recommended: 1-4 hours for most applications
```

### Caching Strategy

```python
# Cache encrypted API keys (reduces KMS calls)
@cache.lru(maxsize=1000)
async def get_api_key_decrypted(api_key_id):
    encrypted = db.get_api_key(api_key_id)
    return await key_manager.decrypt(encrypted)

# Don't cache plaintext secrets (security risk)
# Always decrypt on demand for passwords/tokens
```

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
✅ **Envelope encryption** - Local AES-256-GCM with encrypted master key
✅ **Automatic provider selection** - Transparent multi-provider support
✅ **Key rotation** - Automated with backward compatibility
✅ **Field encryption** - Convenient API for common use cases
✅ **Compliance-ready** - NIST, PCI-DSS, HIPAA, ISO 27001
✅ **Production-grade** - Microsecond latency (cached), 50-200ms (per-request)

Perfect for encrypting sensitive data in production applications.
