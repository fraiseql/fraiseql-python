---
title: Installation
description: Install FraiseQL with Python, Rust extensions, and PostgreSQL setup
tags:
  - installation
  - setup
  - getting-started
  - requirements
---

# Installation Guide

🟢 Beginner · 🟡 Production - Complete installation guide for FraiseQL with different use cases, requirements, and troubleshooting.

## System Requirements

**Minimum Requirements:**

- **Python**: 3.13+
- **PostgreSQL**: 13+
- **Rust Toolchain**: 1.70+ (for building from source)
- **RAM**: 1GB (2GB+ with Rust compilation)
- **Disk**: 200MB (500MB+ with Rust toolchain)

**Recommended for Most Users:**

- **Python**: 3.13+
- **PostgreSQL**: 15+
- **Rust Toolchain**: Latest stable (for optimal performance)
- **RAM**: 4GB+ (for concurrent queries and compilation)
- **Disk**: 2GB+ (including Rust toolchain and dependencies)

## Quick Decision Tree

Choose your installation path:

```
What do you want to do?
├── 🚀 Quick Start (Recommended for most users - 5 minutes)
│   └── pip install fraiseql
│       └── fraiseql init my-project
│           └── fraiseql dev
├── 🧪 Development/Testing
│   └── pip install fraiseql[dev]
├── 📊 Production with Observability
│   └── pip install fraiseql[tracing]
├── 🔐 Production with Auth0
│   └── pip install fraiseql[auth0]
├── 📚 Documentation Building
│   └── pip install fraiseql[docs]
└── 🏗️ Everything (Development + Production)
    └── pip install fraiseql[all]
```



## Installation Options

### Option 1: Quick Start (Recommended for beginners)

**Use case**: First-time users, prototyping, learning FraiseQL

**Installation time**: < 2 minutes

```bash
# Install core FraiseQL
pip install fraiseql

# Verify installation
fraiseql --version

# Create your first project
fraiseql init my-first-api
cd my-first-api

# Start development server
fraiseql dev
```

**What you get**:

- ✅ Core GraphQL framework with Rust backend
- ✅ High-performance PostgreSQL integration
- ✅ Basic CLI tools
- ✅ Development server
- ❌ Testing tools
- ❌ Observability features
- ❌ Auth0 integration

### Option 2: Development Setup

**Use case**: Contributors, testing, development work

**Installation time**: < 5 minutes

```bash
# Install with development dependencies
pip install fraiseql[dev]

# Or install all optional dependencies
pip install fraiseql[all]
```

**What you get** (in addition to Quick Start):

- ✅ pytest, black, ruff, mypy
- ✅ Test containers for PostgreSQL
- ✅ OpenTelemetry tracing
- ✅ Auth0 authentication
- ✅ Documentation building tools
- ✅ Full Rust backend development support

### Option 3: Production with Tracing

**Use case**: Production deployments with monitoring and observability

**Installation time**: < 3 minutes

```bash
# Install with observability features
pip install fraiseql[tracing]
```

**What you get** (in addition to Quick Start):

- ✅ OpenTelemetry integration
- ✅ Jaeger tracing support
- ✅ Prometheus metrics
- ✅ PostgreSQL-native caching
- ✅ Error tracking and monitoring

### Option 4: Production with Auth0

**Use case**: Applications requiring enterprise authentication

**Installation time**: < 3 minutes

```bash
# Install with Auth0 support
pip install fraiseql[auth0]
```

**What you get** (in addition to Quick Start):

- ✅ Auth0 integration
- ✅ JWT token validation
- ✅ User authentication middleware
- ✅ Role-based access control

### Option 5: Documentation Building

**Use case**: Building documentation locally

**Installation time**: < 3 minutes

```bash
# Install with documentation tools
pip install fraiseql[docs]
```

**What you get** (in addition to Quick Start):

- ✅ MkDocs for documentation
- ✅ Material theme
- ✅ Documentation deployment tools

### Option 6: Everything

**Use case**: Full development and production setup

**Installation time**: < 5 minutes

```bash
# Install everything (development + production features)
pip install fraiseql[all]
```

**What you get** (all features from all options above):

- ✅ All Quick Start features
- ✅ All Development features (testing, code quality)
- ✅ All Tracing features (OpenTelemetry, monitoring)
- ✅ All Auth0 features
- ✅ All Documentation features

## Feature Matrix

| Feature | Quick Start | Development | Tracing | Auth0 | Docs | All |
|---------|-------------|-------------|---------|-------|------|-----|
| **Core GraphQL** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **PostgreSQL Integration** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **CLI Tools** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Development Server** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Testing Tools** | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Code Quality** | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| **OpenTelemetry** | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Auth0 Integration** | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ |
| **Documentation Tools** | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |
| **PostgreSQL Caching** | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Error Monitoring** | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |

## Verification Checklist

After installation, verify everything works:

### 1. Python Version Check

```bash
python --version  # Should be 3.13+
```

### 2. Rust Toolchain Check

```bash
# Check if Rust is installed
rustc --version  # Should show version 1.70+

# Check Cargo (Rust package manager)
cargo --version  # Should show version

# Verify Rust compilation works
rustc --print target-list | head -5
```

### 3. FraiseQL Installation Check

```bash
fraiseql --version  # Should show version number (includes Rust backend)
```

### 4. Rust Extension Verification

```bash
# Test that Rust backend loads correctly
python -c "from fraiseql.core.database import DatabasePool; print('✅ Rust backend available')"

# Verify performance optimizations are active
python -c "import fraiseql; print('✅ FraiseQL with Rust backend loaded')"
```

### 5. PostgreSQL Connection Check

```bash
# Make sure PostgreSQL is running
psql --version

# Test connection (replace with your database URL)
psql "postgresql://localhost/postgres" -c "SELECT version();"
```

### 6. Create Test Project

```bash
# Create a test project
fraiseql init test-project
cd test-project

# Check project structure
ls -la
# Should see: src/, pyproject.toml, etc.
```

### 7. Run Development Server

```bash
# Start the dev server
fraiseql dev

# In another terminal, test the GraphQL endpoint
curl http://localhost:8000/graphql \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __typename }"}'
```

## Troubleshooting

### Common Issues

#### Issue: "Rust toolchain not found"

**Solution**: Install Rust toolchain

```bash
# Install Rust using rustup (recommended)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# Verify installation
rustc --version
cargo --version

# Add to PATH permanently (add to ~/.bashrc or ~/.zshrc)
export PATH="$HOME/.cargo/bin:$PATH"
```

#### Issue: "Rust extension failed to build"

**Solution**: Install build dependencies and retry

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install build-essential pkg-config libssl-dev

# macOS
xcode-select --install

# Windows (use Rust for Windows installer)

# Then reinstall FraiseQL
pip uninstall fraiseql
pip install fraiseql --no-cache-dir
```

#### Issue: "Python version 3.13+ required"

**Solution**: Upgrade Python

```bash
# Check current version
python --version

# Install Python 3.13+ (Ubuntu/Debian)
sudo apt update
sudo apt install python3.13 python3.13-venv

# Or use pyenv
pyenv install 3.13.0
pyenv global 3.13.0
```

#### Issue: "ModuleNotFoundError: No module named 'fraiseql'"

**Solution**: Install FraiseQL

```bash
# Make sure you're in the right environment
pip install fraiseql

# Or reinstall
pip uninstall fraiseql
pip install fraiseql
```

#### Issue: "fraiseql command not found"

**Solution**: Add to PATH or use python -m

```bash
# Option 1: Use python module
python -m fraiseql --version

# Option 2: Check pip installation
pip show fraiseql

# Option 3: Reinstall with --force
pip install --force-reinstall fraiseql
```

#### Issue: "PostgreSQL connection failed"

**Solution**: Check PostgreSQL setup

```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Start PostgreSQL if needed
sudo systemctl start postgresql

# Create a test database
createdb test_db

# Test connection
psql test_db -c "SELECT 1;"
```

#### Issue: "Permission denied" on project creation

**Solution**: Check directory permissions

```bash
# Make sure you can write to current directory
mkdir test-dir && rmdir test-dir

# Or specify a different path
fraiseql init /tmp/my-project
```

#### Issue: "Port 8000 already in use"

**Solution**: Use a different port

```bash
# The dev server doesn't have a port option yet
# Kill the process using port 8000
lsof -ti:8000 | xargs kill -9

# Or use a different port (not currently supported)
```

#### Issue: "Rust backend not available"

**Solution**: Check Rust extension loading

```bash
# Test Rust backend import
python -c "from fraiseql.core.database import DatabasePool; print('Rust backend OK')"

# If import fails, reinstall with Rust
pip uninstall fraiseql
pip install fraiseql --no-cache-dir --verbose

# Check for missing dependencies
python -c "import sys; print('Python path:'); [print(p) for p in sys.path]"
```

### Advanced Troubleshooting

#### Check Installation Details

```bash
# Show where FraiseQL is installed
pip show fraiseql

# List all installed packages
pip list | grep fraiseql

# Check for conflicting installations
pip check
```

#### Clean Reinstall

```bash
# Remove all FraiseQL packages
pip uninstall fraiseql fraiseql-confiture -y

# Clear pip cache
pip cache purge

# Reinstall
pip install fraiseql[dev]
```

#### Environment Issues

```bash
# Check Python path
python -c "import sys; print(sys.path)"

# Check for virtual environment
which python
echo $VIRTUAL_ENV

# Activate virtual environment if needed
source venv/bin/activate  # or your venv path
```

## Platform-Specific Notes

### macOS

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# Install PostgreSQL
brew install postgresql

# Start PostgreSQL
brew services start postgresql

# Create database
createdb mydb
```

### Ubuntu/Debian

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# Install build dependencies for Rust
sudo apt update
sudo apt install build-essential pkg-config libssl-dev

# Install Python 3.13
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.13 python3.13-venv

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Start PostgreSQL
sudo systemctl start postgresql

# Create database
sudo -u postgres createdb mydb
```

### Windows

```bash
# Install Rust toolchain from https://rustup.rs/
# Or use winget/chocolatey:
winget install --id Microsoft.VisualStudio.2022.BuildTools  # Includes Rust support
# Or: choco install rust

# Install Python 3.13 from python.org

# Install PostgreSQL from postgresql.org
# Or use chocolatey:
choco install postgresql

# Create database
createdb mydb
```

### Docker

```bash
# Use the official PostgreSQL image
docker run --name postgres -e POSTGRES_PASSWORD=mypass -d -p 5432:5432 postgres:15

# Connect to container
docker exec -it postgres psql -U postgres
```

## Next Steps

After successful installation:

1. **[Quickstart Guide](quickstart.md)** - Build your first API
2. **[Core Concepts](../core/concepts-glossary.md)** - Understand FraiseQL patterns
3. **Examples (../examples/)** - See real implementations
4. **[Configuration](../core/configuration.md)** - Advanced setup options

## Getting Help

- **Installation issues**: Check this troubleshooting section
- **Framework questions**: See [Quickstart Guide](quickstart.md)
- **Bug reports**: [GitHub Issues](../issues)
- **Community**: [GitHub Discussions](../discussions)

---

*Installation Guide - Choose your path, verify setup, troubleshoot issues*
