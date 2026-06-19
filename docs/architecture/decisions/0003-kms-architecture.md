# ADR-0003: KMS Architecture with Rust Pipeline Compatibility

## Status

Accepted

## Context

FraiseQL uses a high-performance Rust pipeline for JSON transformation (~6-17ms latency). Adding per-request KMS encryption would introduce 50-200ms latency penalty per call, making the framework unusably slow for real-time APIs.

The framework needs enterprise-grade encryption for sensitive data while maintaining the performance characteristics that make it competitive.

## Decision

Implement envelope encryption with startup-time key initialization:

1. **Startup Key Retrieval**: At application startup, request data encryption key (DEK) from KMS
2. **In-Memory Caching**: Cache plaintext DEK in application memory
3. **Local Encryption**: Use `local_encrypt`/`local_decrypt` for hot paths
4. **Background Rotation**: Rotate DEK periodically via background task

## Implementation

### Key Retrieval Flow

```python
# At startup
kms_provider = VaultKMSProvider(config)
data_key = await kms_provider.generate_data_key(key_id="fraiseql-data-key")
# data_key contains: plaintext_dek, encrypted_dek, key_id

# Cache for runtime use
self._cached_dek = data_key.plaintext
self._encrypted_dek = data_key.encrypted
```

### Runtime Encryption

```python
# Hot path - no KMS calls
encrypted_data = await local_encrypt(
    plaintext= sensitive_data,
    key=self._cached_dek
)
```

### Key Rotation

```python
async def rotate_keys(self):
    """Background task to rotate DEK."""
    new_key = await self.kms_provider.generate_data_key()
    # Atomically update cached key
    self._cached_dek = new_key.plaintext
    self._encrypted_dek = new_key.encrypted
    # Old encrypted DEK can be discarded
```

## Providers Supported

### HashiCorp Vault

```python
# Uses transit/datakey endpoint
response = await vault_client.post("/v1/transit/datakey/plaintext/my-key")
# Returns: plaintext (DEK), ciphertext (encrypted DEK)
```

### AWS KMS

```python
# Uses GenerateDataKey
response = await kms_client.generate_data_key(
    KeyId=key_id,
    KeySpec='AES_256'
)
# Returns: Plaintext (DEK), CiphertextBlob (encrypted DEK)
```

### GCP Cloud KMS

```python
# Local key generation + remote encryption
local_key = secrets.token_bytes(32)  # 256-bit AES key
encrypted_key = await kms_client.asymmetric_encrypt(
    name=key_version_name,
    plaintext=local_key
)
```

## Security Analysis

### Threat Model

- **Primary Threat**: DEK exposure in memory
- **Mitigation**: Short-lived keys, memory protection, container isolation
- **Acceptable Risk**: DEK lifetime measured in hours/days, not permanent

### Attack Vectors Considered

1. **Memory Dump Attack**: Container memory accessible
   - Mitigation: Short key lifetime, encrypted at rest, secure enclaves
2. **Side Channel Attack**: Timing/analysis of encryption operations
   - Mitigation: Constant-time algorithms, noise injection
3. **Key Rotation Failure**: Old keys not properly discarded
   - Mitigation: Atomic rotation, zero old keys from memory

## Performance Characteristics

### Latency Comparison

| Operation | Without KMS | With KMS (per-request) | With Envelope Encryption |
|-----------|-------------|------------------------|------------------------|
| JSON Transform | 6-17ms | 56-217ms (+50-200ms) | 6-17ms (no change) |
| Key Operations | N/A | 50-200ms | ~0ms (cached) |
| Startup Time | 100ms | 100ms | 150ms (+50ms for key fetch) |

### Memory Overhead

- **DEK Size**: 32 bytes (AES-256)
- **Encrypted DEK**: ~100-200 bytes
- **Total Memory**: < 1KB per application instance

## Consequences

### Positive

- ✅ **Maintains Performance**: No impact on hot path latency
- ✅ **Enterprise Security**: Full KMS integration with industry standards
- ✅ **Multi-Provider**: Vault, AWS, GCP support
- ✅ **Cost Effective**: KMS calls only at startup/rotation
- ✅ **Rust Compatible**: No changes needed to Rust pipeline

### Negative

- ❌ **Memory Key Storage**: DEK exists in plaintext in memory
- ❌ **Key Rotation Complexity**: Background task management
- ❌ **Startup Dependency**: KMS must be available at startup
- ❌ **Provider Differences**: GCP requires local key generation

### Neutral

- ⚪ **Operational Complexity**: Additional KMS management
- ⚪ **Monitoring Needs**: Key rotation health checks
- ⚪ **Provider Lock-in**: Architecture works with any envelope encryption KMS

## Alternatives Considered

### Option 1: Per-Request KMS Encryption

- **Pros**: Maximum security, no local key storage
- **Cons**: 50-200ms latency penalty, unusable for real-time APIs
- **Decision**: Rejected due to performance impact

### Option 2: Client-Side Encryption

- **Pros**: No server-side key management
- **Cons**: Complex client integration, key distribution challenges
- **Decision**: Rejected due to increased complexity

### Option 3: Database-Level Encryption

- **Pros**: Transparent encryption, PostgreSQL TDE
- **Cons**: Limited to PostgreSQL, no application control
- **Decision**: Rejected due to lack of flexibility

## Implementation Notes

### Key Rotation Strategy

- **Time-based**: Rotate every 24 hours
- **Size-based**: Rotate after N encryptions
- **Error-based**: Rotate on KMS errors
- **Manual**: API endpoint for immediate rotation

### Monitoring Requirements

```python
# Key rotation metrics
key_rotation_success_total
key_rotation_failure_total
key_age_seconds
kms_response_time_seconds
```

### Error Handling

- **Startup Failure**: Fail fast if KMS unavailable
- **Runtime Failure**: Fallback to local-only mode with alerts
- **Rotation Failure**: Alert but continue with old key

## Related Decisions

- **ADR-0002**: Ultra Direct Mutation Path - Performance-first architecture
- **ADR-0005**: Simplified Single Source CDC - Audit and observability

## References

- [AWS KMS Envelope Encryption](https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html#envelope_encryption)
- [HashiCorp Vault Transit Engine](https://developer.hashicorp.com/vault/docs/secrets/transit)
- [GCP Cloud KMS](https://cloud.google.com/kms/docs/envelope-encryption)
- [Envelope Encryption Best Practices](https://tools.ietf.org/html/rfc5652)

---

*Accepted: 2025-11-24*
*Review: Security and Performance Team*
