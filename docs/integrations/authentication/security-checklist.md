<!-- Skip to main content -->
---

title: FraiseQL Authentication Security Checklist
description: Complete security checklist for FraiseQL authentication deployment.
keywords: ["framework", "sdk", "monitoring", "database", "authentication", "security"]
tags: ["documentation", "reference"]
---

# FraiseQL Authentication Security Checklist

Complete security checklist for FraiseQL authentication deployment.

## Pre-Deployment Security Audit

### OAuth Provider Configuration

- [ ] Client secrets stored in secure vault (not in code)
- [ ] Redirect URIs limited to intended endpoints only
- [ ] HTTPS enforced for redirect URIs in production
- [ ] Multiple providers support verified (if applicable)
- [ ] OAuth discovery endpoint accessible
- [ ] Public key endpoints responding correctly

### JWT Configuration

- [ ] RS256 algorithm used for OAuth tokens (not HS256)
- [ ] Public keys properly cached
- [ ] Key rotation strategy documented
- [ ] Token expiry set appropriately (1 hour access, 7 days refresh)
- [ ] Issuer URL matches exactly
- [ ] Algorithm validation enabled

### Database Security

- [ ] PostgreSQL user has minimal required permissions
- [ ] Strong password (> 32 characters, random)
- [ ] Connection uses SSL/TLS
- [ ] Database firewall restricts to app servers only
- [ ] Backups encrypted at rest
- [ ] Backup encryption keys managed separately
- [ ] Point-in-time recovery tested

### Session Management

- [ ] Refresh tokens hashed before storage (SHA256)
- [ ] Sessions table uses strong indexes
- [ ] Automatic session expiry via TTL
- [ ] Revoked tokens immediately invalidated (`PostgreSQLRevocationStore` / `TokenRevocationService`)
- [ ] Token revocation tested

### Token Security

- [ ] Access tokens have short expiry (1 hour)
- [ ] Refresh tokens have long expiry (7 days)
- [ ] Tokens not logged in plaintext
- [ ] Token validation happens on every request
- [ ] Expired tokens rejected immediately
- [ ] Token signatures verified correctly

### CSRF Protection

- [ ] State parameter used in OAuth flow
- [ ] State parameter validated on callback
- [ ] State expiry set (10 minutes)
- [ ] State stored securely (not in URL)
- [ ] PKCE enabled for native/mobile apps

### HTTPS/TLS

- [ ] HTTPS enforced (not HTTP)
- [ ] Valid SSL certificate installed
- [ ] Certificate auto-renewal configured
- [ ] TLS 1.2+ only (TLS 1.0, 1.1 disabled)
- [ ] Strong cipher suites configured
- [ ] HSTS header set (max-age=31536000)

### Security Headers

- [ ] Content-Security-Policy header set
- [ ] X-Content-Type-Options: nosniff
- [ ] X-Frame-Options: SAMEORIGIN
- [ ] X-XSS-Protection enabled
- [ ] Referrer-Policy: strict-origin-when-cross-origin

### Rate Limiting

- [ ] Rate limiting enabled on /auth/start (1 req/sec per IP)
- [ ] Rate limiting enabled on /auth/callback (1 req/sec per IP)
- [ ] Rate limiting enabled on /auth/refresh (10 req/sec per IP)
- [ ] Rate limiting configured (`RateLimit` rules; `RedisRateLimitStore` for multi-worker deployments)
- [ ] Brute force protection configured
- [ ] Failed attempts logged and monitored

### Error Handling

- [ ] Generic error messages (no information leakage)
- [ ] Detailed errors only in logs
- [ ] Stack traces never shown to clients
- [ ] Error codes standardized
- [ ] Sensitive data never in error responses

### Logging & Monitoring

- [ ] Structured logging enabled
- [ ] Sensitive data not logged (tokens, passwords, secrets)
- [ ] Authentication events logged with details
- [ ] Failed login attempts tracked
- [ ] Unusual patterns detected
- [ ] Logs stored securely
- [ ] Log retention policy documented

### Access Control

- [ ] Admin endpoints require authentication (`@requires_auth` / `@requires_role` / `@requires_permission`)
- [ ] Role-based access control (RBAC) configured (operation `Authorizer`, field `authorize_field`)
- [ ] Principle of least privilege applied
- [ ] Tenant isolation enforced via PostgreSQL Row-Level Security (RLS) where applicable
- [ ] User permissions validated on each request
- [ ] Unauthorized access attempts logged
- [ ] Schema introspection policy set appropriately for production (`introspection_policy`)
- [ ] GraphQL playground disabled in production (`enable_playground` / `production=True`)

### Environment Configuration

- [ ] Secrets in environment variables (not files)
- [ ] No secrets in git history
- [ ] .env files not committed
- [ ] Production credentials never in code
- [ ] Secrets encrypted in transit
- [ ] Secrets encrypted at rest in vault

### API Security

- [ ] JSON payloads validated (size limits)
- [ ] Input validation on all endpoints
- [ ] No SQL injection vulnerabilities
- [ ] No path traversal vulnerabilities
- [ ] No arbitrary code execution
- [ ] Dependencies scanned for CVEs

### Data Privacy

- [ ] PII minimized in storage
- [ ] Email addresses hashed if not needed
- [ ] User IDs don't reveal identity
- [ ] No unnecessary personal data collected
- [ ] GDPR compliance verified

### Incident Response

- [ ] Incident response plan documented
- [ ] Contact list created
- [ ] Escalation procedures defined
- [ ] Recovery procedures tested
- [ ] Backups verified restorable

## Ongoing Security

### Regular Audits

- [ ] Monthly: Review access logs
- [ ] Monthly: Check for failed auth patterns
- [ ] Quarterly: Review security configuration
- [ ] Quarterly: Update dependencies
- [ ] Annually: External security audit

### Dependency Management

- [ ] Dependencies scanned monthly (e.g., `uv pip audit` / `pip-audit`, or Dependabot)
- [ ] Security updates applied immediately
- [ ] Beta/dev dependencies removed before production
- [ ] Unused dependencies removed
- [ ] Changelog reviewed for security fixes

### Monitoring

- [ ] Real-time alerting for security events
- [ ] Alert on failed login attempts (>5 in 5 min)
- [ ] Alert on tokens rejected (spike detection)
- [ ] Alert on database errors
- [ ] Alert on unauthorized access attempts

### Secrets Rotation

- [ ] OAuth client secrets rotated yearly
- [ ] JWT signing keys rotated yearly
- [ ] Database passwords rotated yearly
- [ ] SSL certificates rotated before expiry
- [ ] Old secrets removed after rotation

### Testing

- [ ] Penetration testing scheduled annually
- [ ] Security code review process established
- [ ] Security test cases written
- [ ] Failed scenarios tested
- [ ] Recovery procedures tested

## OAuth Provider Specific

### Google

- [ ] OAuth consent screen configured
- [ ] Scopes limited to necessary (openid, profile, email)
- [ ] Application verified
- [ ] Sensitive scopes acknowledged
- [ ] Removed from dev projects after testing

### Keycloak

- [ ] Realm created for production
- [ ] Admin console protected with strong password
- [ ] HTTPS enforced
- [ ] Users don't have realm admin role
- [ ] LDAP/user federation audited

### Auth0

- [ ] Tenant settings reviewed
- [ ] Rules/actions audited for security
- [ ] Logs reviewed for suspicious activity
- [ ] MFA enabled for admin
- [ ] Backup admin credentials stored securely

## Post-Deployment

### First Week

- [ ] Monitor authentication success rate
- [ ] Check for failed login patterns
- [ ] Verify token validation working
- [ ] Test session revocation
- [ ] Verify backups functioning

### First Month

- [ ] Review all auth logs
- [ ] Check for anomalies
- [ ] Verify performance metrics
- [ ] Test disaster recovery
- [ ] Get security team sign-off

### Ongoing

- [ ] Daily: Check monitoring dashboard
- [ ] Weekly: Review authentication metrics
- [ ] Monthly: Security audit
- [ ] Quarterly: Full security review
- [ ] Annually: Penetration testing

## Compliance

### GDPR

- [ ] Privacy policy references authentication
- [ ] Consent collected for OAuth scopes
- [ ] User data deletion implemented
- [ ] Data retention policy documented
- [ ] Right to access data implemented

### SOC2

- [ ] Access controls documented
- [ ] Change management process in place
- [ ] Incident response plan documented
- [ ] Monitoring and alerting enabled
- [ ] Backup and recovery procedures documented

### PCI-DSS (if handling payments)

- [ ] Tokens never stored
- [ ] PCI scope minimized
- [ ] Payment tokens encrypted
- [ ] Access restricted to authorized personnel

## Incident Response

### If Breach Occurs

1. **Immediate (0-1 hour)**
   - [ ] Revoke all active sessions
   - [ ] Force password reset for affected users
   - [ ] Enable MFA for admin accounts
   - [ ] Preserve evidence (logs, memory dumps)

2. **Short term (1-24 hours)**
   - [ ] Notify security team
   - [ ] Assess scope of breach
   - [ ] Communicate with users
   - [ ] Update OAuth provider

3. **Medium term (1-7 days)**
   - [ ] Complete forensic analysis
   - [ ] Root cause analysis
   - [ ] Patch vulnerabilities
   - [ ] Update security procedures

4. **Long term (1+ months)**
   - [ ] Notify compliance/legal
   - [ ] File incident report if required
   - [ ] Security audit
   - [ ] Implement preventive measures

### Testing Incident Response

Simulate a breach and verify recovery:

1. Manually revoke all sessions
2. Verify users can't use old tokens
3. Verify users can log back in
4. Document time to recovery
5. Review logs for completeness

## Communication

- [ ] Security vulnerabilities reported to <security@yourdomain.com>
- [ ] Responsible disclosure policy documented
- [ ] Response time: 48 hours
- [ ] Fix time: 30 days for critical

## Sign-Off

- [ ] Security team reviewed and approved
- [ ] Legal team reviewed and approved
- [ ] Operations team ready for deployment
- [ ] Incident response team trained
- [ ] Monitoring configured

---

**Deployment Approved By**: _______________
**Date**: _______________
**Valid Until**: _______________

---

See Also:

- [Deployment Guide](./deployment.md)
- [Monitoring Guide](./monitoring.md)
- [Troubleshooting](./troubleshooting.md)
