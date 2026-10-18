"""Compliance Demo Application
============================

Demonstrates:
- Cryptographic audit trails with HMAC chains
- SLSA provenance verification
- KMS integration patterns
- Immutable audit logs for compliance

Usage:
    python main.py

Then visit: http://localhost:8000/graphql
"""

import os
from datetime import datetime
from uuid import UUID

from fraiseql import FraiseQL, create_fraiseql_app
from fraiseql.security import SecurityProfile
from fraiseql.types import ID

# ============================================================================
# CONFIGURATION
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/compliance_demo")

# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

fraiseql = FraiseQL()


@fraiseql.type(sql_source="v_document")
class Document:
    """Document with integrity checksum."""

    id: ID
    title: str
    content: str
    classification: str  # public, confidential, secret
    created_by: str
    created_at: datetime
    updated_at: datetime
    version: int
    checksum: str  # SHA-256 hash


@fraiseql.type(sql_source="tv_document")
class DocumentWithAudit:
    """Document with audit statistics."""

    id: ID
    title: str
    content: str
    classification: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    version: int
    checksum: str
    audit_count: int
    last_audit_at: datetime | None


@fraiseql.type(sql_source="v_audit_trail")
class AuditEntry:
    """Cryptographic audit trail entry."""

    id: ID
    sequence_number: int
    event_type: str
    resource_type: str
    resource_id: ID
    actor: str
    action_details: dict
    ip_address: str | None
    user_agent: str | None
    timestamp: datetime
    previous_hash: str | None
    current_hash: str
    hmac_signature: str
    compliance_markers: dict | None
    retention_until: datetime | None


@fraiseql.type(sql_source="tv_audit_trail")
class AuditEntryWithValidation:
    """Audit entry with chain validation."""

    id: ID
    sequence_number: int
    event_type: str
    resource_type: str
    resource_id: ID
    actor: str
    action_details: dict
    timestamp: datetime
    current_hash: str
    hmac_signature: str
    compliance_markers: dict | None
    chain_valid: bool  # Computed: validates chain integrity


@fraiseql.type(sql_source="v_slsa_provenance")
class SLSAProvenance:
    """SLSA provenance attestation."""

    id: ID
    artifact_name: str
    artifact_version: str
    artifact_digest: str
    build_type: str
    builder_id: str
    source_repo: str
    source_commit: str
    verified: bool
    verified_at: datetime | None
    created_at: datetime


@fraiseql.type(sql_source="v_kms_key")
class KMSKey:
    """KMS key metadata."""

    id: ID
    key_id: str
    key_provider: str  # aws-kms, gcp-kms, hashicorp-vault
    key_purpose: str  # audit-signing, data-encryption, document-signing
    key_algorithm: str
    key_status: str  # active, rotated, revoked
    created_at: datetime
    rotated_at: datetime | None


# ============================================================================
# QUERIES
# ============================================================================


@fraiseql.query
class Query:
    """Root query type."""

    @fraiseql.field
    async def documents(
        self,
        info,
        classification: str | None = None,
        limit: int = 50,
    ) -> list[Document]:
        """List documents, optionally filtered by classification."""
        db = fraiseql.get_db(info.context)
        where = {}
        if classification:
            where["classification"] = classification
        return await db.find("v_document", where=where, limit=limit)

    @fraiseql.field
    async def document(self, info, id: ID) -> DocumentWithAudit | None:
        """Get single document with audit statistics."""
        db = fraiseql.get_db(info.context)
        return await db.find_one("tv_document", where={"id": id})

    @fraiseql.field
    async def audit_trail(
        self,
        info,
        resource_type: str | None = None,
        resource_id: ID | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """List audit trail entries.

        Filters:
        - resource_type: Filter by resource type (document, user, etc.)
        - resource_id: Filter by specific resource ID
        """
        db = fraiseql.get_db(info.context)
        where = {}
        if resource_type:
            where["resource_type"] = resource_type
        if resource_id:
            where["resource_id"] = resource_id
        return await db.find(
            "v_audit_trail",
            where=where,
            limit=limit,
            order_by=[("sequence_number", "DESC")],
        )

    @fraiseql.field
    async def audit_chain_validation(
        self, info
    ) -> list[AuditEntryWithValidation]:
        """Get audit trail with chain validation status.

        Each entry includes 'chain_valid' boolean indicating
        whether the cryptographic chain is intact.
        """
        db = fraiseql.get_db(info.context)
        return await db.find(
            "tv_audit_trail",
            limit=1000,
            order_by=[("sequence_number", "ASC")],
        )

    @fraiseql.field
    async def slsa_provenance(
        self,
        info,
        artifact_name: str | None = None,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[SLSAProvenance]:
        """List SLSA provenance attestations.

        Filters:
        - artifact_name: Filter by artifact name
        - verified_only: Show only verified attestations
        """
        db = fraiseql.get_db(info.context)
        where = {}
        if artifact_name:
            where["artifact_name"] = artifact_name
        if verified_only:
            where["verified"] = True
        return await db.find("v_slsa_provenance", where=where, limit=limit)

    @fraiseql.field
    async def kms_keys(
        self,
        info,
        provider: str | None = None,
        status: str | None = None,
    ) -> list[KMSKey]:
        """List KMS keys.

        Filters:
        - provider: aws-kms, gcp-kms, hashicorp-vault
        - status: active, rotated, revoked
        """
        db = fraiseql.get_db(info.context)
        where = {}
        if provider:
            where["key_provider"] = provider
        if status:
            where["key_status"] = status
        return await db.find("v_kms_key", where=where)


# ============================================================================
# MUTATIONS
# ============================================================================


@fraiseql.mutation(name="createDocument", function="fn_create_document", enable_cascade=True)
class CreateDocument:
    """Create document with automatic audit trail.

    CASCADE enabled: Returns updated document with audit count.
    """

    title: str
    content: str
    classification: str
    created_by: str


@fraiseql.mutation(name="recordSLSAProvenance", function="fn_record_slsa_provenance")
class RecordSLSAProvenance:
    """Record SLSA provenance attestation."""

    artifact_name: str
    artifact_version: str
    artifact_digest: str
    build_type: str
    source_commit: str
    attestation: str


# ============================================================================
# CUSTOM ENDPOINTS
# ============================================================================


from fastapi import HTTPException
from fastapi.responses import JSONResponse


@fraiseql.app.get("/compliance/verify-audit-chain")
async def verify_audit_chain():
    """Verify integrity of cryptographic audit chain.

    Returns:
        - total_entries: Total audit entries
        - valid_entries: Entries with valid chain links
        - invalid_entries: Entries with broken chain links
        - chain_intact: Overall chain integrity status
    """
    from asyncpg import create_pool

    pool = await create_pool(DATABASE_URL)
    try:
        results = await pool.fetch("SELECT * FROM fn_verify_audit_chain()")

        total = len(results)
        valid = sum(1 for r in results if r["valid"])
        invalid = total - valid

        return {
            "total_entries": total,
            "valid_entries": valid,
            "invalid_entries": invalid,
            "chain_intact": invalid == 0,
            "details": [
                {
                    "sequence": r["sequence_number"],
                    "valid": r["valid"],
                    "message": r["error_message"],
                }
                for r in results
            ],
        }
    finally:
        await pool.close()


@fraiseql.app.post("/compliance/slsa/verify/{artifact_name}")
async def verify_slsa_provenance(artifact_name: str, version: str):
    """Verify SLSA provenance for an artifact.

    In production, this would:
    1. Fetch attestation from registry
    2. Verify signature with cosign
    3. Validate builder identity
    4. Check provenance claims

    This demo returns mock verification.
    """
    from asyncpg import create_pool

    pool = await create_pool(DATABASE_URL)
    try:
        provenance = await pool.fetchrow(
            """
            SELECT * FROM tb_slsa_provenance
            WHERE artifact_name = $1 AND artifact_version = $2
            """,
            artifact_name,
            version,
        )

        if not provenance:
            raise HTTPException(status_code=404, detail="Provenance not found")

        # Mock verification
        return {
            "artifact": f"{artifact_name}@{version}",
            "verified": provenance["verified"],
            "slsa_level": "SLSA Level 3",
            "builder": provenance["builder_id"],
            "source": {
                "repo": provenance["source_repo"],
                "commit": provenance["source_commit"],
            },
            "build_time": provenance["build_finished_on"].isoformat(),
            "verification_steps": [
                {"step": "Signature verification", "status": "✓ PASSED"},
                {"step": "Builder identity check", "status": "✓ PASSED"},
                {"step": "Source provenance", "status": "✓ PASSED"},
                {"step": "Materials completeness", "status": "✓ PASSED"},
            ],
        }
    finally:
        await pool.close()


@fraiseql.app.get("/compliance/kms/rotate/{key_id}")
async def rotate_kms_key(key_id: str):
    """Rotate KMS key (demo endpoint).

    In production, this would:
    1. Call KMS provider API
    2. Generate new key version
    3. Update key registry
    4. Re-encrypt data with new key
    """
    from asyncpg import create_pool

    pool = await create_pool(DATABASE_URL)
    try:
        # Mark old key as rotated
        await pool.execute(
            """
            UPDATE tb_kms_key
            SET key_status = 'rotated', rotated_at = NOW()
            WHERE key_id = $1
            """,
            key_id,
        )

        # In production: Create new key version
        return {
            "status": "success",
            "message": f"Key {key_id} rotated successfully",
            "old_key_status": "rotated",
            "new_key_version": "v2",
            "rotation_timestamp": datetime.now().isoformat(),
        }
    finally:
        await pool.close()


# ============================================================================
# APPLICATION SETUP
# ============================================================================

app = create_fraiseql_app(
    database_url=DATABASE_URL,
    schema=fraiseql.get_schema(),
    enable_rust_pipeline=True,
    enable_cascade=True,
    security_profile=SecurityProfile.REGULATED,  # Compliance-focused
    allow_introspection=True,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "security_profile": "REGULATED",
        "features": [
            "cryptographic_audit_trail",
            "slsa_provenance",
            "kms_integration",
        ],
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 80)
    print("Compliance Demo Application")
    print("=" * 80)
    print()
    print("Features:")
    print("  ✓ Cryptographic audit trails with HMAC chains")
    print("  ✓ SLSA provenance tracking and verification")
    print("  ✓ KMS integration patterns")
    print("  ✓ REGULATED security profile")
    print()
    print("Endpoints:")
    print("  • GraphQL API: http://localhost:8000/graphql")
    print("  • Verify Audit Chain: GET /compliance/verify-audit-chain")
    print("  • Verify SLSA: POST /compliance/slsa/verify/{artifact}")
    print("  • Rotate KMS Key: GET /compliance/kms/rotate/{key_id}")
    print("  • Health Check: GET /health")
    print()
    print("=" * 80)
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)
