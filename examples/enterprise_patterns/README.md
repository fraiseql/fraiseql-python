# Enterprise Patterns Example

🟠 ADVANCED | ⏱️ 45 min | 🎯 Enterprise Compliance | 🏷️ All Patterns

This example demonstrates all FraiseQL enterprise patterns in a single, comprehensive application.

**What you'll learn:**

- Complete enterprise pattern implementation
- SOX/HIPAA compliant audit trails
- Multi-layer validation (GraphQL → App → Core → DB)
- NOOP handling for edge cases
- App/Core function architecture split
- Identifier management (triple ID pattern)

**Prerequisites:**

- Basic GraphQL knowledge
- Understanding of CQRS patterns
- `../blog_simple/` - Basic patterns

**Next steps:**

- [Subscriptions](../../docs/architecture/realtime/subscriptions.md) - Add real-time features
- `../analytics_dashboard/` - High-performance analytics
- `../saas-starter/` - Multi-tenant SaaS foundation

## Patterns Demonstrated

### ✅ Mutation Result Pattern

- Standardized mutation responses with metadata
- Field-level change tracking
- Comprehensive audit information
- See: `mutations.py` and `test_mutation_results.py`

### ✅ NOOP Handling Pattern

- Idempotent operations with graceful edge case handling
- Multiple NOOP scenarios (duplicate, no-changes, business rules)
- See: `test_noop_handling.py`

### ✅ App/Core Function Split

- Clean separation of input handling and business logic
- Type-safe core functions with JSONB app wrappers
- See: `db/migrations/002_app_functions.sql` and `003_core_functions.sql`

### ✅ Unified Audit Logging

- **Single `audit_events` table** combining CDC + cryptographic chain
- PostgreSQL-native crypto with SHA-256 hashing and HMAC signatures
- Tamper-proof audit trails for SOX/HIPAA compliance
- See: `core.log_and_return_mutation()` and unified audit table schema

### ✅ Identifier Management

- Triple ID pattern: internal ID, UUID primary key, business identifier
- Automatic identifier generation and recalculation
- Flexible lookup by any identifier type
- See: identifier-related functions and tests

### ✅ Multi-Layer Validation

- GraphQL schema validation with Pydantic
- App layer input sanitization
- Core layer business rule validation
- Database constraint validation
- See: `test_validation.py`

## Quick Start

```bash
# Start database
docker-compose up -d db

# Run migrations
python -m examples.enterprise_patterns.migrations

# Start API
uvicorn examples.enterprise_patterns.app:app --reload

# Run tests
pytest examples/enterprise_patterns/tests/ -v
```

## Key Files

- **models.py** - Complete type definitions with all patterns
- **mutations.py** - All mutation patterns in one place
- **db/migrations/** - Complete schema demonstrating all patterns
- **tests/** - Comprehensive test suite for each pattern

This example serves as the definitive reference for implementing all patterns together.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ GraphQL Layer (FraiseQL)                                    │
│ - Enterprise mutation classes with success/error/noop       │
│ - ID transformation: pk_[entity] → id                       │
│ - Comprehensive input validation                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ App Layer Functions (app.* schema)                          │
│ - JSONB → typed input conversion                            │
│ - Basic validation and sanitization                         │
│ - Delegation to core layer                                  │
└─────────────────────────────────────────────────────────────┐
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Core Layer Functions (core.* schema)                        │
│ - All business logic and rules                              │
│ - NOOP handling for edge cases                              │
│ - Comprehensive audit logging                               │
│ - Cross-entity validation                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Database Layer                                              │
│ - tb_* tables with JSONB data column                        │
│ - Complete audit trails (created/updated/version)           │
│ - Triple ID pattern (id, pk_entity, identifier)             │
│ - Constraint validation                                     │
└─────────────────────────────────────────────────────────────┘
```

## Entity Examples

This example includes complete implementations for:

- **Organizations** - Multi-tenancy with enterprise features
- **Users** - Authentication, roles, preferences with audit
- **Projects** - Business entities with full lifecycle
- **Tasks** - Nested entities with complex relationships
- **Documents** - File management with versioning
- **Notifications** - Event-driven communication

Each entity demonstrates all patterns in a realistic business context.

## Testing Strategy

### Pattern-Specific Tests

- `test_mutation_results.py` - Validates success/error/noop responses
- `test_noop_handling.py` - Tests all NOOP scenarios
- `test_audit_trails.py` - Verifies complete audit information
- `test_validation.py` - Multi-layer validation testing
- `test_identifiers.py` - Triple ID pattern verification

### Integration Tests

- `test_cross_entity_validation.py` - Complex business rules
- `test_transaction_handling.py` - Multi-entity operations
- `test_performance.py` - Scale testing with enterprise patterns

### End-to-End Tests

- `test_complete_workflows.py` - Realistic business scenarios
- `test_error_recovery.py` - Failure handling and rollback
- `test_audit_compliance.py` - Regulatory compliance scenarios

## Performance Considerations

With enterprise patterns enabled, expect:

- **Memory Usage**: ~20% increase due to audit trails
- **Query Performance**: Minimal impact with proper indexing
- **Function Calls**: 2-3 per mutation (app → core → logging)
- **Database Size**: ~30% increase from audit data

Optimizations included:

- Efficient JSONB indexing strategies
- Lazy loading of audit information
- Batch operations for bulk changes
- Caching of frequently accessed patterns

## Production Readiness

This example includes production-ready features:

- Complete error handling with structured responses
- Comprehensive logging and monitoring
- Security best practices (no secrets in logs)
- Performance optimization patterns
- Scalability considerations

## Compliance Features

Enterprise patterns support:

- **SOX Compliance** - Complete change auditing
- **GDPR Compliance** - Data lineage tracking
- **HIPAA Compliance** - Audit trail requirements
- **ISO 27001** - Information security standards

All mutations include sufficient audit information for regulatory compliance.
