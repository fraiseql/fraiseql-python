# FraiseQL Migration Checklist

**Purpose:** Generic checklist for migrating from any GraphQL framework to FraiseQL

Use this checklist alongside framework-specific guides:

- [From Strawberry](./from-strawberry.md)
- [From Graphene](./from-graphene.md)
- [From PostGraphile](./from-postgraphile.md)

---

## Pre-Migration Assessment

### Team Readiness

- [ ] Team has Python experience (3.10+ recommended)
- [ ] Team comfortable with async/await patterns
- [ ] Team has PostgreSQL database access and expertise
- [ ] Stakeholders approve 1-3 week migration timeline
- [ ] Rollback plan documented

### Technical Requirements

- [ ] Python 3.10+ installed
- [ ] PostgreSQL 12+ available
- [ ] Database backup created
- [ ] Testing environment set up
- [ ] Performance baseline established (current req/s, latency)

### Architecture Review

- [ ] Current GraphQL schema documented
- [ ] Custom resolvers identified and catalogued
- [ ] Database schema reviewed
- [ ] Third-party integrations listed
- [ ] Authentication/authorization patterns documented

---

## Phase 1: Database Preparation (1-3 days)

### Schema Migration

- [ ] Review current table naming conventions
- [ ] Decide on trinity pattern adoption (tb_/v_/tv_)
- [ ] Create migration script for table renames (if needed)
- [ ] Create views (`v_*`) for all tables
- [ ] Create computed views (`tv_*`) for common joins
- [ ] Test views return correct data
- [ ] Document any schema changes

### Functions and Procedures

- [ ] Identify all stored procedures/functions
- [ ] Review function signatures
- [ ] Rename functions to fn_* pattern (recommended)
- [ ] Test functions with psql
- [ ] Document function parameters and return types

### Security and Policies

- [ ] Review existing Row-Level Security (RLS) policies
- [ ] Test RLS policies with different users/tenants
- [ ] Document session variable requirements
- [ ] Plan multi-tenancy implementation (if needed)

---

## Phase 2: Type Definitions (1-2 days)

### GraphQL Types

- [ ] List all current GraphQL object types
- [ ] Convert each type to FraiseQL `@type` decorator
- [ ] Map types to database views (`sql_source` parameter)
- [ ] Add proper Python type hints (UUID, str, int, etc.)
- [ ] Handle nullable fields (`str | None`)
- [ ] Test type instantiation

### Input Types

- [ ] List all input types
- [ ] Convert to FraiseQL `@input` decorator
- [ ] Add validation logic (if needed)
- [ ] Test input parsing

### Enums and Scalars

- [ ] List all custom enums
- [ ] Convert to Python Enum classes
- [ ] Map custom scalars to Python types
- [ ] Test enum serialization

---

## Phase 3: Query Migration (2-3 days)

### Simple Queries

- [ ] List all query fields
- [ ] Convert each query to `@fraiseql.field` decorator
- [ ] Use `db.find_one()` for single object queries
- [ ] Use `db.find()` for list queries
- [ ] Add proper return type hints
- [ ] Test each query in GraphiQL

### Filtering and Pagination

- [ ] Implement `where` parameter for filtering
- [ ] Test filter operators (_eq, _ne, _like, _gt, etc.)
- [ ] Add `limit` and `offset` for pagination
- [ ] Test edge cases (empty results, large datasets)
- [ ] Document filter syntax for frontend team

### Relationships

- [ ] Identify all relationship fields
- [ ] Decide on resolver strategy (explicit vs computed views)
- [ ] Implement relationship resolvers
- [ ] Test N+1 query prevention
- [ ] Consider DataLoader for complex relationships

---

## Phase 4: Mutation Migration (2-3 days)

### Database Functions

- [ ] Create PostgreSQL function for each mutation
- [ ] Test functions directly with psql
- [ ] Document function inputs and outputs
- [ ] Handle errors and edge cases in functions

### Mutation Classes

- [ ] Create FraiseQL `@mutation` class for each mutation
- [ ] Map to corresponding PostgreSQL function
- [ ] Add input validation
- [ ] Test mutations in GraphiQL
- [ ] Verify return values match schema

### CASCADE Configuration

- [ ] Identify mutations that benefit from CASCADE
- [ ] Enable `enable_cascade=True` on appropriate mutations
- [ ] Test cache invalidation behavior
- [ ] Document CASCADE expectations for frontend

---

## Phase 5: Advanced Features (1-2 days)

### DataLoaders

- [ ] Identify N+1 query patterns
- [ ] Implement `@dataloader_field` decorators
- [ ] Test batching behavior
- [ ] Measure performance improvement

### Custom Resolvers

- [ ] List all custom field resolvers
- [ ] Implement as `@fraiseql.field` methods
- [ ] Test computed fields
- [ ] Verify performance

### Subscriptions (if needed)

- [ ] Plan subscription implementation
- [ ] Set up WebSocket support
- [ ] Implement subscription resolvers
- [ ] Test real-time updates

---

## Phase 6: Configuration and Setup (1 day)

### Application Setup

- [ ] Install FraiseQL: `pip install "fraiseql<2"`
- [ ] Configure `create_fraiseql_app()`
- [ ] Set database URL
- [ ] Enable Rust pipeline: `enable_rust_pipeline=True`
- [ ] Enable CASCADE: `enable_cascade=True`
- [ ] Configure CORS if needed
- [ ] Set up GraphiQL for development

### Environment Configuration

- [ ] Set environment variables
- [ ] Configure database connection pooling
- [ ] Set up logging
- [ ] Configure error handling
- [ ] Test configuration in dev environment

### Security Configuration

- [ ] Configure authentication
- [ ] Set up authorization rules
- [ ] Configure tenant ID headers (if multi-tenant)
- [ ] Test RLS with different users
- [ ] Review security best practices

---

## Phase 7: Testing (2-3 days)

### Unit Tests

- [ ] Convert resolver unit tests to pytest
- [ ] Test all queries individually
- [ ] Test all mutations individually
- [ ] Test error cases
- [ ] Achieve >80% code coverage

### Integration Tests

- [ ] Test complete GraphQL operations
- [ ] Test authentication flow
- [ ] Test authorization rules
- [ ] Test multi-tenancy (if applicable)
- [ ] Test error handling

### Performance Tests

- [ ] Run load tests with wrk/k6/artillery
- [ ] Measure query latency (p50, p95, p99)
- [ ] Measure throughput (req/s)
- [ ] Compare to baseline (should see 7-10x improvement)
- [ ] Identify bottlenecks

### End-to-End Tests

- [ ] Test with real frontend application
- [ ] Verify all features work
- [ ] Test error scenarios
- [ ] Verify cache invalidation (CASCADE)
- [ ] User acceptance testing

---

## Phase 8: Deployment Preparation (1-2 days)

### Infrastructure

- [ ] Set up production database
- [ ] Configure connection pooling
- [ ] Set up monitoring (Prometheus, Grafana)
- [ ] Configure logging (structured logs)
- [ ] Set up distributed tracing (OpenTelemetry)

### Documentation

- [ ] Update API documentation
- [ ] Document schema changes
- [ ] Create runbook for common issues
- [ ] Document rollback procedure
- [ ] Train team on new system

### Deployment Strategy

- [ ] Choose deployment strategy (blue-green, canary, etc.)
- [ ] Plan database migration execution
- [ ] Schedule maintenance window (if needed)
- [ ] Prepare rollback scripts
- [ ] Communicate timeline to stakeholders

---

## Phase 9: Deployment (1 day)

### Pre-Deployment

- [ ] Database backup created
- [ ] All tests passing
- [ ] Code review completed
- [ ] Deployment checklist reviewed
- [ ] Team on standby

### Deployment Steps

- [ ] Run database migrations
- [ ] Deploy FraiseQL application
- [ ] Verify health checks pass
- [ ] Run smoke tests
- [ ] Monitor error rates
- [ ] Monitor performance metrics

### Post-Deployment

- [ ] Verify all features working
- [ ] Monitor for 24 hours
- [ ] Check logs for errors
- [ ] Measure performance vs baseline
- [ ] Gather user feedback

---

## Phase 10: Post-Migration (1 week)

### Monitoring

- [ ] Set up alerts for errors
- [ ] Set up alerts for performance degradation
- [ ] Monitor database query performance
- [ ] Track user-reported issues
- [ ] Review logs daily

### Optimization

- [ ] Identify slow queries
- [ ] Add database indexes where needed
- [ ] Optimize expensive resolvers
- [ ] Tune connection pool settings
- [ ] Review and optimize computed views

### Documentation

- [ ] Document lessons learned
- [ ] Update migration guide with gotchas
- [ ] Create troubleshooting guide
- [ ] Share success metrics with stakeholders
- [ ] Celebrate with team! 🎉

---

## Success Criteria

### Performance Metrics

- [ ] Query latency improved 5-10x
- [ ] Throughput increased 5-10x
- [ ] Error rate < 0.1%
- [ ] P95 latency < 50ms
- [ ] Zero downtime during migration

### Functional Requirements

- [ ] All features working
- [ ] No data loss
- [ ] Authentication working
- [ ] Authorization working
- [ ] Frontend integration complete

### Team Satisfaction

- [ ] Team trained on new system
- [ ] Documentation complete
- [ ] Runbook created
- [ ] Monitoring in place
- [ ] Positive feedback from team

---

## Rollback Plan

### Triggers for Rollback

- Critical bugs affecting >10% of users
- Data integrity issues
- Performance degradation >50%
- Security vulnerabilities

### Rollback Steps

1. [ ] Switch traffic back to old system
2. [ ] Restore database if migrations ran
3. [ ] Notify stakeholders
4. [ ] Document rollback reason
5. [ ] Plan remediation

---

## Timeline Estimates

| Phase | Strawberry | Graphene | PostGraphile |
|-------|-----------|----------|--------------|
| **Pre-Migration** | 1 day | 1 day | 0.5 days |
| **Database Prep** | 2-3 days | 2 days | 0.5 days |
| **Type Definitions** | 1 day | 1 day | 0.5 days |
| **Query Migration** | 2-3 days | 2 days | 1 day |
| **Mutation Migration** | 2-3 days | 2-3 days | 1 day |
| **Advanced Features** | 1-2 days | 1 day | 1 day |
| **Configuration** | 1 day | 1 day | 0.5 days |
| **Testing** | 2-3 days | 2 days | 1 day |
| **Deployment** | 2 days | 2 days | 1 day |
| **Post-Migration** | 1 week | 1 week | 1 week |
| **Total** | **2-3 weeks** | **1-2 weeks** | **3-4 days** |

---

## Resources

- [Strawberry Migration Guide](./from-strawberry.md)
- [Graphene Migration Guide](./from-graphene.md)
- [PostGraphile Migration Guide](./from-postgraphile.md)
- [Trinity Pattern Guide](../core/trinity-pattern.md)
- [CASCADE Documentation](../features/graphql-cascade.md)
- [Production Deployment Checklist](../tutorials/production-deployment.md)

---

## Support

Need help with your migration?

- **Discord**: [Join Community](https://discord.gg/fraiseql)
- **GitHub Issues**: [Report Problems](https://github.com/fraiseql/fraiseql/issues)
- **Email**: support@fraiseql.com
- **Consulting**: Available for enterprise migrations

---

**Good luck with your migration! 🚀**
