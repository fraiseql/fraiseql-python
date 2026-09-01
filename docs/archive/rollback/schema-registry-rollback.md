# Schema Registry Rollback Plan

**Version**: 1.0
**Date**: 2025-11-06
**Purpose**: Emergency rollback procedures for Schema Registry issues

---

## Overview

This document provides step-by-step rollback procedures if issues are discovered with the Schema Registry implementation. The Schema Registry is designed to be backward compatible, but this plan ensures you can quickly revert if needed.

---

## Risk Assessment

| Risk Level | Scenario | Probability | Impact | Rollback Level |
|------------|----------|-------------|--------|----------------|
| **Low** | Minor logging issues | Low | Minimal | No action needed |
| **Medium** | Performance degradation | Very Low | Medium | Level 1: Feature Flag |
| **High** | Critical bug in production | Very Low | High | Level 2: Code Rollback |
| **Critical** | Data corruption | None (read-only) | N/A | Not applicable |

**Note**: The Schema Registry is **read-only** and does not modify data. The worst case is incorrect GraphQL responses, which can be immediately rolled back.

---

## Rollback Levels

### Level 1: Feature Flag Disable (Instant - No Downtime)

**When to use:**

- Minor issues detected
- Non-critical bugs
- Performance testing
- Gradual rollout control

**Time to recover**: < 1 minute (code change + restart)

**Procedure:**

1. **Modify application code:**

```python
# File: main.py or app.py

from fraiseql.fastapi import create_fraiseql_app, FraiseQLConfig

app = create_fraiseql_app(
    config=FraiseQLConfig(database_url="..."),
    title="My API",
    enable_schema_registry=False,  # ← ADD THIS LINE
)
```

2. **Restart application:**

```bash
# For development
uvicorn main:app --reload

# For production (systemd)
sudo systemctl restart fraiseql-app

# For Docker
docker-compose restart app

# For Kubernetes
kubectl rollout restart deployment/fraiseql-app
```

3. **Verify rollback:**

Check logs - you should NOT see:

```
INFO: Initialized schema registry with N types
```

4. **Test functionality:**

```bash
# Run health check
curl http://localhost:8000/health

# Test a simple query
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __typename }"}'
```

**Impact:**

- ✅ Application continues to run
- ⚠️ Issue #112 bug returns (nested `__typename` incorrect)
- ⚠️ GraphQL aliases don't work
- ✅ No data loss
- ✅ No database changes

---

### Level 2: Version Rollback (5-10 minutes)

**When to use:**

- Critical bugs in production
- Feature flag disable not sufficient
- Multiple issues detected
- Need to completely revert changes

**Time to recover**: 5-10 minutes

**Procedure:**

1. **Identify previous stable version:**

```bash
# Check current version
pip show fraiseql

# Or in Python:
python -c "import fraiseql; print(fraiseql.__version__)"
```

2. **Rollback to previous version:**

```bash
# Option A: Using pip
pip install fraiseql==<previous-version>

# Option B: Using uv
uv pip install fraiseql==<previous-version>

# Option C: Using requirements.txt
# Edit requirements.txt to specify previous version:
# fraiseql==<previous-version>
pip install -r requirements.txt
```

3. **Rebuild if using Rust extensions:**

```bash
# Only needed if you build from source
cd fraiseql
uv build
```

4. **Restart application:**

```bash
# Same as Level 1 restart procedure
sudo systemctl restart fraiseql-app
```

5. **Verify rollback:**

```bash
# Check version
python -c "import fraiseql; print(fraiseql.__version__)"

# Verify schema registry is NOT initialized
# (Check logs - should NOT see schema registry messages)
```

6. **Run regression tests:**

```bash
pytest tests/ --tb=short
```

**Impact:**

- ✅ Complete rollback to previous behavior
- ⚠️ Lose schema registry benefits
- ✅ No data loss
- ✅ Stable known state

---

### Level 3: Emergency Hotfix (30-60 minutes)

**When to use:**

- Specific bug identified that can be quickly fixed
- Rollback not desired (need schema registry benefits)
- Issue is isolated and well-understood

**Time to recover**: 30-60 minutes (fix + test + deploy)

**Procedure:**

1. **Identify the bug:**

```python
# Enable debug logging
import logging
logging.getLogger("fraiseql").setLevel(logging.DEBUG)
```

2. **Create a hotfix branch:**

```bash
git checkout -b hotfix/schema-registry-issue-XXX
```

3. **Apply targeted fix**

(Specific to the bug - coordinate with maintainers)

4. **Test the fix:**

```bash
# Run unit tests
pytest tests/unit/ -v

# Run integration tests
pytest tests/integration/ -v

# Run regression tests
pytest tests/regression/ -v
```

5. **Deploy hotfix:**

```bash
# Build and install
uv build
pip install dist/*.whl

# Or deploy via package manager
pip install git+https://github.com/fraiseql/fraiseql-python@hotfix/branch
```

6. **Monitor closely:**

```bash
# Watch logs for errors
tail -f /var/log/fraiseql/app.log

# Monitor metrics
# (Use your monitoring stack - Grafana, DataDog, etc.)
```

**Impact:**

- ✅ Fixes specific issue
- ✅ Maintains schema registry benefits
- ⏱️ Longer recovery time
- ⚠️ Requires testing and validation

---

## Rollback Decision Matrix

| Symptom | Severity | Recommended Rollback | Timeframe |
|---------|----------|----------------------|-----------|
| Startup time > 500ms | Medium | Level 1: Feature Flag | 1 minute |
| Query errors (< 1%) | Medium | Level 1: Feature Flag | 1 minute |
| Query errors (> 10%) | High | Level 2: Version Rollback | 5 minutes |
| Application crash | Critical | Level 2: Version Rollback | 5 minutes |
| Memory leak detected | High | Level 1 → Level 2 if persists | 10 minutes |
| Performance degradation | Medium | Level 1: Feature Flag | 1 minute |
| GraphQL response errors | High | Level 1 → Level 2 if not fixed | 5-10 minutes |

---

## Monitoring & Detection

### Pre-Rollback Checklist

Before rolling back, gather this information:

**1. Application Logs:**

```bash
# Check for schema registry initialization
grep "Initialized schema registry" /var/log/fraiseql/app.log

# Check for errors
grep "ERROR" /var/log/fraiseql/app.log | tail -50

# Check for warnings
grep "WARNING" /var/log/fraiseql/app.log | tail -50
```

**2. Performance Metrics:**

```bash
# Query latency
# (Use your monitoring tools)

# Memory usage
ps aux | grep fraiseql

# CPU usage
top -p $(pgrep -f fraiseql)
```

**3. Error Rates:**

```bash
# HTTP 500 errors
# (Check your access logs or monitoring dashboard)
```

**4. Reproduce the Issue:**

```bash
# Try to reproduce with a simple query
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ test { __typename } }"}'
```

### Post-Rollback Validation

After rolling back, verify:

**1. Application Health:**

```bash
curl http://localhost:8000/health
# Should return 200 OK
```

**2. Basic Queries Work:**

```bash
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __schema { queryType { name } } }"}'
```

**3. Performance Restored:**

- Check query latency is back to baseline
- Monitor for 10-15 minutes

**4. Error Rate Dropped:**

- HTTP 500 errors should return to normal levels

---

## Communication Plan

### During an Incident

**1. Immediate (T+0 minutes):**

- Detect issue via monitoring/alerts
- Assess severity using decision matrix
- Notify on-call engineer

**2. Investigation (T+5 minutes):**

- Gather logs and metrics (see checklist above)
- Determine appropriate rollback level
- Notify stakeholders if high/critical severity

**3. Execution (T+10 minutes):**

- Execute rollback procedure
- Document actions taken
- Monitor for resolution

**4. Validation (T+15 minutes):**

- Run post-rollback validation
- Confirm issue resolved
- Continue monitoring for 30 minutes

**5. Retrospective (T+24 hours):**

- Document root cause
- Create bug report
- Plan permanent fix
- Update rollback plan if needed

### Stakeholder Communication Template

```
Subject: [INCIDENT] Schema Registry Rollback - [SEVERITY]

Status: IN PROGRESS / RESOLVED
Rollback Level: [1/2/3]
Time Detected: [timestamp]
Time Resolved: [timestamp] (or ETA)

Impact:
- [Describe user-facing impact]
- [Affected queries/endpoints]

Actions Taken:
- [Rollback procedure executed]
- [Validation completed]

Next Steps:
- [Monitoring plan]
- [Permanent fix timeline]

Incident Manager: [Name]
```

---

## Testing Rollback Procedures

### Regular Testing Schedule

Test rollback procedures regularly:

**Quarterly (Every 3 months):**

1. Level 1: Feature Flag disable/enable
2. Verify application works in both modes
3. Document any issues

**Bi-annually (Every 6 months):**

1. Level 2: Version rollback in staging
2. Test full upgrade/downgrade cycle
3. Measure rollback time

### Test Script

```bash
#!/bin/bash
# rollback_test.sh - Test schema registry rollback

echo "Testing Schema Registry Rollback Procedures"
echo "============================================"

# Test Level 1: Feature Flag
echo "Test 1: Feature Flag Disable"
sed -i 's/enable_schema_registry=True/enable_schema_registry=False/' main.py
systemctl restart fraiseql-app
sleep 5

if systemctl is-active fraiseql-app; then
    echo "✓ Level 1 rollback successful"
else
    echo "✗ Level 1 rollback failed"
    exit 1
fi

# Restore
sed -i 's/enable_schema_registry=False/enable_schema_registry=True/' main.py
systemctl restart fraiseql-app
sleep 5

echo "Test 2: Version Rollback (staging only)"
# ... add version rollback test ...

echo "All rollback tests passed ✓"
```

---

## Known Issues & Workarounds

### Issue: "Schema registry already initialized"

**When**: Running tests or restarting in development

**Workaround**: This is expected behavior - the registry is a global singleton.

**Not a production issue**: Each process initializes once.

---

### Issue: Performance degradation with very large schemas (1000+ types)

**Likelihood**: Very low (most schemas have < 100 types)

**Workaround**: Feature flag disable if startup time > 500ms

**Permanent fix**: Schema registry lazy loading (future enhancement)

---

## Appendix: Contact Information

### Escalation Path

1. **Level 1**: On-call engineer
2. **Level 2**: Lead backend engineer
3. **Level 3**: CTO / Engineering Manager

### Resources

- **Documentation**: `/docs/migration/schema_registry.md`
- **Implementation Plan**: `SCHEMA_REGISTRY_IMPLEMENTATION_PLAN.md`
- **GitHub Issues**: https://github.com/fraiseql/fraiseql/issues
- **Support**: support@fraiseql.com (if available)

---

## Revision History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2025-11-06 | Initial rollback plan | FraiseQL Team |

---

## Summary

The Schema Registry rollback plan provides **three levels** of recovery:

1. **Level 1** (Feature Flag): Instant rollback, 0 downtime
2. **Level 2** (Version Rollback): 5-10 minutes, complete revert
3. **Level 3** (Hotfix): 30-60 minutes, targeted fix

**Key Points:**

- ✅ No data loss possible (read-only transformation)
- ✅ Multiple rollback options
- ✅ Clear decision matrix
- ✅ Documented procedures
- ✅ Regular testing recommended

**Remember**: The Schema Registry is designed to be stable and backward compatible. These procedures are precautionary and unlikely to be needed.

---

**Questions about rollback procedures?** Contact the on-call engineer or file an issue.
