# SLSA Provenance Verification Guide

**Target Audience:** Procurement officers, security auditors, compliance officers (non-technical)
**Time Required:** 10-15 minutes
**Prerequisites:** None (web browser and command line basics)
**Last Updated:** 2025-12-08

---

## Overview

This guide helps you verify FraiseQL's supply chain security claims by checking **SLSA provenance** - cryptographic proof that the software you're evaluating was built from trusted source code without tampering.

**What you'll learn:**

- ✅ What SLSA is and why it matters for procurement
- ✅ How to verify FraiseQL releases in 3 simple steps
- ✅ What to include in procurement documentation
- ✅ How to demonstrate compliance to auditors

**No specialized security knowledge required** - this guide uses copy-paste commands and web-based tools.

---

## What is SLSA?

**SLSA** (Supply-chain Levels for Software Artifacts, pronounced "salsa") is a **security framework** developed by Google and the OpenSSF (Open Source Security Foundation) to prevent supply chain attacks on software.

### Why SLSA Matters for Procurement

**The Problem:**
Software supply chain attacks (like SolarWinds, Log4j) can compromise thousands of organizations through a single tampered package. Traditional security checks can't detect if attackers modified source code during the build process.

**The Solution:**
SLSA provides **cryptographic proof** that:

1. Software was built from specific source code (not tampered with)
2. The build process used known, auditable systems
3. No unauthorized changes occurred between source and distribution

**For Procurement Officers:**

- ✅ **Verify vendor claims** - Don't just trust "we're secure," verify cryptographically
- ✅ **Meet compliance requirements** - Executive Order 14028, NIST 800-161, FedRAMP
- ✅ **Reduce risk** - Detect compromised packages before deployment
- ✅ **Audit trail** - Permanent record of verification for audits

### SLSA Levels

SLSA defines 4 levels of supply chain security (Build L1-L3, higher = more secure):

| Level | Description | FraiseQL Status |
|-------|-------------|-----------------|
| **Build L1** | Build process is documented | ✅ Achieved |
| **Build L2** | Build provenance is generated | ✅ Achieved |
| **Build L3** | Source and build platforms are hardened | ✅ **Current Level** |

**FraiseQL is SLSA Build Level 3** - the highest practical level for most organizations.

**What this means:**

- Builds run on hardened GitHub-hosted runners (not maintainer laptops)
- All build steps are auditable and tamper-resistant
- Provenance is signed with Sigstore (keyless cryptographic signing)
- No human has write access to release artifacts

---

## How to Verify FraiseQL Provenance

You can verify FraiseQL releases using **three methods** (choose based on your technical comfort level):

### Method 1: Web-Based Verification (No Installation Required)

**Best for:** Procurement officers, non-technical reviewers
**Time:** 5 minutes

#### Step 1: Find the Release

1. Go to FraiseQL's GitHub releases: https://github.com/fraiseql/fraiseql/releases
2. Click on the **latest release** (e.g., `v0.1.0`)
3. Scroll to **"🔐 Artifact Verification"** section in the release notes

#### Step 2: View Attestations

1. In the release page, look for the **"Attestations"** badge (right sidebar)
2. Click **"Show all attestations"**
3. You should see:
   - **SLSA Provenance** attestation for each wheel (`.whl`) and source distribution (`.tar.gz`)
   - **Signed by GitHub Actions** via Sigstore
   - **Certificate verification** status (should show ✅)

#### Step 3: Verify Details

Click on any attestation to see:

- **Source repository**: `github.com/fraiseql/fraiseql`
- **Build workflow**: `.github/workflows/publish.yml`
- **Build commit**: Exact Git commit SHA used for build
- **Builder**: GitHub-hosted runner (ubuntu-latest)
- **Signature**: Sigstore certificate chain

**What to look for:**

- ✅ Attestation status: **Verified**
- ✅ Issuer: `https://token.actions.githubusercontent.com`
- ✅ Workflow: `fraiseql/fraiseql/.github/workflows/publish.yml`
- ✅ Certificate validity: **Valid** (not expired)

#### Step 4: Document for Procurement

**Screenshot the attestation page** and include in procurement documentation with:

- Release version verified (e.g., `v0.1.0`)
- Verification date
- Attestation status (Verified ✅)
- Your name and role

---

### Method 2: GitHub CLI Verification (Recommended for Technical Users)

**Best for:** Security teams, technical procurement officers
**Time:** 10 minutes
**Prerequisites:** GitHub CLI installed

#### Step 1: Install GitHub CLI

```bash
# macOS (Homebrew)
brew install gh

# Windows (Winget)
winget install GitHub.cli

# Linux (Debian/Ubuntu)
sudo apt install gh

# Verify installation
gh --version
```

#### Step 2: Authenticate (First Time Only)

```bash
gh auth login
# Follow prompts to authenticate with GitHub
```

#### Step 3: Download a FraiseQL Wheel

```bash
# Create verification directory
mkdir fraiseql-verification
cd fraiseql-verification

# Download latest release wheel
gh release download --repo fraiseql/fraiseql --pattern "*.whl"
```

**Expected output:**

```
Downloading fraiseql-0.1.0-py3-none-any.whl
✓ Downloaded fraiseql-0.1.0-py3-none-any.whl
```

#### Step 4: Verify SLSA Provenance

```bash
# Verify attestation for the downloaded wheel
gh attestation verify fraiseql-*.whl --owner fraiseql --repo fraiseql
```

**Expected output:**

```
Loaded digest sha256:abc123... for file://fraiseql-0.1.0-py3-none-any.whl
Loaded 1 attestation from GitHub API
✓ Verification succeeded!

sha256:abc123... was attested by:
REPO          PREDICATE_TYPE          WORKFLOW
fraiseql/fraiseql  https://slsa.dev/provenance/v1  .github/workflows/publish.yml@refs/tags/v0.1.0
```

**What this means:**

- ✅ The wheel was built by the official FraiseQL repository
- ✅ Using the published build workflow (auditable on GitHub)
- ✅ From a tagged release (not a random commit)
- ✅ Signature verified via Sigstore

#### Step 5: Inspect Provenance Details (Optional)

```bash
# View full provenance data
gh attestation verify fraiseql-*.whl --owner fraiseql --repo fraiseql --format json > provenance.json

# View human-readable summary
cat provenance.json | jq '.verificationResult'
```

**Key fields to check:**

- `buildType`: Should be `"https://slsa.dev/provenance/v1"`
- `builder.id`: Should reference GitHub Actions
- `invocation.configSource.uri`: Should be `"git+https://github.com/fraiseql/fraiseql@refs/tags/v*"`

---

### Method 3: PyPI Attestation Verification (Future)

**Best for:** Python package managers, automated verification
**Time:** 2 minutes
**Status:** 🔄 Coming in pip 25.0+ (Q1 2025)

#### Current Status

FraiseQL publishes attestations to PyPI using **PEP 740** (PyPI attestations), but pip doesn't support verification yet.

**When pip 25.0 releases:**

```bash
# Install with automatic attestation verification
pip install fraiseql==0.1.0 --verify-attestations

# Should show:
# ✓ Verified attestation for fraiseql-0.1.0-py3-none-any.whl
# ✓ Installing fraiseql-0.1.0
```

**Manual verification (advanced users):**

```bash
# Download attestation bundle
pip download fraiseql==0.1.0 --no-deps
# Attestations are automatically fetched by pip 25.0+
```

**Reference:** [PEP 740 - Index support for digital attestations](https://peps.python.org/pep-0740/)

---

## Understanding the Provenance Data

### What's Included in SLSA Provenance?

FraiseQL's SLSA provenance includes:

1. **Build Invocation**
   - Source repository: `github.com/fraiseql/fraiseql`
   - Git commit SHA: Exact version of source code
   - Build trigger: Tag push (e.g., `refs/tags/v0.1.0`)

2. **Build Environment**
   - Builder: GitHub Actions (ubuntu-latest)
   - Workflow: `.github/workflows/publish.yml`
   - Runner: GitHub-hosted (not developer machine)

3. **Build Steps**
   - Test execution (pytest with 100% passing)
   - Rust extension compilation (maturin)
   - Wheel generation with metadata
   - SHA256 checksum generation

4. **Build Materials**
   - Source code (git commit)
   - Dependencies (from `pyproject.toml`)
   - Build tools (uv, maturin, Python 3.13)

5. **Cryptographic Signature**
   - Sigstore keyless signing
   - Certificate from Fulcio (public key infrastructure)
   - Transparency log entry in Rekor

### How to Read Provenance JSON

**Example provenance snippet:**

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [
    {
      "name": "fraiseql-0.1.0-py3-none-any.whl",
      "digest": {
        "sha256": "abc123..."
      }
    }
  ],
  "predicateType": "https://slsa.dev/provenance/v1",
  "predicate": {
    "buildDefinition": {
      "buildType": "https://actions.github.io/buildtypes/workflow/v1",
      "externalParameters": {
        "workflow": {
          "ref": "refs/tags/v0.1.0",
          "repository": "https://github.com/fraiseql/fraiseql"
        }
      }
    }
  }
}
```

**Key fields explained:**

- `subject.name`: The artifact being attested (wheel filename)
- `subject.digest.sha256`: Cryptographic hash of the artifact
- `predicateType`: SLSA provenance v1 format
- `buildType`: GitHub Actions workflow build
- `externalParameters.workflow.ref`: Git tag/branch used for build
- `externalParameters.workflow.repository`: Source repository

---

## Verifying Checksums (Additional Security Layer)

Every FraiseQL release includes SHA256 checksums for all artifacts.

### Web-Based Checksum Verification

1. Go to the release page: https://github.com/fraiseql/fraiseql/releases
2. Download the wheel: `fraiseql-0.1.0-py3-none-any.whl`
3. Download the checksum: `fraiseql-0.1.0-py3-none-any.whl.sha256`
4. Verify using online tool: https://emn178.github.io/online-tools/sha256_checksum.html
   - Upload the `.whl` file
   - Compare computed hash with `.sha256` file content
   - Should match exactly ✅

### Command-Line Checksum Verification

```bash
# Download wheel and checksum
gh release download --repo fraiseql/fraiseql --pattern "fraiseql-*.whl*"

# Verify checksum
sha256sum -c fraiseql-*.whl.sha256
```

**Expected output:**

```
fraiseql-0.1.0-py3-none-any.whl: OK
```

**If checksum doesn't match:**

```
fraiseql-0.1.0-py3-none-any.whl: FAILED
sha256sum: WARNING: 1 computed checksum did NOT match
```

❌ **Do NOT use the artifact** - it may be compromised or corrupted.

---

## SBOM Verification (Software Bill of Materials)

FraiseQL provides SBOMs in **CycloneDX** and **SPDX** formats for dependency transparency.

### Why SBOM Matters

An SBOM (Software Bill of Materials) lists all software components, libraries, and dependencies - like an ingredient list for software. This helps:

- ✅ **Identify vulnerabilities** - Check if any dependencies have known security issues
- ✅ **License compliance** - Verify all licenses are acceptable for your organization
- ✅ **Supply chain visibility** - Track transitive dependencies (dependencies of dependencies)

### How to Access FraiseQL's SBOM

**Option 1: GitHub Releases**

1. Go to release page: https://github.com/fraiseql/fraiseql/releases
2. Download `fraiseql-0.1.0-sbom.json` (CycloneDX format)
3. Or download `fraiseql-0.1.0-sbom.spdx.json` (SPDX format)

**Option 2: Generate from Installed Package**

```bash
# Install fraiseql
pip install fraiseql

# Generate SBOM (uses the fraiseql CLI)
fraiseql sbom generate --format cyclonedx --output sbom.json
```

### Analyzing the SBOM

**Web-Based SBOM Viewer:**

1. Go to: https://sbom.cybellum.com/viewer
2. Upload `fraiseql-*-sbom.json`
3. View components, licenses, vulnerabilities

**Command-Line SBOM Analysis:**

```bash
# Install cyclonedx-cli (one-time setup)
npm install -g @cyclonedx/cyclonedx-cli

# Validate SBOM format
cyclonedx-cli validate --input-file fraiseql-0.1.0-sbom.json

# Convert to other formats
cyclonedx-cli convert --input-file fraiseql-0.1.0-sbom.json --output-format spdx-json
```

**What to check in SBOM:**

- ✅ **Total components**: FraiseQL has ~50-70 direct/transitive dependencies
- ✅ **Known vulnerabilities**: Should be 0 critical/high (check with `pip-audit`)
- ✅ **License compliance**: All dependencies use permissive licenses (MIT, Apache-2.0, BSD)
- ✅ **Dependency sources**: All from PyPI (trusted package index)

---

## Compliance Evidence for Procurement

### What to Include in Procurement Documentation

When documenting FraiseQL's supply chain security for procurement:

**1. Verification Summary**

```
Vendor: FraiseQL
Product Version: v0.1.0
Verification Date: 2025-12-08
Verified By: [Your Name], [Your Title]

Supply Chain Security:
✅ SLSA Build Level 3
✅ Sigstore-signed attestations verified
✅ GitHub provenance attestations verified
✅ SHA256 checksums validated
✅ SBOM reviewed (CycloneDX 1.5)
✅ Zero critical vulnerabilities identified

Compliance Alignment:
✅ Executive Order 14028 (SBOM + provenance)
✅ NIST SP 800-161 Rev. 1 (supply chain risk management)
✅ NIST SP 800-218 (secure software development framework)
```

**2. Screenshots/Evidence**

- GitHub attestation page (showing "Verified ✅")
- `gh attestation verify` command output
- SBOM vulnerability scan results
- Checksum verification results

**3. Verification Commands Used**

```bash
# Commands executed for verification
gh release download --repo fraiseql/fraiseql --pattern "*.whl"
gh attestation verify fraiseql-*.whl --owner fraiseql --repo fraiseql
sha256sum -c fraiseql-*.whl.sha256
```

**4. Risk Assessment**

- **Supply Chain Risk**: Low (SLSA L3, automated builds, no human in the loop)
- **Dependency Risk**: Low (50-70 dependencies, all from PyPI, no known vulnerabilities)
- **Build Security**: High (GitHub-hosted runners, auditable workflow, Sigstore signing)

### Demonstrating Compliance to Auditors

**For Executive Order 14028 (Federal Procurement):**

- ✅ Provide SBOM in CycloneDX/SPDX format
- ✅ Show SLSA provenance verification results
- ✅ Document cryptographic signing (Sigstore)

**For NIST SP 800-161 (Supply Chain Risk Management):**

- ✅ SBOM provides complete dependency visibility
- ✅ Provenance shows controlled build environment
- ✅ Continuous monitoring via GitHub Security Advisories

**For NIST SP 800-218 (Secure Software Development Framework):**

- ✅ Protect the Software (PS): SLSA provenance, signing, SBOM
- ✅ Produce Well-Secured Software (PW): Automated testing, linting, security scans
- ✅ Respond to Vulnerabilities (RV): Dependabot, security advisories, patch releases

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: GitHub CLI Not Installed

**Error:**

```
bash: gh: command not found
```

**Solution:**
Install GitHub CLI:

```bash
# macOS
brew install gh

# Windows
winget install GitHub.cli

# Linux
sudo apt install gh
```

#### Issue 2: GitHub CLI Not Authenticated

**Error:**

```
error: HTTP 401: Bad credentials (https://api.github.com/repos/fraiseql/fraiseql/attestations)
```

**Solution:**
Authenticate GitHub CLI:

```bash
gh auth login
# Follow prompts to authenticate
```

#### Issue 3: Attestation Not Found

**Error:**

```
error: no attestations found for fraiseql-0.1.0-py3-none-any.whl
```

**Possible causes:**

1. **Wrong owner/repo**: Make sure you're using `--owner fraiseql --repo fraiseql`
2. **Pre-attestation release**: Releases before v0.1.0 may not have attestations
3. **File name mismatch**: Ensure filename matches exactly (check with `ls`)

**Solution:**

```bash
# List available releases
gh release list --repo fraiseql/fraiseql

# Download specific version with attestations
gh release download v0.1.0 --repo fraiseql/fraiseql --pattern "*.whl"
```

#### Issue 4: Checksum Mismatch

**Error:**

```
fraiseql-0.1.0-py3-none-any.whl: FAILED
```

**Possible causes:**

1. **Partial download**: Network interruption during download
2. **Corrupted file**: Disk error or transmission error
3. **Tampering**: File modified after download (rare)

**Solution:**

```bash
# Re-download the file
rm fraiseql-*.whl*
gh release download --repo fraiseql/fraiseql --pattern "fraiseql-*.whl*"

# Verify again
sha256sum -c fraiseql-*.whl.sha256
```

If checksum still fails after re-download:

1. **Report to FraiseQL security team**: security@fraiseql.com
2. **Do NOT use the artifact** until resolved

#### Issue 5: SBOM Not Available

**Error:**

```
error: release asset not found: fraiseql-0.1.0-sbom.json
```

**Solution:**
SBOM may be generated separately from release artifacts:

```bash
# Generate SBOM from installed package
pip install fraiseql
fraiseql sbom generate --format cyclonedx --output sbom.json
```

Or check the SBOM workflow artifacts:

```bash
gh run list --workflow=sbom.yml --repo fraiseql/fraiseql
```

---

## Frequently Asked Questions

### General

**Q: Do I need to verify every FraiseQL release?**

A: **Best practice**: Verify the first time you evaluate FraiseQL, then verify major version updates (e.g., v1.0 → v2.0). For minor/patch updates, verification is optional but recommended for regulated industries.

**Q: How long does verification take?**

A:

- Web-based verification: 5 minutes
- GitHub CLI verification: 10 minutes (first time, including setup)
- Subsequent verifications: 2-3 minutes

**Q: Can I automate verification in CI/CD?**

A: Yes. Use GitHub CLI in your deployment pipeline:

```bash
# In CI/CD pipeline
gh attestation verify fraiseql-*.whl --owner fraiseql --repo fraiseql || exit 1
```

### Technical

**Q: What is Sigstore and why does FraiseQL use it?**

A: Sigstore is an open-source project (backed by Linux Foundation) that provides **keyless signing** for software artifacts. Benefits:

- No private keys to manage or leak
- Uses OpenID Connect (OIDC) for identity verification
- Public transparency log (Rekor) prevents backdating
- Certificate-based trust (Fulcio)

FraiseQL uses Sigstore because it's:

- ✅ **Free and open-source**
- ✅ **Widely adopted** (npm, Maven Central, Homebrew)
- ✅ **Compliant** with Executive Order 14028

**Q: What's the difference between SLSA provenance and SBOM?**

A:

- **SLSA Provenance**: Proves *how* the software was built (build process, source commit, builder identity)
- **SBOM**: Lists *what's in* the software (dependencies, components, licenses)

Both are complementary - you need both for complete supply chain security.

**Q: Can provenance attestations be forged?**

A: **No**, if verified correctly. Attestations are:

1. Signed with Sigstore (keyless signing via OIDC)
2. Recorded in public transparency log (Rekor)
3. Bound to GitHub Actions identity (can't be created outside official workflow)
4. Timestamped and immutable

Attempting to forge would require:

- Compromising GitHub's OIDC provider
- Compromising Sigstore's Fulcio certificate authority
- Tampering with Rekor transparency log (publicly auditable)

All of these are infeasible for practical attackers.

### Compliance

**Q: Is SLSA verification required for FedRAMP?**

A: FedRAMP doesn't specifically mandate SLSA, but requires **software supply chain risk management**. SLSA provenance satisfies:

- **SC-28**: Protection of Information at Rest (integrity verification)
- **SA-10**: Developer Configuration Management (build provenance)
- **SA-15**: Development Process and Criteria (secure development practices)

**Q: How long are attestations retained?**

A: GitHub attestations are retained **indefinitely** (part of public transparency log). You can verify old releases years later.

**Q: Can I verify FraiseQL installed via pip?**

A: Currently, pip doesn't preserve attestations after installation. Options:

1. Verify wheel *before* installation (recommended)
2. Use `pip download` to get wheel, verify, then install
3. Wait for pip 25.0+ which will support `--verify-attestations`

---

## Additional Resources

### Official Documentation

- **SLSA Framework**: https://slsa.dev/
- **Sigstore Documentation**: https://docs.sigstore.dev/
- **PEP 740 (PyPI Attestations)**: https://peps.python.org/pep-0740/
- **GitHub Attestations**: https://docs.github.com/en/actions/security-guides/using-artifact-attestations

### FraiseQL Resources

- **GitHub Repository**: https://github.com/fraiseql/fraiseql
- **Release Notes**: https://github.com/fraiseql/fraiseql/releases
- **Security Policy**: https://github.com/fraiseql/fraiseql/security/policy
- **Supply Chain Security Workflow**: `.github/workflows/publish.yml`

### Compliance Frameworks

- **Executive Order 14028**: [White House Cybersecurity EO](https://www.whitehouse.gov/briefing-room/presidential-actions/2021/05/12/executive-order-on-improving-the-nations-cybersecurity/)
- **NIST SP 800-161 Rev. 1**: [Cybersecurity Supply Chain Risk Management](https://csrc.nist.gov/publications/detail/sp/800-161/rev-1/final)
- **NIST SP 800-218**: [Secure Software Development Framework](https://csrc.nist.gov/publications/detail/sp/800-218/final)

### Tools

- **GitHub CLI**: https://cli.github.com/
- **Cosign** (Sigstore CLI): https://docs.sigstore.dev/cosign/installation/
- **CycloneDX CLI**: https://github.com/CycloneDX/cyclonedx-cli
- **SBOM Viewer** (web-based): https://sbom.cybellum.com/viewer

---

## Support

### Need Help?

**For Procurement Officers:**

- Questions about verification: procurement@fraiseql.com
- Compliance documentation requests: compliance@fraiseql.com

**For Security Teams:**

- Technical verification issues: security@fraiseql.com
- Vulnerability reports: https://github.com/fraiseql/fraiseql/security/advisories/new

**For General Support:**

- GitHub Discussions: https://github.com/fraiseql/fraiseql/discussions
- Documentation: https://fraiseql.com/docs

---

**Document Version:** 1.0
**Last Updated:** 2025-12-08
**Maintained By:** FraiseQL Security Team
**Next Review:** Q2 2025

---

## Related Guides

- **[Security & Compliance Hub](./README/)** - Overview of all security features
- **[Compliance Matrix](./compliance-matrix/)** - Regulatory controls mapping *(coming in WP-012)*
- **[Security Profiles](./security-profiles/)** - Configuration for regulated industries *(coming in WP-013)*
- **[Global Regulations Guide](../compliance/global-regulations/)** - Detailed regulatory requirements
