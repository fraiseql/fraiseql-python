.PHONY: help test test-unit test-integration lint format check clean db-up db-down db-logs db-reset db-status db-verify demo-start demo-stop demo-logs demo-status demo-restart demo-clean examples-start examples-stop examples-logs examples-status examples-clean prod-start prod-stop prod-logs prod-status prod-clean prod-examples-start prod-examples-stop prod-examples-logs prod-examples-status prod-examples-clean release-check release-build release-publish release

# Default target
help:
	@echo "FraiseQL v1 Development Commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test               - Run all tests"
	@echo "  make test-unit          - Run unit tests only (fast, no database)"
	@echo "  make test-integration   - Run integration tests (requires Docker)"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint               - Run ruff linter"
	@echo "  make format             - Format code with ruff"
	@echo "  make check              - Run all checks (format + lint + test)"
	@echo "  make clean              - Clean build artifacts"
	@echo ""
	@echo "Database (Docker):"
	@echo "  make db-up              - Start test databases (PostgreSQL, MySQL)"
	@echo "  make db-down            - Stop test databases"
	@echo "  make db-logs            - View database logs"
	@echo "  make db-reset           - Reset test databases (remove volumes)"
	@echo "  make db-status          - Check database health"
	@echo ""
	@echo "Docker Demo (Newcomers):"
	@echo "  make demo-start         - Start single-example stack (blog only)"
	@echo "  make demo-stop          - Stop demo stack"
	@echo "  make demo-logs          - View demo logs"
	@echo "  make demo-status        - Check demo health"
	@echo "  make demo-restart       - Restart demo stack"
	@echo "  make demo-clean         - Remove demo volumes and stop"
	@echo ""
	@echo "Docker Examples (Advanced - with local build):"
	@echo "  make examples-start     - Start multi-example stack (blog, ecommerce, streaming)"
	@echo "  make examples-stop      - Stop examples stack"
	@echo "  make examples-logs      - View examples logs"
	@echo "  make examples-status    - Check examples health"
	@echo "  make examples-clean     - Remove examples volumes and stop"
	@echo ""
	@echo "Docker Production (Pre-built Images - No Local Build):"
	@echo "  make prod-start         - Start production demo (single example, pre-built)"
	@echo "  make prod-stop          - Stop production demo"
	@echo "  make prod-status        - Check production health"
	@echo "  make prod-logs          - View production logs"
	@echo "  make prod-clean         - Remove production volumes"
	@echo "  make prod-examples-start - Start production multi-example (all 3, pre-built)"
	@echo "  make prod-examples-stop  - Stop production multi-example"
	@echo "  make prod-examples-status - Check multi-example health"
	@echo "  make prod-examples-clean  - Remove multi-example volumes"
	@echo ""
	@echo "Release (PyPI):"
	@echo "  make release-check       - Pre-release checks (lint, tests, version)"
	@echo "  make release-build       - Build wheel+sdist (runs checks first)"
	@echo "  make release-publish     - Publish dist/ to PyPI"
	@echo "  make release             - Full pipeline: check -> build -> publish"
	@echo ""

# ============================================================================
# Python Development
# ============================================================================

# Run all tests (unit + integration)
test: test-unit test-integration

# Run unit tests only (no database required)
test-unit:
	@echo "Running unit tests..."
	@uv run pytest tests/unit/ -q

# Run integration tests (requires Docker databases)
test-integration: db-up
	@echo "Running integration tests..."
	@sleep 2
	@uv run pytest tests/integration/ -q

# Run ruff linter
lint:
	@uv run ruff check src/

# Format code
format:
	@uv run ruff format src/

# Run all checks
check: format lint test-unit

# Clean build artifacts
clean:
	@rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ============================================================================
# Docker-based Test Database Management
# ============================================================================

# Start test databases (PostgreSQL + MySQL)
db-up:
	@echo "Starting test databases..."
	@docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for databases to be healthy..."
	@sleep 3
	@docker compose -f docker-compose.test.yml ps

# Stop test databases
db-down:
	@echo "Stopping test databases..."
	@docker compose -f docker-compose.test.yml down

# View database logs
db-logs:
	@docker compose -f docker-compose.test.yml logs -f

# Reset test databases (remove volumes)
db-reset:
	@echo "Resetting test databases (removing volumes)..."
	@docker compose -f docker-compose.test.yml down -v
	@docker compose -f docker-compose.test.yml up -d
	@sleep 3
	@echo "Databases reset and started"

# Check database health status
db-status:
	@echo "Database status:"
	@docker compose -f docker-compose.test.yml ps

# Verify test data
db-verify:
	@echo "Verifying PostgreSQL test data..."
	@docker compose -f docker-compose.test.yml exec -T postgres-test \
		psql -U fraiseql_test -d test_fraiseql -c "SELECT 'v_user' AS view, COUNT(*) FROM v_user UNION ALL SELECT 'v_post', COUNT(*) FROM v_post UNION ALL SELECT 'v_product', COUNT(*) FROM v_product;"

# ============================================================================
# Docker Demo Platform (Newcomer Onboarding)
# ============================================================================

## Start demo stack (GraphQL IDE, tutorial, server, database)
demo-start:
	@echo "Starting FraiseQL demo stack..."
	@docker compose -f docker/docker-compose.demo.yml up -d
	@echo ""
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@docker compose -f docker/docker-compose.demo.yml ps
	@echo ""
	@echo "Demo stack is running!"
	@echo ""
	@echo "Open your browser:"
	@echo "  GraphQL IDE:      http://localhost:3000"
	@echo "  Tutorial:         http://localhost:3001"
	@echo "  Admin Dashboard:  http://localhost:3002"
	@echo "  API Server:       http://localhost:8000"
	@echo ""

## Stop demo stack
demo-stop:
	@echo "Stopping FraiseQL demo stack..."
	@docker compose -f docker/docker-compose.demo.yml down

## View demo logs
demo-logs:
	@docker compose -f docker/docker-compose.demo.yml logs -f

## Check demo health status
demo-status:
	@echo "Demo Stack Status:"
	@docker compose -f docker/docker-compose.demo.yml ps
	@echo ""
	@echo "Service Health:"
	@echo -n "  FraiseQL Server: "
	@curl -s http://localhost:8000/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  GraphQL IDE: "
	@curl -s http://localhost:3000/ > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Tutorial: "
	@curl -s http://localhost:3001/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  PostgreSQL: "
	@docker compose -f docker/docker-compose.demo.yml exec -T postgres-blog pg_isready -U fraiseql > /dev/null 2>&1 && echo "Healthy" || echo "Unhealthy"

## Restart demo stack
demo-restart: demo-stop demo-start

## Remove demo volumes and stop (fresh start)
demo-clean:
	@echo "Cleaning up demo stack (removing volumes)..."
	@docker compose -f docker/docker-compose.demo.yml down -v
	@echo "Run 'make demo-start' to start fresh"

# ============================================================================
# Docker Multi-Example Stack (Blog + E-Commerce + Streaming)
# ============================================================================

## Start multi-example stack (all 3 domains simultaneously)
examples-start:
	@echo "Starting FraiseQL multi-example stack..."
	@echo "   Running: Blog, E-Commerce, and Streaming examples"
	@docker compose -f docker/docker-compose.examples.yml up -d
	@echo ""
	@echo "Waiting for services to be healthy..."
	@sleep 8
	@docker compose -f docker/docker-compose.examples.yml ps
	@echo ""
	@echo "Multi-example stack is running!"
	@echo ""
	@echo "Open your browser:"
	@echo "  Blog IDE:           http://localhost:3000"
	@echo "  E-Commerce IDE:     http://localhost:3100"
	@echo "  Streaming IDE:      http://localhost:3200"
	@echo "  Tutorial:           http://localhost:3001"
	@echo "  Admin Dashboard:    http://localhost:3002"
	@echo ""

## Stop multi-example stack
examples-stop:
	@echo "Stopping FraiseQL multi-example stack..."
	@docker compose -f docker/docker-compose.examples.yml down

## View multi-example logs
examples-logs:
	@docker compose -f docker/docker-compose.examples.yml logs -f

## Check multi-example health status
examples-status:
	@echo "Multi-Example Stack Status:"
	@docker compose -f docker/docker-compose.examples.yml ps
	@echo ""
	@echo "Service Health:"
	@echo -n "  Blog Server: "
	@curl -s http://localhost:8000/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  E-Commerce Server: "
	@curl -s http://localhost:8001/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Streaming Server: "
	@curl -s http://localhost:8002/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Tutorial: "
	@curl -s http://localhost:3001/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Admin Dashboard: "
	@curl -s http://localhost:3002/health > /dev/null && echo "Healthy" || echo "Unhealthy"

## Remove multi-example volumes and stop (fresh start)
examples-clean:
	@echo "Cleaning up multi-example stack (removing volumes)..."
	@docker compose -f docker/docker-compose.examples.yml down -v
	@echo "Run 'make examples-start' to start fresh"

# ============================================================================
# Docker Production Stack (Pre-built Images from Docker Hub)
# ============================================================================

## Start production demo stack (pre-built images, no local build)
prod-start:
	@echo "Starting FraiseQL production demo stack (pre-built images)..."
	@docker compose -f docker/docker-compose.prod.yml up -d
	@echo ""
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@docker compose -f docker/docker-compose.prod.yml ps
	@echo ""
	@echo "Production demo stack is running!"
	@echo ""
	@echo "Open your browser:"
	@echo "  GraphQL IDE:      http://localhost:3000"
	@echo "  Tutorial:         http://localhost:3001"
	@echo "  Admin Dashboard:  http://localhost:3002"
	@echo "  API Server:       http://localhost:8000"
	@echo ""

## Stop production demo stack
prod-stop:
	@echo "Stopping FraiseQL production demo stack..."
	@docker compose -f docker/docker-compose.prod.yml down

## View production demo logs
prod-logs:
	@docker compose -f docker/docker-compose.prod.yml logs -f

## Check production demo health status
prod-status:
	@echo "Production Demo Stack Status:"
	@docker compose -f docker/docker-compose.prod.yml ps
	@echo ""
	@echo "Service Health:"
	@echo -n "  FraiseQL Server: "
	@curl -s http://localhost:8000/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  GraphQL IDE: "
	@curl -s http://localhost:3000/ > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Tutorial: "
	@curl -s http://localhost:3001/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  PostgreSQL: "
	@docker compose -f docker/docker-compose.prod.yml exec -T postgres-blog pg_isready -U fraiseql > /dev/null 2>&1 && echo "Healthy" || echo "Unhealthy"

## Clean production demo stack
prod-clean:
	@echo "Cleaning up production demo stack (removing volumes)..."
	@docker compose -f docker/docker-compose.prod.yml down -v
	@echo "Run 'make prod-start' to start fresh"

## Start production multi-example stack (all 3 examples with pre-built images)
prod-examples-start:
	@echo "Starting FraiseQL production multi-example stack..."
	@echo "   Running: Blog, E-Commerce, and Streaming examples (pre-built images)"
	@docker compose -f docker/docker-compose.prod-examples.yml up -d
	@echo ""
	@echo "Waiting for services to be healthy..."
	@sleep 8
	@docker compose -f docker/docker-compose.prod-examples.yml ps
	@echo ""
	@echo "Production multi-example stack is running!"
	@echo ""
	@echo "Open your browser:"
	@echo "  Blog IDE:           http://localhost:3000"
	@echo "  E-Commerce IDE:     http://localhost:3100"
	@echo "  Streaming IDE:      http://localhost:3200"
	@echo "  Tutorial:           http://localhost:3001"
	@echo "  Admin Dashboard:    http://localhost:3002"
	@echo ""

## Stop production multi-example stack
prod-examples-stop:
	@echo "Stopping FraiseQL production multi-example stack..."
	@docker compose -f docker/docker-compose.prod-examples.yml down

## View production multi-example logs
prod-examples-logs:
	@docker compose -f docker/docker-compose.prod-examples.yml logs -f

## Check production multi-example health status
prod-examples-status:
	@echo "Production Multi-Example Stack Status:"
	@docker compose -f docker/docker-compose.prod-examples.yml ps
	@echo ""
	@echo "Service Health:"
	@echo -n "  Blog Server: "
	@curl -s http://localhost:8000/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  E-Commerce Server: "
	@curl -s http://localhost:8001/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Streaming Server: "
	@curl -s http://localhost:8002/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Tutorial: "
	@curl -s http://localhost:3001/health > /dev/null && echo "Healthy" || echo "Unhealthy"
	@echo -n "  Admin Dashboard: "
	@curl -s http://localhost:3002/health > /dev/null && echo "Healthy" || echo "Unhealthy"

## Clean production multi-example stack
prod-examples-clean:
	@echo "Cleaning up production multi-example stack (removing volumes)..."
	@docker compose -f docker/docker-compose.prod-examples.yml down -v
	@echo "Run 'make prod-examples-start' to start fresh"

# ============================================================================
# Python Package Release (fraiseql on PyPI)
# ============================================================================

# Extract version from pyproject.toml
VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')

## Pre-release checks: lint, tests, version consistency, clean working tree
release-check:
	@echo "Running pre-release checks for fraiseql v$(VERSION)..."
	@echo ""
	@echo "-- Checking clean working tree --"
	@git diff --quiet && git diff --cached --quiet || { echo "Working tree is dirty. Commit or stash changes first."; exit 1; }
	@echo "Working tree is clean"
	@echo ""
	@echo "-- Checking version consistency (pyproject.toml vs fraiseql_rs/Cargo.toml) --"
	@CARGO_VERSION=$$(grep '^version' fraiseql_rs/Cargo.toml | head -1 | sed 's/.*"\(.*\)"/\1/') && \
		if [ "$(VERSION)" != "$$CARGO_VERSION" ]; then \
			echo "Version mismatch: pyproject.toml=$(VERSION) vs fraiseql_rs/Cargo.toml=$$CARGO_VERSION"; \
			exit 1; \
		fi
	@echo "Version $(VERSION) consistent"
	@echo ""
	@echo "-- Running ruff checks --"
	@uv run ruff check src/fraiseql/ || { echo "Ruff check failed"; exit 1; }
	@uv run ruff format --check src/fraiseql/ || { echo "Ruff format check failed"; exit 1; }
	@echo "Ruff checks passed"
	@echo ""
	@echo "-- Running unit tests --"
	@uv run pytest tests/unit/ -x -q --ignore=tests/unit/security/test_kms_vault_containers.py || { echo "Unit tests failed"; exit 1; }
	@echo ""
	@echo "All pre-release checks passed for v$(VERSION)"

## Build wheel and sdist with maturin
release-build: release-check
	@echo ""
	@echo "Building fraiseql v$(VERSION)..."
	@rm -rf dist/
	@uv run maturin build --release
	@mkdir -p dist/
	@cp fraiseql_rs/target/wheels/fraiseql-$(VERSION)-*.whl dist/
	@echo ""
	@echo "Build artifacts:"
	@ls -lh dist/
	@echo ""
	@echo "-- Validating with twine --"
	@uv run twine check dist/* || { echo "Twine check failed"; exit 1; }
	@echo "Package validation passed"

## Publish to PyPI (requires TWINE_USERNAME/TWINE_PASSWORD or ~/.pypirc)
release-publish:
	@echo ""
	@echo "Publishing fraiseql v$(VERSION) to PyPI..."
	@test -d dist/ || { echo "No dist/ directory. Run 'make release-build' first."; exit 1; }
	@uv run twine upload dist/*
	@echo ""
	@echo "fraiseql v$(VERSION) published to PyPI"
	@echo "   https://pypi.org/project/fraiseql/$(VERSION)/"

## Full release pipeline: check -> build -> publish
release: release-build release-publish
	@echo ""
	@echo "Release v$(VERSION) complete!"
