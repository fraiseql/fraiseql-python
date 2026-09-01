# FraiseQL Version Status & Roadmap

**Last Updated**: January 5, 2025
**Current Stable**: v1.9.6

---

## 📊 Architecture Overview

FraiseQL uses a unified architecture with exclusive Rust pipeline execution for all queries.

| Component | Location | Status | Purpose |
|-----------|----------|--------|---------|
| **FraiseQL Framework** | Root level | ✅ Production | Complete GraphQL framework with Rust pipeline |
| **Rust Pipeline** | [`fraiseql_rs/`](../../fraiseql_rs/) | ✅ Core | Exclusive query execution engine (7-10x faster) |
| **Examples** | `examples/` | ✅ Reference | Production-ready application patterns |
| **Documentation** | [`docs/`](../../docs/) | ✅ Current | Comprehensive guides and tutorials |

---

## 🎯 Getting Started

### **For Production Applications**

```bash
# Install FraiseQL with exclusive Rust pipeline
pip install "fraiseql<2"
```

**Why FraiseQL?**

- ✅ **Production stable** with exclusive Rust pipeline execution
- ✅ **7-10x faster** than traditional Python GraphQL frameworks
- ✅ **Complete feature set** (APQ, caching, monitoring, security)
- ✅ **Active maintenance** and performance optimizations
- ✅ **Unified architecture** - no version choices to manage

### **For Learning** → Explore Examples

```bash
# See production patterns and architectures
cd examples/
ls -la  # 20+ working examples with Rust pipeline
```

### **For Contributors**

- Build on the unified Rust pipeline architecture
- Add features, fix bugs, improve documentation
- See [Contributing Guide](../../CONTRIBUTING.md)

---

## 📈 Version Stability Definitions

### **Production Stable** 🟢

- ✅ Zero breaking changes in minor versions
- ✅ Security patches and critical bug fixes
- ✅ New features in minor versions only
- ✅ Long-term support (18+ months)

### **Maintenance Mode** 🟡

- ✅ Critical security fixes only
- ✅ No new features
- ✅ Migration guides provided
- ⚠️ Limited support timeframe

### **Experimental** 🔴

- ⚠️ Breaking changes without notice
- ⚠️ No stability guarantees
- ⚠️ Not recommended for production
- ✅ Rapid iteration and exploration

### **Showcase/Portfolio** 🎭

- 📚 Interview-quality code examples
- 📚 Demonstrates architectural patterns
- ❌ Not intended for production use
- ✅ Learning and demonstration value

---

## 🗺️ Development Roadmap

### **Current Architecture** (Unified Rust Pipeline)

**Status**: Production stable with exclusive Rust execution
**Timeline**: Ongoing maintenance and enhancement
**Architecture**: PostgreSQL → Rust Pipeline → HTTP Response

**Core Components**:

- **Rust Pipeline**: Exclusive query execution (7-10x performance)
- **Python Framework**: Type-safe GraphQL API layer
- **PostgreSQL Integration**: Native JSONB views and functions
- **Enterprise Features**: Security, monitoring, caching

**Ongoing Development**:

- Performance optimizations in Rust pipeline
- Additional caching strategies
- Enhanced monitoring and observability
- New production example applications
- Advanced security patterns

### **Architecture Evolution**

FraiseQL's exclusive Rust pipeline provides a stable, high-performance foundation. Future enhancements build upon this unified architecture rather than introducing new versions to manage.

---

## 🔄 Development Policy

### **Architecture Stability**

FraiseQL maintains backward compatibility within the unified Rust pipeline architecture. Breaking changes are rare and announced well in advance.

### **Feature Evolution**

- New features enhance the existing Rust pipeline
- Performance improvements are seamless upgrades
- Enterprise features extend current capabilities

### **Support Commitment**

- **Current release**: Full support + new features
- **Security updates**: Critical fixes for previous releases
- **Documentation**: Comprehensive guides for all features

---

## 🚨 Architecture Notes

### **Exclusive Rust Pipeline**

- FraiseQL uses a single, unified architecture
- All queries execute through the Rust pipeline for optimal performance
- No alternative execution modes to choose between

### **Required Components**

- **Rust Pipeline** (`fraiseql_rs`): Core execution engine
- **Python Framework**: API layer and type system
- **PostgreSQL**: Data persistence with JSONB views

### **Directory Structure**

- Root level: Production framework with Rust pipeline
- `examples/`: Reference implementations
- `docs/`: Comprehensive documentation
- `fraiseql_rs/`: Rust performance engine

---

## 📞 Getting Help

### **Documentation & Examples**

- [Installation Guide](../getting-started/installation/)
- [Quickstart](../getting-started/quickstart/)
- Examples (../../examples/) - 20+ production patterns
- [API Reference](../reference/)

### **Architecture Questions**

- Review [Architecture Overview](../architecture/) for technical details
- Check [Documentation](../README/) for comprehensive guides
- Open issue for clarification

### **Performance & Features**

- Rust pipeline provides 7-10x performance improvement
- All features work within unified architecture
- No version management required

---

## 🔍 Architecture Evolution

### **Unified Rust Pipeline** (2025)

- ✅ Exclusive Rust execution for all queries
- ✅ 7-10x performance improvement over Python-only frameworks
- ✅ Production stable with comprehensive monitoring
- ✅ Enterprise security and compliance features

### **Rust Integration** (2024-2025)

- ⚡ Rust pipeline development and optimization
- 🏗️ Architecture stabilization
- 📊 Advanced monitoring and observability
- 🐛 Performance bug fixes and improvements

### **Framework Foundation** (2023-2024)

- 🏗️ Core GraphQL framework development
- 📚 Comprehensive documentation
- 🔧 Developer tooling and examples

---

*This document reflects FraiseQL's unified Rust pipeline architecture. Last updated: January 5, 2025*
