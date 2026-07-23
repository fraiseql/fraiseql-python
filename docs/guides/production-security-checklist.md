<!-- Skip to main content -->
---

title: FraiseQL Production Security Checklist
description: Complete pre-production security checklist for deploying FraiseQL to production.
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial", "security"]
tags: ["documentation", "reference"]
---

# FraiseQL Production Security Checklist

**Status:** ✅ Production Ready
**Audience:** DevOps, Security Engineers, Architects
**Reading Time:** 15-20 minutes
**Last Updated:** 2026-02-05

Complete pre-production security checklist for deploying FraiseQL to production.

---

## 🔒 Quick Assessment

**Self-Assessment**: Before beginning, answer these questions:

- [ ] Do you have a security requirements document?
- [ ] Have you identified your compliance requirements (PCI-DSS, HIPAA, SOC 2, etc.)?
- [ ] Is your organization's security team aware of this deployment?
- [ ] Do you have an incident response plan?

If you answered **no** to any of these, start with [Security Planning](#security-planning) section.

---

## Security Planning

### Compliance Requirements

**Determine your compliance baseline:**

- [ ] Identify applicable regulations (GDPR, HIPAA, PCI-DSS, SOC 2, etc.)
- [ ] Document data classification (public, internal, confidential, sensitive)
- [ ] Define retention requirements for audit logs
- [ ] Review incident notification requirements
- [ ] Identify any geographic data residency requirements
- [ ] Document approval process for security exceptions

### Risk Assessment

- [ ] Conduct threat modeling (identify attack vectors)
- [ ] Evaluate potential data exposure impact
- [ ] Assess business continuity requirements
- [ ] Define acceptable downtime windows
- [ ] Establish security incident severity levels
- [ ] Identify sensitive fields requiring encryption

### Team Preparation

- [ ] Security team reviewed deployment plan
- [ ] DevOps team trained on security configuration
- [ ] Incident response team briefed on architecture
- [ ] On-call escalation path established
- [ ] Communication plan for security incidents documented

---

## 1. Network Security

### Firewall & Network Isolation

- [ ] FraiseQL FastAPI app (behind Uvicorn/Gunicorn) accessible only via load balancer (not directly)
- [ ] Firewall allows only necessary inbound ports (443 for HTTPS, 5432 for DB if on network)
- [ ] Firewall denies all inbound by default
- [ ] Database server not accessible from internet (private network only)
- [ ] Redis/caching layer (if used) not accessible from internet
- [ ] All outbound traffic audited and approved
- [ ] DDoS protection enabled (WAF, rate limiting)
- [ ] Network segmentation implemented (DMZ, internal, database tiers)

### TLS/SSL Configuration

- [ ] HTTPS enforced (HTTP requests redirect to HTTPS)
- [ ] Valid SSL certificate installed (not self-signed in production)
- [ ] Certificate from trusted CA (Let's Encrypt, DigiCert, etc.)
- [ ] Certificate auto-renewal configured (before expiry)
- [ ] Certificate renewal monitored and alerted
- [ ] TLS 1.2 minimum (TLS 1.0, 1.1 disabled)
- [ ] TLS 1.3 enabled (if available)
- [ ] Strong cipher suites configured (ECDHE, AES-256)
- [ ] Weak ciphers disabled
- [ ] Perfect Forward Secrecy (PFS) enabled
- [ ] HSTS header set (Strict-Transport-Security: max-age=31536000; includeSubDomains)
- [ ] Certificate pinning considered for sensitive clients
- [ ] mTLS enabled between services (if multi-service deployment)
- [ ] Client certificates validated and rotated regularly

### CDN & Proxies

- [ ] If using CDN, verify HTTPS end-to-end
- [ ] CDN cache headers configured correctly
- [ ] Sensitive headers (Authorization, Cookies) not cached
- [ ] Rate limiting configured at CDN/proxy level
- [ ] IP allowlisting configured (if applicable)
- [ ] Proxy logging enabled and monitored

---

## 2. Authentication & Authorization

### OAuth2/OIDC Configuration

- [ ] OAuth provider selected and configured
- [ ] Client ID and Secret stored in secure vault (not in code, config, or environment files)
- [ ] Redirect URIs restricted to production endpoints only
- [ ] Redirect URIs use HTTPS only
- [ ] Consent screen properly configured with organization branding
- [ ] Scopes limited to minimum required (principle of least privilege)
- [ ] OAuth provider discovery endpoint verified
- [ ] Public key endpoints cached and verified
- [ ] Key rotation strategy documented

### JWT Token Handling

- [ ] RS256 algorithm enforced (asymmetric, not HS256)
- [ ] Public keys properly cached with expiration
- [ ] Private keys never exposed or logged
- [ ] Issuer URL validated on every token check
- [ ] Algorithm parameter validated (prevent "none" algorithm)
- [ ] Access token expiry: 1 hour (or shorter)
- [ ] Refresh token expiry: 7 days (or shorter)
- [ ] Token subject (sub) claim validated
- [ ] Tokens never logged in plaintext
- [ ] Token validation happens on every request (no skipping)

### Session Management

- [ ] Refresh tokens hashed before storage (bcrypt, Argon2, or SHA256)
- [ ] Sessions stored in database (not in-memory)
- [ ] Session table indexes optimized
- [ ] Automatic session expiry via TTL
- [ ] Revoked sessions immediately invalidated
- [ ] Session revocation tested and verified
- [ ] Concurrent session limits enforced (if applicable)
- [ ] Session timeout on inactivity configured

### Field-Level Authorization

- [ ] Authorization decorators (`requires_auth`, `requires_role`, `requires_permission`) used on sensitive resolvers
- [ ] Field-level authorization (`authorize_field`) applied to sensitive fields
- [ ] Operation-level `Authorizer` wired via `@fraiseql.query(authorizer=...)` / `@fraiseql.subscription(authorizer=...)`
- [ ] Role-based access control (RBAC) configured
- [ ] Row-level security (RLS) enforced at database (session GUC `app.tenant_id` set per request)
- [ ] Authorization checks cannot be bypassed (resolver-bypass routes, e.g. `enable_rust_endpoint`, remain authorization-gated)
- [ ] Permission changes take effect immediately (decision cache TTL accounted for)
- [ ] Authorization audit logging enabled

### Introspection Control

- [ ] Schema introspection disabled for unauthenticated clients (`introspection_policy=AUTHENTICATED`)
- [ ] Introspection requires authentication for internal tools
- [ ] Introspection completely disabled in production if not needed (`introspection_policy=DISABLED`; auto-disabled when `environment="production"`)
- [ ] GraphQL playground disabled in production (`enable_playground=False`; auto-disabled in production)
- [ ] Only allowlisted queries accepted (`apq_mode="required"` with `apq_queries_dir` populated)

---

## 3. Data Security

### Encryption at Rest

- [ ] Database encryption enabled (TDE, EBS encryption, etc.)
- [ ] Encryption keys managed by KMS (AWS KMS, HashiCorp Vault, etc.)
- [ ] Encryption key rotation configured (annual or per policy)
- [ ] Backups encrypted with same or separate keys
- [ ] Backup encryption keys managed separately from database keys
- [ ] Sensitive fields encrypted (PII, payment data)
- [ ] Encryption key access restricted to authorized personnel only

### Encryption in Transit

- [ ] All database connections use TLS (`sslmode=require` or stricter in `database_url`)
- [ ] Database connection strings encrypted (not in plaintext config)
- [ ] Inter-service communication encrypted
- [ ] Any outbound integrations (called from `fn_` functions or FastAPI middleware) over HTTPS only

### Sensitive Data Handling

- [ ] Passwords never stored in logs
- [ ] Tokens never stored in logs
- [ ] API keys never stored in logs
- [ ] Sensitive fields masked in error messages
- [ ] PII not logged without strict need
- [ ] Log retention policy respects data protection requirements
- [ ] Sensitive data purged according to retention policy
- [ ] Data export requires explicit authorization

### Database Hardening

- [ ] PostgreSQL user has minimal required permissions
- [ ] Database user cannot create tables or databases
- [ ] Database connection requires strong authentication (not empty password)
- [ ] Database user password > 32 characters (random, no patterns)
- [ ] Database connection limited to the FraiseQL application server IPs
- [ ] Database public access disabled
- [ ] Unnecessary extensions disabled
- [ ] SQL injection prevention verified (use prepared statements)
- [ ] Point-in-time recovery tested and validated

---

## 4. Rate Limiting & DDoS Protection

### Rate Limiting Configuration

- [ ] Application rate limiting enabled (`rate_limit_enabled=True`)
- [ ] Per-minute / per-hour limits configured (`rate_limit_requests_per_minute`, `rate_limit_requests_per_hour`, `rate_limit_burst_size`)
- [ ] Stricter limits applied to authentication endpoints (login, token refresh)
- [ ] Rate limits enforced at multiple layers (WAF, proxy, application)
- [ ] Rate limit headers returned to clients
- [ ] Rate limit allow/deny lists reviewed (`rate_limit_whitelist`, `rate_limit_blacklist`)
- [ ] Distributed rate limiting backed by Redis if running multiple instances (`RedisRateLimitStore`)
- [ ] Rate limiting verified under load testing

### Query Complexity Limits

- [ ] Query depth limit enforced (`complexity_max_depth`, or `max_query_depth`)
- [ ] Query complexity scoring enabled (`complexity_enabled=True`)
- [ ] Complexity limit set (`complexity_max_score`, default 1000 — tune per policy)
- [ ] Mutation complexity calculated and limited
- [ ] Timeout on slow queries (`execution_timeout_ms`, default 30000 ms)
- [ ] Query complexity monitoring in place

### DDoS Protection

- [ ] DDoS protection service enabled (if available)
- [ ] Automatic scaling configured for traffic spikes
- [ ] Connection limits enforced at load balancer
- [ ] Slowloris attack protection enabled
- [ ] HTTP/2 request flooding protection configured

---

## 5. Audit Logging & Monitoring

### Audit Logging Configuration

- [ ] Audit logging enabled for all mutations
- [ ] Audit logs include: user, timestamp, action, resource, old value, new value
- [ ] Sensitive data not included in audit logs (or masked)
- [ ] Audit logs sent to centralized logging system
- [ ] Audit logs immutable (cannot be modified or deleted)
- [ ] Audit log retention: minimum 1 year (per compliance)
- [ ] Audit log access restricted to authorized personnel only
- [ ] Audit log integrity monitoring enabled (hash verification)

### Security Event Logging

- [ ] Failed authentication attempts logged
- [ ] Authorization failures logged
- [ ] Rate limit violations logged
- [ ] Unusual query patterns logged
- [ ] Administrative actions logged
- [ ] Configuration changes logged
- [ ] Security event sampling rate: 100% (no sampling for security events)

### Observability & Monitoring

- [ ] Application logs sent to centralized logging (ELK, Splunk, CloudWatch)
- [ ] Error tracking enabled (Sentry, DataDog)
- [ ] Performance monitoring enabled (New Relic, DataDog)
- [ ] Security metrics monitored (failed auth, rate limits, authorization failures)
- [ ] Distributed tracing enabled (Jaeger, DataDog)
- [ ] Log aggregation and search configured
- [ ] Alert thresholds set for security events
- [ ] On-call rotation configured for security alerts

---

## 6. Error Handling & Information Disclosure

### Error Message Configuration

- [ ] Error messages sanitized (no internal details exposed)
- [ ] Stack traces never returned to clients
- [ ] Database errors wrapped and anonymized
- [ ] SQL queries never exposed in error messages
- [ ] File paths never exposed in error messages
- [ ] Version numbers not disclosed in error responses
- [ ] Errors logged internally for debugging

### Exception Handling

- [ ] All exceptions caught and logged
- [ ] Graceful error responses returned
- [ ] No unhandled exceptions in production
- [ ] Error monitoring configured

---

## 7. Infrastructure & Deployment

### Server Configuration

- [ ] OS patches applied (latest security updates)
- [ ] Unused services disabled
- [ ] SSH hardened (SSH keys only, no passwords)
- [ ] SSH key rotation configured
- [ ] sudo access restricted (principle of least privilege)
- [ ] File permissions configured correctly (not world-readable)
- [ ] Sensitive files encrypted (private keys, credentials)

### Container Security (if using Docker/Kubernetes)

- [ ] Container images scanned for vulnerabilities
- [ ] Base images from trusted registries only
- [ ] Secrets managed via secrets manager (not in environment variables)
- [ ] Container running as non-root user
- [ ] Container filesystem read-only (where possible)
- [ ] Resource limits configured (CPU, memory)
- [ ] Network policies restrict pod communication
- [ ] Pod security policies enforced
- [ ] Container image signing and verification enabled

### Load Balancer Configuration

- [ ] Load balancer health checks configured
- [ ] Load balancer timeout set (connection, request, idle)
- [ ] Load balancer logging enabled
- [ ] Load balancer access logs monitored
- [ ] Load balancer rate limiting enabled
- [ ] Load balancer WAF rules enabled
- [ ] Load balancer SSL/TLS hardened

### Secrets Management

- [ ] Secrets vault implemented (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault)
- [ ] Secrets not stored in environment variables
- [ ] Secrets not stored in configuration files
- [ ] Secrets not stored in version control
- [ ] Secrets rotated regularly (monthly or per policy)
- [ ] Secrets access logged and audited
- [ ] Secrets backup encrypted
- [ ] Emergency access procedure documented

### Backups & Disaster Recovery

- [ ] Automated backups configured (daily or hourly)
- [ ] Backups encrypted at rest
- [ ] Backups encrypted in transit
- [ ] Backups stored in geographically separate location
- [ ] Backup retention policy documented
- [ ] Backup restoration tested (monthly)
- [ ] Disaster recovery plan documented
- [ ] RTO (Recovery Time Objective) defined
- [ ] RPO (Recovery Point Objective) defined
- [ ] Failover tested and validated

---

## 8. Third-Party & Dependencies

### Dependency Management

- [ ] Dependency scanner enabled (Snyk, Dependabot, etc.)
- [ ] Known vulnerabilities checked regularly
- [ ] Vulnerable dependencies updated immediately
- [ ] Dependency review process documented
- [ ] Supply chain security assessed
- [ ] License compliance verified

### Vulnerability Management

- [ ] Vulnerability scanning enabled
- [ ] Vulnerability patching process documented
- [ ] Critical vulnerabilities patched within 24 hours
- [ ] High vulnerabilities patched within 7 days
- [ ] Vulnerability monitoring alerts configured

---

## 9. Testing & Validation

### Security Testing

- [ ] OWASP Top 10 vulnerabilities tested
- [ ] SQL injection testing performed
- [ ] XSS (Cross-Site Scripting) testing performed
- [ ] CSRF (Cross-Site Request Forgery) testing performed
- [ ] Authentication bypass testing performed
- [ ] Authorization bypass testing performed
- [ ] Rate limiting testing performed
- [ ] Error message disclosure testing performed
- [ ] Penetration testing scheduled (annual, minimum)

### Load & Performance Testing

- [ ] Load testing performed (target: 1000 concurrent users)
- [ ] Rate limiting verified under load
- [ ] Database connection pooling verified
- [ ] Memory leaks checked
- [ ] Query performance profiled
- [ ] Timeout behavior verified
- [ ] Failure scenarios tested (database down, timeout, etc.)

---

## 10. Compliance & Documentation

### Documentation

- [ ] Security architecture documented
- [ ] Data flow diagram created and reviewed
- [ ] Security controls documented
- [ ] Configuration management documented
- [ ] Incident response plan documented
- [ ] Disaster recovery plan documented
- [ ] Change control process documented
- [ ] Access control matrix documented
- [ ] Secrets management procedure documented

### Compliance Verification

- [ ] Compliance requirements mapped to controls
- [ ] Gap analysis completed
- [ ] Remediation plan for gaps documented
- [ ] Compliance audit scheduled
- [ ] Compliance audit evidence collected
- [ ] Compliance report generated

### Security Training

- [ ] Security team trained on FraiseQL
- [ ] DevOps team trained on security configuration
- [ ] Developers trained on secure coding
- [ ] Incident response team trained
- [ ] On-call team trained on escalation
- [ ] Training records maintained

---

## 11. Ongoing Security Maintenance

### Regular Reviews

- [ ] Monthly security review scheduled
- [ ] Quarterly audit log review
- [ ] Annual penetration testing
- [ ] Annual security training
- [ ] Dependency updates reviewed weekly
- [ ] Security alerts monitored continuously

### Incident Response

- [ ] Incident response plan documented
- [ ] Incident response team trained
- [ ] Incident reporting process defined
- [ ] Post-incident review process defined
- [ ] Lessons learned documented
- [ ] Security patches tested in staging before production

### Security Alerts

- [ ] Failed authentication attempts monitored
- [ ] Authorization failures monitored
- [ ] Rate limiting violations monitored
- [ ] Unusual query patterns monitored
- [ ] Error rates monitored
- [ ] Performance degradation monitored
- [ ] Backup job status monitored
- [ ] Security certificate expiry monitored

---

## Final Pre-Production Sign-Off

**Before going live, ensure all stakeholders sign off:**

- [ ] Security team approved
- [ ] DevOps team approved
- [ ] Compliance team approved
- [ ] Management approved
- [ ] Architecture team approved
- [ ] Database team approved

**Date approved:** ___________

**Approved by:** ___________

---

## See Also

**Security Documentation:**

- **[Authentication Provider Selection](../integrations/authentication/provider-selection-guide.md)** — Choosing OAuth providers securely
- **[Authentication Security Checklist](../integrations/authentication/security-checklist.md)** — Auth-specific security checks
- **[RBAC & Authorization](./authorization-quick-start.md)** — Field-level access control configuration
- **[Audit Logging](../enterprise/audit-logging.md)** — Compliance and audit trail setup
- **[KMS Integration](../enterprise/kms.md)** — Key management service configuration

**Operations:**

- **[Production Deployment Guide](./production-deployment.md)** — Deployment procedures
- **[Monitoring & Observability](./monitoring.md)** — Production monitoring setup
- **[Distributed Tracing](../operations/distributed-tracing.md)** — Observability configuration

**Compliance:**

- **[Specs: Security & Compliance](../specs/security-compliance.md)** — Security feature specifications

---

**Last Updated:** 2026-02-05
