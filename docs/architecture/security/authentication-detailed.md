---

title: FraiseQL Authentication Details
description: 1. [Executive Summary](#executive-summary)
keywords: ["design", "scalability", "performance", "patterns", "security"]
tags: ["documentation", "reference"]
---

# FraiseQL Authentication Details

**Status**: ✅ Implemented
**Last Updated**: February 5, 2026

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Authentication Architecture](#1-authentication-architecture)
3. [OAuth2 Implementation](#2-oauth2-implementation)
4. [SAML 2.0 Integration](#3-saml-20-integration)
5. [JWT Token Specification](#4-jwt-token-specification)
6. [Custom Authentication Provider Pattern](#5-custom-authentication-provider-pattern)
7. [Session Management](#6-session-management)
8. [Token Revocation](#7-token-revocation)
9. [Multi-Tenant Authentication](#8-multi-tenant-authentication)
10. [Security Best Practices](#9-security-best-practices)
11. [Audit & Compliance](#10-audit--compliance)
12. [Performance Optimization](#11-performance-optimization)
13. [Error Handling](#12-error-handling)

---

## Executive Summary

FraiseQL provides enterprise-grade authentication with support for multiple authentication schemes, token lifecycle management, and seamless integration with database-enforced authorization. This specification covers:

- **OAuth2 Implementation**: Authorization Code, Client Credentials, Refresh Token flows
- **SAML Integration**: Assertion parsing, attribute mapping, multi-tenant federation
- **JWT Validation**: Token structure, signature verification, claims validation
- **Custom Providers**: Extensible authentication plugin architecture
- **Token Management**: Generation, refresh, revocation, and expiration
- **Session Handling**: Stateful and stateless authentication models
- **Multi-Tenant Support**: Tenant isolation and context propagation
- **Security Best Practices**: Token storage, CSRF protection, secure headers

---

## 1. Authentication Architecture

### 1.1 Core Principles

FraiseQL authentication follows these principles:

1. **Authentication ≠ Authorization**
   - Authentication: Who are you?
   - Authorization: What can you do?
   - Separate concerns with clear boundaries

2. **Tokens Are Credentials**
   - Treat tokens like passwords
   - Never log them
   - Rotate regularly
   - Revoke when compromised

3. **Database Is Source of Truth**
   - User identities stored in database
   - Sessions linked to database records
   - Audit trails immutable and append-only

4. **Stateless Preferred, Stateful Supported**
   - JWT tokens for stateless (scalable, distributed)
   - Session cookies for stateful (traditional, browser-friendly)
   - Can mix strategies per client type

5. **Multi-Tenant by Default**
   - Every user belongs to one or more tenants
   - Context propagated through all layers
   - Tenant isolation enforced at query level

### 1.2 Authentication Flow Overview

```text
Client Request
    ↓
┌─────────────────────────────────────────┐
│ 1. Extract Credentials                  │
│    - Authorization header (Bearer token)│
│    - Cookie (session)                   │
│    - Custom (API key, etc.)             │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 2. Validate Credentials                 │
│    - Signature verification (JWT)       │
│    - Session lookup (cookies)           │
│    - Custom validation logic            │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 3. Extract Principal                    │
│    - User ID                            │
│    - Tenant ID(s)                       │
│    - Roles/Permissions                  │
│    - Custom attributes                  │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 4. Attach to Request Context            │
│    - Available to the Authorizer        │
│    - Available to queries/mutations     │
│    - Available to field authorization   │
└─────────────────────────────────────────┘
    ↓
Authorize Request
    ↓
Execute Query/Mutation
```

### 1.3 Supported Authentication Schemes

| Scheme | Use Case | Stateless | Token Type | Setup Complexity |
|--------|----------|-----------|------------|------------------|
| **OAuth2 Authorization Code** | Web applications | Yes | JWT | Medium |
| **OAuth2 Client Credentials** | Service-to-service | Yes | JWT | Low |
| **OAuth2 Refresh Token** | Token renewal | Yes | JWT (with refresh) | Low |
| **SAML 2.0** | Enterprise SSO | Stateful | Assertion | High |
| **JWT Direct** | Mobile/SPA backends | Yes | JWT | Low |
| **Session Cookies** | Traditional web apps | Stateful | Session ID | Low |
| **API Keys** | Service integration | Yes | API Key | Very Low |
| **Custom Provider** | Special requirements | Configurable | Varies | Varies |

---

## 2. OAuth2 Implementation

### 2.1 OAuth2 Authorization Code Flow

Used for web applications where users log in through a browser.

#### Flow Sequence

```text
User's Browser               FraiseQL App              OAuth2 Provider
      │                           │                           │
      │ (1) Click "Login"         │                           │
      ├──────────────────────────►│                           │
      │                           │                           │
      │                           │ (2) Redirect to provider  │
      │◄────────────────────────────────────────────────────────┤
      │                           │       with client_id,      │
      │                           │       redirect_uri,        │
      │                           │       state                │
      │                           │                           │
      │ (3) User grants access    │                           │
      │ (in provider's UI)        │                           │
      │                           │                           │
      │ (4) Redirect to app       │                           │
      ├──────────────────────────────────────────────────────────┤
      │       with auth_code,     │                           │
      │       state               │                           │
      │                           │                           │
      │                           │ (5) Exchange code for token│
      │                           ├──────────────────────────►│
      │                           │ (POST to token endpoint)  │
      │                           │                           │
      │                           │ (6) Return token          │
      │                           │◄──────────────────────────┤
      │                           │                           │
      │ (7) Logged in             │                           │
      │◄──────────────────────────┤                           │
      │   (set session/token)     │                           │
```

#### Implementation Details

The example below is a self-contained reference implementation. In a FraiseQL v1
app you typically front OAuth2/OIDC with **Auth0** (`Auth0Provider(Auth0Config(...))`,
`auth_provider="auth0"`) or implement a custom `AuthProvider` subclass; FraiseQL does
not ship its own OAuth2 client classes.

```python
import httpx

class OAuth2AuthorizationCodeFlow:
    """OAuth2 Authorization Code flow implementation"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        authorize_url: str,
        token_url: str,
        redirect_uri: str,
        scope: list[str] = ["openid", "profile", "email"]
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.redirect_uri = redirect_uri
        self.scope = scope

    def get_authorization_url(self, state: str, nonce: str | None = None) -> str:
        """Generate authorization URL for user redirect

        Args:
            state: Random string to prevent CSRF (must be validated on callback)
            nonce: Optional OpenID Connect nonce for ID token validation

        Returns:
            URL to redirect user to for authorization
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scope),
            "state": state,
        }
        if nonce:
            params["nonce"] = nonce

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.authorize_url}?{query_string}"

    async def exchange_code_for_token(
        self,
        code: str,
        state: str,
        stored_state: str
    ) -> TokenResponse:
        """Exchange authorization code for tokens

        Args:
            code: Authorization code from OAuth2 provider
            state: State returned by provider
            stored_state: Original state sent to provider (for CSRF validation)

        Returns:
            TokenResponse with access_token, refresh_token, expires_in

        Raises:
            CSRFError: If state doesn't match
            TokenExchangeError: If code exchange fails
        """
        # Validate CSRF protection
        if state != stored_state:
            raise CSRFError("State mismatch - possible CSRF attack")

        # Exchange code for token
        token_request = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, json=token_request)
            if response.status_code != 200:
                raise TokenExchangeError(f"Token exchange failed: {response.text}")

            data = response.json()
            return TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                expires_in=data.get("expires_in", 3600),
                token_type=data.get("token_type", "Bearer"),
                id_token=data.get("id_token"),  # OpenID Connect
            )
```

#### Security Considerations

1. **CSRF Protection**
   - Always validate `state` parameter
   - Store state server-side before redirect
   - State must be random and unique per session

2. **PKCE (Proof Key for Code Exchange)**
   - Required for public clients (SPAs, mobile apps)
   - Optional but recommended for confidential clients
   - Prevents authorization code interception

   ```python
   import secrets
   import hashlib
   import base64

   def generate_pkce_pair() -> tuple[str, str]:
       """Generate PKCE code_verifier and code_challenge

       Returns:
           (code_verifier, code_challenge) tuple
       """
       code_verifier = base64.urlsafe_b64encode(
           secrets.token_bytes(32)
       ).decode().rstrip("=")

       challenge = base64.urlsafe_b64encode(
           hashlib.sha256(code_verifier.encode()).digest()
       ).decode().rstrip("=")

       return code_verifier, challenge
   ```

3. **Token Storage**
   - Never store tokens in localStorage (XSS vulnerability)
   - Store in memory or secure httpOnly cookie
   - For SPAs: Backend-for-Frontend (BFF) pattern recommended

4. **Scope Limitation**
   - Request minimal necessary scopes
   - Document why each scope is needed
   - Validate returned scopes match requested

### 2.2 OAuth2 Client Credentials Flow

Used for service-to-service authentication without user involvement.

```python
class OAuth2ClientCredentialsFlow:
    """OAuth2 Client Credentials flow for machine-to-machine auth"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        scope: list[str] | None = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.scope = scope or []

    async def get_token(self) -> TokenResponse:
        """Request access token using client credentials

        Returns:
            TokenResponse with access_token and expires_in

        Raises:
            TokenAcquisitionError: If token request fails
        """
        token_request = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            token_request["scope"] = " ".join(self.scope)

        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, json=token_request)
            if response.status_code != 200:
                raise TokenAcquisitionError(f"Token request failed: {response.text}")

            data = response.json()
            return TokenResponse(
                access_token=data["access_token"],
                expires_in=data.get("expires_in", 3600),
                token_type=data.get("token_type", "Bearer"),
            )
```

**Use Cases:**

- Service-to-service API calls
- Microservices authentication
- Scheduled batch jobs
- Integration with external systems

**Security Considerations:**

- Store client_secret securely (environment variables, secret management)
- Rotate client_secret regularly
- Use in backend only (never expose to frontend)
- Implement rate limiting on token endpoint

### 2.3 OAuth2 Refresh Token Flow

Refresh tokens extend session lifetime without requiring re-authentication.

```python
class OAuth2RefreshTokenFlow:
    """OAuth2 Refresh Token flow for token renewal"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Use refresh token to get new access token

        Args:
            refresh_token: Long-lived refresh token from previous authentication

        Returns:
            TokenResponse with new access_token and potentially new refresh_token

        Raises:
            TokenRefreshError: If refresh fails (token expired/revoked)
        """
        token_request = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, json=token_request)
            if response.status_code != 200:
                if response.status_code == 400:
                    # Refresh token invalid or expired - require re-authentication
                    raise TokenRefreshError("Refresh token invalid or expired")
                raise TokenRefreshError(f"Token refresh failed: {response.text}")

            data = response.json()
            return TokenResponse(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", refresh_token),
                expires_in=data.get("expires_in", 3600),
                token_type=data.get("token_type", "Bearer"),
            )
```

**Token Rotation Strategy:**

```text
Initial Login:
  access_token (short-lived, 15min) → Set cookie httpOnly, Secure, SameSite=Strict
  refresh_token (long-lived, 7 days) → Set cookie httpOnly, Secure, SameSite=Strict

After 14 minutes (before expiry):
  Client calls /refresh endpoint
  Server: exchange refresh_token for new access_token + new refresh_token
  Rotate refresh_token (invalidate old one) - prevents replay attacks
  Return new tokens in httpOnly cookies

If refresh_token expires:
  Require full re-authentication (redirect to login)
  Display grace period message (optional)
```

---

## 3. SAML 2.0 Integration

### 3.1 SAML Architecture

SAML (Security Assertion Markup Language) is XML-based protocol for enterprise SSO.

```text
User's Browser          FraiseQL App           Identity Provider (IdP)
      │                      │                       │
      │ (1) Click "Login"    │                       │
      ├─────────────────────►│                       │
      │                      │                       │
      │                      │ (2) Generate SAML     │
      │                      │     AuthnRequest      │
      │                      │                       │
      │ (3) Redirect with    │                       │
      │     SAML request     │                       │
      ├──────────────────────────────────────────────┤
      │                      │                       │
      │ (4) User login/      │                       │
      │     grant consent    │                       │
      │ (in IdP UI)          │                       │
      │                      │                       │
      │ (5) Redirect with    │                       │
      │     SAML assertion   │                       │
      ├──────────────────────────────────────────────┤
      │                      │                       │
      │                      │ (6) Verify assertion  │
      │                      │     - Signature       │
      │                      │     - Timestamp       │
      │                      │     - Issuer          │
      │                      │                       │
      │ (7) Create session   │                       │
      │◄─────────────────────┤                       │
      │   (set auth cookie)  │                       │
```

### 3.2 SAML Assertion Validation

```python
from lxml import etree
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.backends import default_backend

class SAMLAssertionValidator:
    """Validate SAML 2.0 assertions from IdP"""

    def __init__(
        self,
        idp_cert_path: str,
        entity_id: str,
        acs_url: str,
        sso_url: str
    ):
        """Initialize SAML validator

        Args:
            idp_cert_path: Path to IdP's X.509 certificate (PEM format)
            entity_id: Service Provider entity ID (e.g., "https://app.example.com/saml")
            acs_url: Assertion Consumer Service URL where IdP redirects after auth
            sso_url: IdP's Single Sign-On URL
        """
        self.idp_cert_path = idp_cert_path
        self.entity_id = entity_id
        self.acs_url = acs_url
        self.sso_url = sso_url

        # Load IdP certificate for signature verification
        with open(idp_cert_path, "rb") as f:
            cert_data = f.read()
        self.idp_cert = load_pem_x509_certificate(
            cert_data,
            default_backend()
        )

    def validate_assertion(
        self,
        saml_response_b64: str,
        relay_state: str | None = None
    ) -> dict[str, Any]:
        """Validate SAML assertion from IdP

        Args:
            saml_response_b64: Base64-encoded SAML response from IdP
            relay_state: Optional state parameter for CSRF protection

        Returns:
            Dict with user_id, email, name, attributes from assertion

        Raises:
            SAMLValidationError: If assertion invalid or signature verification fails
        """
        # Decode SAML response
        try:
            saml_response_xml = base64.b64decode(saml_response_b64).decode("utf-8")
        except Exception as e:
            raise SAMLValidationError(f"Failed to decode SAML response: {e}")

        root = etree.fromstring(saml_response_xml.encode("utf-8"))

        # 1. Verify signature
        self._verify_signature(root)

        # 2. Extract assertion element
        assertion = self._extract_assertion(root)

        # 3. Validate assertion structure and attributes
        self._validate_assertion_structure(assertion)

        # 4. Extract user identity
        user_data = self._extract_user_data(assertion)

        return user_data

    def _verify_signature(self, root: etree._Element) -> None:
        """Verify SAML response signature using IdP's certificate

        Args:
            root: Root XML element of SAML response

        Raises:
            SAMLValidationError: If signature verification fails
        """
        # Find Signature element
        signature_elem = root.find(
            ".//{http://www.w3.org/2000/09/xmldsig#}Signature"
        )
        if signature_elem is None:
            raise SAMLValidationError("No signature found in SAML response")

        # Extract signed data and signature value
        try:
            signature_value = signature_elem.find(
                ".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue"
            ).text
            signed_info = signature_elem.find(
                ".//{http://www.w3.org/2000/09/xmldsig#}SignedInfo"
            )

            # This is simplified - full implementation uses xmlsec1 or similar
            # In production, use proper SAML library (onelogin, python3-saml)
            if not self._verify_rsa_signature(
                etree.tostring(signed_info),
                base64.b64decode(signature_value),
                self.idp_cert.public_key()
            ):
                raise SAMLValidationError("Signature verification failed")
        except Exception as e:
            raise SAMLValidationError(f"Signature verification failed: {e}")

    def _extract_assertion(self, root: etree._Element) -> etree._Element:
        """Extract Assertion element from SAML response

        Handles both direct assertions and encrypted assertions.
        """
        # Direct assertion (unencrypted)
        assertion = root.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion"
        )
        if assertion is not None:
            return assertion

        # Encrypted assertion
        encrypted = root.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}EncryptedAssertion"
        )
        if encrypted is not None:
            # Would need SP's private key to decrypt
            raise SAMLValidationError("Encrypted assertions not yet supported")

        raise SAMLValidationError("No assertion found in SAML response")

    def _validate_assertion_structure(self, assertion: etree._Element) -> None:
        """Validate assertion structure and timestamps

        Checks:
        - NotBefore and NotOnOrAfter timestamps
        - Issuer matches IdP
        - Audience matches this service provider
        """
        import datetime

        # Check timestamp validity
        conditions = assertion.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}Conditions"
        )
        if conditions is not None:
            not_before = conditions.get("NotBefore")
            not_on_or_after = conditions.get("NotOnOrAfter")

            now = datetime.datetime.utcnow()

            if not_before:
                nb_time = datetime.datetime.fromisoformat(
                    not_before.replace("Z", "+00:00")
                )
                if now < nb_time:
                    raise SAMLValidationError("Assertion not yet valid (NotBefore)")

            if not_on_or_after:
                noa_time = datetime.datetime.fromisoformat(
                    not_on_or_after.replace("Z", "+00:00")
                )
                if now >= noa_time:
                    raise SAMLValidationError("Assertion expired (NotOnOrAfter)")

        # Check issuer
        issuer = assertion.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}Issuer"
        )
        if issuer is None:
            raise SAMLValidationError("No issuer found in assertion")

        # Issuer should match known IdP URL
        # (configure IdP URL during setup)

        # Check audience
        audience_restriction = assertion.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}AudienceRestriction"
        )
        if audience_restriction is not None:
            audience = audience_restriction.find(
                ".//{urn:oasis:names:tc:SAML:2.0:assertion}Audience"
            )
            if audience is None or audience.text != self.entity_id:
                raise SAMLValidationError(
                    f"Audience mismatch: expected {self.entity_id}"
                )

    def _extract_user_data(self, assertion: etree._Element) -> dict[str, Any]:
        """Extract user identity and attributes from assertion

        Standard SAML attributes:
        - urn:oid:0.9.2342.19200300.100.1.3 (email)
        - urn:oid:2.5.4.3 (commonName)
        - urn:oid:2.5.4.4 (surname)
        - urn:oid:2.5.4.42 (givenName)
        """
        subject = assertion.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}Subject"
        )
        if subject is None:
            raise SAMLValidationError("No subject found in assertion")

        # Extract NameID (principal identifier)
        name_id = subject.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID"
        )
        if name_id is None:
            raise SAMLValidationError("No NameID found in subject")

        user_id = name_id.text

        # Extract attributes
        attributes = {}
        attr_statement = assertion.find(
            ".//{urn:oasis:names:tc:SAML:2.0:assertion}AttributeStatement"
        )

        if attr_statement is not None:
            for attr in attr_statement.findall(
                ".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute"
            ):
                attr_name = attr.get("Name")
                attr_value = attr.find(
                    ".//{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue"
                )
                if attr_value is not None and attr_value.text:
                    attributes[attr_name] = attr_value.text

        return {
            "user_id": user_id,
            "email": attributes.get("urn:oid:0.9.2342.19200300.100.1.3", user_id),
            "name": attributes.get("urn:oid:2.5.4.3", user_id),
            "attributes": attributes,
        }
```

### 3.3 SAML Attribute Mapping

Map SAML attributes to FraiseQL user model:

```python
class SAMLAttributeMapper:
    """Map SAML attributes to FraiseQL user properties"""

    def __init__(self, mapping: dict[str, str]):
        """Initialize mapper

        Args:
            mapping: Dict mapping FraiseQL fields to SAML attribute names

        Example:
            {
                "email": "urn:oid:0.9.2342.19200300.100.1.3",
                "display_name": "urn:oid:2.5.4.3",
                "department": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/department",
                "roles": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/role",
            }
        """
        self.mapping = mapping

    def map_attributes(
        self,
        saml_attributes: dict[str, str],
        user_id: UUID  # UUID v4 for GraphQL ID
    ) -> dict[str, Any]:
        """Map SAML attributes to user object

        Args:
            saml_attributes: Raw SAML attribute dict from assertion
            user_id: SAML NameID (principal identifier)

        Returns:
            Dict of FraiseQL user properties
        """
        mapped = {"id": user_id}

        for fraiseql_field, saml_attr_name in self.mapping.items():
            if saml_attr_name in saml_attributes:
                value = saml_attributes[saml_attr_name]
                # Special handling for roles (comma-separated or array)
                if fraiseql_field == "roles" and isinstance(value, str):
                    mapped[fraiseql_field] = [r.strip() for r in value.split(",")]
                else:
                    mapped[fraiseql_field] = value

        return mapped
```

---

## 4. JWT Token Specification

### 4.1 JWT Structure

JWT consists of three base64url-encoded parts separated by dots:

```text
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.
eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.
SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
```

**Header** (JWT metadata):

```json
{
  "alg": "RS256",     // Signing algorithm
  "typ": "JWT",       // Token type
  "kid": "key-id-123" // Key ID (for key rotation)
}
```

**Payload** (Claims):

```json
{
  "sub": "user:12345",           // Subject (user ID)
  "aud": "api.example.com",       // Audience (intended recipient)
  "iss": "https://auth.example.com",  // Issuer
  "iat": 1516239022,             // Issued at (timestamp)
  "exp": 1516242622,             // Expiration (timestamp)
  "nbf": 1516239022,             // Not before (timestamp)
  "tenant_id": "tenant:789",     // Custom claim: tenant
  "roles": ["admin", "user"],    // Custom claim: roles
  "permissions": ["read:posts", "write:posts"]  // Custom claim: permissions
}
```

**Signature**:

```text
HMAC-SHA256 or RSA-SHA256 of (header + payload) using secret key
```

### 4.2 JWT Generation

```python
from datetime import datetime, timedelta
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class JWTTokenGenerator:
    """Generate signed JWT tokens"""

    def __init__(
        self,
        private_key_path: str,
        algorithm: str = "RS256",
        issuer: str = "https://auth.example.com",
        audience: str = "api.example.com"
    ):
        """Initialize token generator

        Args:
            private_key_path: Path to private key (PEM format)
            algorithm: Signing algorithm (RS256, HS256, etc.)
            issuer: Token issuer claim
            audience: Token audience claim
        """
        with open(private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience

    def generate_token(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        expires_in_seconds: int = 3600,
        custom_claims: dict[str, Any] | None = None
    ) -> str:
        """Generate access token

        Args:
            user_id: User identifier
            tenant_id: Tenant identifier
            roles: User roles
            permissions: User permissions
            expires_in_seconds: Token lifetime in seconds
            custom_claims: Additional custom claims

        Returns:
            Signed JWT token
        """
        now = datetime.utcnow()
        expires = now + timedelta(seconds=expires_in_seconds)

        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "nbf": int(now.timestamp()),
        }

        if roles:
            payload["roles"] = roles

        if permissions:
            payload["permissions"] = permissions

        if custom_claims:
            payload.update(custom_claims)

        # Sign token
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm=self.algorithm
        )

        return token

    def generate_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
        expires_in_seconds: int = 604800  # 7 days
    ) -> str:
        """Generate long-lived refresh token

        Refresh tokens:
        - Have longer expiration (days vs minutes)
        - Are stored in database (can be revoked)
        - Are rotated on use (old token invalidated)
        - Are tracked for audit/security analysis
        """
        now = datetime.utcnow()
        expires = now + timedelta(seconds=expires_in_seconds)

        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "type": "refresh",  # Token type
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "nbf": int(now.timestamp()),
        }

        token = jwt.encode(
            payload,
            self.private_key,
            algorithm=self.algorithm
        )

        return token
```

### 4.3 JWT Validation

```python
class JWTTokenValidator:
    """Validate and extract claims from JWT tokens"""

    def __init__(
        self,
        public_key_path: str,
        algorithm: str = "RS256",
        issuer: str = "https://auth.example.com",
        audience: str = "api.example.com"
    ):
        """Initialize token validator

        Args:
            public_key_path: Path to public key (PEM format)
            algorithm: Expected signing algorithm
            issuer: Expected issuer claim
            audience: Expected audience claim
        """
        with open(public_key_path, "rb") as f:
            self.public_key = serialization.load_pem_public_key(
                f.read(),
                backend=default_backend()
            )
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience

    def validate_token(
        self,
        token: str,
        token_type: str = "access"
    ) -> dict[str, Any]:
        """Validate token signature and claims

        Validation steps:
        1. Verify signature using public key
        2. Check expiration (exp claim)
        3. Check not-before (nbf claim)
        4. Verify issuer
        5. Verify audience
        6. Verify token type (if refresh token)

        Args:
            token: JWT token string
            token_type: Expected token type ("access" or "refresh")

        Returns:
            Decoded token claims

        Raises:
            TokenExpiredError: If token has expired
            InvalidSignatureError: If signature verification fails
            InvalidTokenError: If token format or claims invalid
        """
        try:
            # Decode and verify signature
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                }
            )

            # Verify token type for refresh tokens
            if token_type == "refresh":
                if payload.get("type") != "refresh":
                    raise InvalidTokenError("Expected refresh token, got access token")

            return payload

        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Token has expired") from e
        except jwt.InvalidSignatureError as e:
            raise InvalidSignatureError("Signature verification failed") from e
        except jwt.DecodeError as e:
            raise InvalidTokenError("Failed to decode token") from e
        except jwt.InvalidClaimsError as e:
            raise InvalidTokenError(f"Invalid claims: {e}") from e

    def extract_tenant_id(self, token: str) -> str | None:
        """Extract tenant_id claim without full validation

        Used during request processing to route to tenant database.
        Still validates signature but skips expiration check.
        """
        try:
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                options={"verify_exp": False}  # Skip expiration for routing
            )
            return payload.get("tenant_id")
        except (jwt.DecodeError, jwt.InvalidSignatureError):
            return None
```

---

## 5. Custom Authentication Provider Pattern

FraiseQL v1 supports pluggable authentication via the `AuthProvider` ABC in
`fraiseql.auth`. The built-in providers are `Auth0Provider`,
`Auth0ProviderWithRevocation`, `NativeAuthProvider`, and `RustCustomJWTProvider`; you can
add your own by subclassing `AuthProvider` and implementing
`async validate_token(token) -> dict[str, Any]` and
`async get_user_from_token(token) -> UserContext`, then passing the instance to
`create_fraiseql_app(auth=...)`.

The class below is an **illustrative** credential-check shape (for example, an LDAP bind in
your login flow). It is *not* the FraiseQL base class — see the end of this section for how
to wire the equivalent through the real `AuthProvider` ABC:

```python
from abc import ABC, abstractmethod
from typing import Any

class AuthenticationProvider(ABC):
    """Illustrative base for a custom credential check (not a FraiseQL class)."""

    @abstractmethod
    async def authenticate(
        self,
        credentials: dict[str, Any]
    ) -> AuthenticationResult:
        """Authenticate user and return principal

        Args:
            credentials: Raw credentials from client (varies by provider)

        Returns:
            AuthenticationResult with user_id, tenant_id, roles, etc.

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def validate(
        self,
        token: str
    ) -> AuthenticationResult:
        """Validate existing token/session

        Args:
            token: Token or session ID to validate

        Returns:
            AuthenticationResult if valid

        Raises:
            AuthenticationError: If token invalid or expired
        """
        pass

    @abstractmethod
    async def revoke(
        self,
        token: str
    ) -> None:
        """Revoke token/session (logout)

        Args:
            token: Token or session ID to revoke
        """
        pass


class LDAPAuthenticationProvider(AuthenticationProvider):
    """Custom provider: LDAP directory authentication"""

    def __init__(
        self,
        ldap_server: str,
        base_dn: str,
        user_search_attr: str = "uid"
    ):
        self.ldap_server = ldap_server
        self.base_dn = base_dn
        self.user_search_attr = user_search_attr

    async def authenticate(
        self,
        credentials: dict[str, Any]
    ) -> AuthenticationResult:
        """Authenticate via LDAP

        Args:
            credentials: {"username": "...", "password": "..."}
        """
        username = credentials.get("username")
        password = credentials.get("password")

        if not username or not password:
            raise AuthenticationError("Username and password required")

        # Connect to LDAP server
        ldap_conn = ldap.initialize(self.ldap_server)

        # Search for user
        search_filter = f"({self.user_search_attr}={username})"
        result = ldap_conn.search_s(
            self.base_dn,
            ldap.SCOPE_SUBTREE,
            search_filter
        )

        if not result:
            raise AuthenticationError("User not found")

        user_dn = result[0][0]
        user_attrs = result[0][1]

        # Attempt bind with user's password
        try:
            ldap_conn.simple_bind_s(user_dn, password)
        except ldap.INVALID_CREDENTIALS:
            raise AuthenticationError("Invalid password")

        # Extract tenant from LDAP attributes
        tenant_id = user_attrs.get("ou", [b"default"])[0].decode()

        return AuthenticationResult(
            user_id=username,
            tenant_id=tenant_id,
            roles=self._extract_roles(user_attrs),
            metadata={"ldap_dn": user_dn}
        )

    async def validate(self, token: str) -> AuthenticationResult:
        # For LDAP, tokens are session IDs stored in database
        session = await self._get_session(token)
        if not session or session.expired():
            raise AuthenticationError("Session invalid or expired")
        return AuthenticationResult(**session.data)

    async def revoke(self, token: str) -> None:
        await self._delete_session(token)

    def _extract_roles(self, ldap_attrs: dict) -> list[str]:
        """Extract roles from LDAP attributes"""
        # Implementation specific to your LDAP schema
        pass
```

> **FraiseQL v1 note.** The class above is illustrative — it shows the *shape* of a
> custom credential check. v1 does **not** provide an `AuthenticationProvider` base with
> `authenticate`/`validate`/`revoke`, nor a `register_authentication_provider(...)`
> registry. The real extension point is the `AuthProvider` ABC in `fraiseql.auth`
> (abstract `async validate_token(token) -> dict[str, Any]` and
> `async get_user_from_token(token) -> UserContext`), selected via
> `create_fraiseql_app(auth=...)`.

**There is no FraiseQL LDAP provider.** To authenticate against LDAP/Active Directory,
use one of two honest paths:

1. **Front it with Auth0** (or another OIDC broker that fronts your directory). FraiseQL
   then validates the resulting JWTs:

   ```python
   from fraiseql.auth import Auth0Provider, Auth0Config
   from fraiseql.fastapi import create_fraiseql_app

   auth = Auth0Provider(Auth0Config(
       domain="your-tenant.auth0.com",
       api_identifier="https://api.example.com",
   ))

   app = create_fraiseql_app(
       database_url="postgresql://localhost/mydb",
       types=[User],
       queries=[...],
       auth=auth,
   )
   ```

2. **Implement a custom `AuthProvider`.** Subclass the ABC and validate whatever your
   issuer hands you (here, an opaque session/token your login flow created after a
   successful LDAP bind):

   ```python
   from typing import Any
   from fraiseql.auth import AuthProvider, UserContext

   class LDAPSessionProvider(AuthProvider):
       """Validate session tokens minted after an LDAP bind."""

       async def validate_token(self, token: str) -> dict[str, Any]:
           session = await self._lookup_session(token)
           if session is None or session.expired():
               raise ValueError("Session invalid or expired")
           return {"sub": session.user_id, "roles": session.roles}

       async def get_user_from_token(self, token: str) -> UserContext:
           payload = await self.validate_token(token)
           return UserContext(
               user_id=payload["sub"],
               roles=payload.get("roles", []),
           )

   app = create_fraiseql_app(
       database_url="postgresql://localhost/mydb",
       types=[User],
       queries=[...],
       auth=LDAPSessionProvider(),
   )
   ```

The LDAP bind itself (the `LDAPAuthenticationProvider` shown above) lives in your login
endpoint or a custom FastAPI route; FraiseQL only validates the credential it issues.

---

## 6. Session Management

### 6.1 Stateless Sessions (JWT)

**Advantages:**

- Scalable (no server-side storage)
- Distributed-friendly (each server can validate)
- Mobile-friendly
- CDN/edge-cacheable

**Disadvantages:**

- Cannot revoke immediately (token stays valid until expiry)
- Token contains claims (privacy consideration)
- Size overhead (increases request/response size)

### 6.2 Stateful Sessions (Cookies)

**Advantages:**

- Can revoke immediately
- Smaller tokens (just session ID)
- Traditional web browser support
- CSRF protection easier

**Disadvantages:**

- Requires server-side state (session store)
- Not as scalable
- Requires sticky sessions or shared store

### 6.3 Hybrid Approach (Recommended)

Combine stateless and stateful for best of both:

```python
class HybridSessionManager:
    """Combine JWT (stateless) and session store (stateful)"""

    def __init__(
        self,
        jwt_validator: JWTTokenValidator,
        session_store: SessionStore,
        access_token_expires: int = 900,  # 15 minutes
        refresh_token_expires: int = 604800  # 7 days
    ):
        self.jwt_validator = jwt_validator
        self.session_store = session_store
        self.access_token_expires = access_token_expires
        self.refresh_token_expires = refresh_token_expires

    async def create_session(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str]
    ) -> SessionPair:
        """Create new session with access + refresh tokens

        Access token:
        - JWT (stateless)
        - Short-lived (15 min)
        - Sent with each request
        - Can't be revoked (expires quickly)

        Refresh token:
        - Stored in session store (stateful)
        - Long-lived (7 days)
        - Used only to get new access token
        - Can be revoked

        Returns:
            SessionPair with access_token and refresh_token
        """
        # Create access token (stateless JWT)
        access_token = self.jwt_generator.generate_token(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            expires_in_seconds=self.access_token_expires
        )

        # Create refresh token (stateful)
        refresh_token_value = secrets.token_urlsafe(32)
        session_record = SessionRecord(
            session_id=refresh_token_value,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=self.refresh_token_expires),
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.remote_addr,
            revoked=False
        )
        await self.session_store.save(session_record)

        return SessionPair(
            access_token=access_token,
            refresh_token=refresh_token_value,
            expires_in=self.access_token_expires
        )

    async def refresh_access_token(
        self,
        refresh_token: str
    ) -> str:
        """Exchange refresh token for new access token

        Process:
        1. Validate refresh token (check session store)
        2. Verify not revoked or expired
        3. Generate new access token
        4. Optionally rotate refresh token
        """
        session_record = await self.session_store.get(refresh_token)
        if not session_record:
            raise SessionError("Refresh token not found")

        if session_record.revoked:
            raise SessionError("Refresh token has been revoked")

        if session_record.expires_at < datetime.utcnow():
            raise SessionError("Refresh token has expired")

        # Generate new access token
        new_access_token = self.jwt_generator.generate_token(
            user_id=session_record.user_id,
            tenant_id=session_record.tenant_id,
            roles=session_record.roles,
            expires_in_seconds=self.access_token_expires
        )

        # Optional: Rotate refresh token (invalidate old, create new)
        if should_rotate_refresh_token():
            await self.session_store.delete(refresh_token)
            new_refresh_token = await self.create_session(
                user_id=session_record.user_id,
                tenant_id=session_record.tenant_id,
                roles=session_record.roles
            )
            return new_access_token, new_refresh_token.refresh_token

        return new_access_token

    async def revoke_session(self, refresh_token: str) -> None:
        """Revoke refresh token (logout)

        Marking refresh_token as revoked prevents:
        - Getting new access tokens
        - Continuing session
        - Re-authenticating with same token
        """
        session_record = await self.session_store.get(refresh_token)
        if session_record:
            session_record.revoked = True
            await self.session_store.save(session_record)
```

---

## 7. Token Revocation

### 7.1 Immediate Revocation (Stateful)

For tokens that need immediate revocation (password change, logout, compromise):

```python
class TokenRevocationStore:
    """Store revoked tokens for immediate invalidation"""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def revoke_token(
        self,
        token: str,
        jwt_payload: dict[str, Any],
        reason: str = "user_logout"
    ) -> None:
        """Revoke token immediately

        Args:
            token: JWT token string
            jwt_payload: Decoded JWT payload (contains exp)
            reason: Revocation reason for audit
        """
        # Calculate TTL = token expiration - now
        now = datetime.utcnow()
        exp = datetime.fromtimestamp(jwt_payload["exp"])
        ttl_seconds = int((exp - now).total_seconds())

        if ttl_seconds > 0:
            # Store token hash in Redis with TTL
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            key = f"revoked_token:{token_hash}"

            await self.redis.setex(
                key,
                ttl_seconds,
                json.dumps({
                    "user_id": jwt_payload["sub"],
                    "tenant_id": jwt_payload["tenant_id"],
                    "reason": reason,
                    "revoked_at": now.isoformat()
                })
            )

    async def is_revoked(self, token: str) -> bool:
        """Check if token has been revoked"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        key = f"revoked_token:{token_hash}"
        return await self.redis.exists(key)
```

### 7.2 Revocation Reasons

```python
class RevocationReason(Enum):
    """Reasons for token revocation"""

    # User-initiated
    USER_LOGOUT = "user_logout"                    # Normal logout
    PASSWORD_CHANGED = "password_changed"          # User changed password
    PERMISSION_CHANGED = "permission_changed"      # User's permissions modified
    ROLE_CHANGED = "role_changed"                  # User's role changed
    ACCOUNT_DISABLED = "account_disabled"          # Account suspended

    # Security
    TOKEN_COMPROMISED = "token_compromised"        # Suspected token leak
    SUSPICIOUS_ACTIVITY = "suspicious_activity"    # Anomalous activity detected
    BREACH_DETECTED = "breach_detected"            # Security breach identified
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"    # Abusive token use

    # Administrative
    POLICY_CHANGE = "policy_change"                # Security policy changed
    TENANT_DEACTIVATED = "tenant_deactivated"      # Tenant shut down
    FORCE_REAUTHENTICATE = "force_reauthenticate"  # Admin force re-auth

    # Technical
    SESSION_TIMEOUT = "session_timeout"            # Inactivity timeout
    DEVICE_LOST = "device_lost"                    # Device marked as lost
    LOGOUT_ALL_DEVICES = "logout_all_devices"      # Log out all sessions
```

---

## 8. Multi-Tenant Authentication

### 8.1 Tenant Context Propagation

Every request includes tenant context for isolation:

```python
class TenantContext:
    """User's tenant context for authorization and data isolation"""

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        roles: list[str],
        is_tenant_admin: bool = False
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.roles = roles
        self.is_tenant_admin = is_tenant_admin

    def can_access_tenant(self, target_tenant_id: str) -> bool:
        """Check if user can access another tenant

        Users typically can only access their own tenant.
        Exception: Platform admins (system administrators).
        """
        return self.tenant_id == target_tenant_id or "platform_admin" in self.roles
```

### 8.2 Tenant-Scoped Authorization

FraiseQL v1 enforces tenant scoping with PostgreSQL **Row-Level Security (RLS)** and/or an
operation-level `Authorizer` — there is no `@FraiseQL.authorize`/`authorization_rule`
decorator. The CQRS repository sets session GUCs (`SET LOCAL app.tenant_id = …`) from
`info.context["tenant_id"]`, so RLS policies see the current tenant automatically.

Define the type as usual and let RLS do the filtering:

```python
import fraiseql
from fraiseql.types import ID

@fraiseql.type(sql_source="v_post", jsonb_column="data")
class Post:
    """Posts are scoped to the owning tenant via RLS."""
    id: ID
    title: str
    content: str
```

```sql
-- The v_post view (and its tb_post backing table) carries tenant_id;
-- RLS restricts every read to the request's tenant.
ALTER TABLE tb_post ENABLE ROW LEVEL SECURITY;

CREATE POLICY post_tenant_isolation ON tb_post
    USING (fk_customer_org = current_setting('app.tenant_id')::uuid);
```

For row-by-row decisions that go beyond RLS, attach an `Authorizer` to the operation
via `@fraiseql.query(authorizer=...)` (or globally on `create_fraiseql_app(authorizer=...)`).
The authorizer returns an `AuthorizationDecision.allow(...)` / `.deny(...)`:

```python
import fraiseql
from typing import Any
from fraiseql.security.authorization import AuthorizationDecision

class TenantAuthorizer:
    async def authorize_operation(
        self,
        *,
        context: dict[str, Any],
        operation_type,
        operation_name: str,
        arguments: dict[str, Any],
    ) -> AuthorizationDecision:
        if context.get("user") is None:
            return AuthorizationDecision.deny()
        # AND a tenant filter into the read's mandatory_filters.
        return AuthorizationDecision.allow(
            filters={"tenant_id": context["tenant_id"]},
        )

@fraiseql.query(authorizer=TenantAuthorizer())
async def posts(info) -> list[Post]:
    db = info.context["db"]
    return await db.find("v_post")
```

### 8.3 Multi-Tenant Database Strategy

FraiseQL v1 targets a **single PostgreSQL database**. The recommended (and built-in)
isolation strategy is **shared tables with RLS**: every tenant's rows live in the same
`tb_`/`v_`/`tv_` objects, and Row-Level Security restricts each request to its tenant.

Tenant context flows automatically:

```text
request → info.context["tenant_id"] → SET LOCAL app.tenant_id = … → RLS policies
```

The repository issues `SET LOCAL app.tenant_id = …` (and `app.user_id`,
`app.is_super_admin`, etc.) per transaction from `info.context`, so policies like the one
in §8.2 filter every query. You can additionally pass
`mandatory_filters={"tenant_id": ...}` to `db.find`/`db.count` for defence in depth.

If you need stronger physical isolation, use **schema-per-tenant** inside the same
database (one `search_path` per tenant) — still one PostgreSQL instance, one connection
pool. Separate databases or servers per tenant are an operational/deployment choice
outside FraiseQL; v1 does not route across multiple databases.

---

## 9. Security Best Practices

### 9.1 Token Storage

| Storage Method | XSS Risk | CSRF Risk | Use Case | Security |
|---|---|---|---|---|
| **localStorage** | ⚠️ High | ✅ Low | SPA | ❌ Not recommended |
| **sessionStorage** | ⚠️ High | ✅ Low | SPA | ❌ Not recommended |
| **Cookie (httpOnly)** | ✅ Low | ⚠️ Medium | Web | ✅ Recommended |
| **Memory variable** | ✅ Low | ✅ Low | SPA | ✅ Recommended (but lost on refresh) |
| **Secure httpOnly cookie** | ✅ Low | ✅ Low (with SameSite) | All | ✅ Best practice |

**Recommended:** Secure httpOnly cookie with SameSite=Strict

```python
response.set_cookie(
    key="access_token",
    value=token,
    httponly=True,        # Prevent JavaScript access (XSS protection)
    secure=True,          # Only send over HTTPS
    samesite="Strict",    # Prevent CSRF attacks
    max_age=900,          # 15 minutes
    domain="api.example.com",
    path="/graphql"
)
```

### 9.2 CSRF Protection

Protect against Cross-Site Request Forgery. FraiseQL v1 ships real CSRF protection in
`fraiseql.security` (there is no hook framework — wire it as standard FastAPI middleware
on the app returned by `create_fraiseql_app`):

```python
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.security.csrf_protection import (
    create_production_csrf_config,
    setup_csrf_protection,
)

app = create_fraiseql_app(
    database_url="postgresql://localhost/mydb",
    types=[...],
    queries=[...],
)

# Validates an X-CSRF-Token header on state-changing (mutation) operations,
# checks Origin/Referer, and exposes a token-issuing endpoint.
csrf_config = create_production_csrf_config(secret_key="...")
setup_csrf_protection(app, csrf_config)
```

The middleware (`CSRFProtectionMiddleware` / `GraphQLCSRFValidator`) skips safe operations
(queries, `GET`/`HEAD`/`OPTIONS`) and enforces the token only on mutations, returning a
GraphQL/JSON error response when validation fails.

### 9.3 Rate Limiting & Brute Force Protection

```python
class AuthenticationRateLimiter:
    """Prevent brute force attacks on authentication endpoints"""

    def __init__(self, redis_client, max_attempts: int = 5, window_seconds: int = 300):
        self.redis = redis_client
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    async def check_rate_limit(self, identifier: str) -> bool:
        """Check if authentication attempt should be allowed

        Args:
            identifier: User identifier or IP address

        Returns:
            True if attempt allowed, False if rate limited
        """
        key = f"auth_attempts:{identifier}"
        attempts = await self.redis.incr(key)

        if attempts == 1:
            await self.redis.expire(key, self.window_seconds)

        if attempts > self.max_attempts:
            return False

        return True

    async def get_lockout_time(self, identifier: str) -> int:
        """Get remaining lockout time in seconds"""
        key = f"auth_attempts:{identifier}"
        return await self.redis.ttl(key)
```

### 9.4 Credential Validation

```python
class CredentialValidator:
    """Validate credentials before authentication attempt"""

    @staticmethod
    def validate_password(password: str) -> None:
        """Enforce strong password requirements

        Requirements:
        - Minimum 12 characters
        - At least one uppercase letter
        - At least one number
        - At least one special character
        """
        if len(password) < 12:
            raise ValidationError("Password must be at least 12 characters")

        if not any(c.isupper() for c in password):
            raise ValidationError("Password must contain uppercase letter")

        if not any(c.isdigit() for c in password):
            raise ValidationError("Password must contain digit")

        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            raise ValidationError("Password must contain special character")

    @staticmethod
    def validate_email(email: str) -> None:
        """Validate email format and deliverability"""
        import re
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, email):
            raise ValidationError("Invalid email format")
```

---

## 10. Audit & Compliance

### 10.1 Authentication Event Logging

```python
class AuthenticationAuditLog:
    """Log authentication events for compliance and investigation"""

    async def log_event(
        self,
        event_type: str,
        user_id: str | None,
        tenant_id: str,
        status: str,
        ip_address: str,
        user_agent: str,
        details: dict[str, Any] | None = None
    ) -> None:
        """Log authentication event

        Events logged:
        - LOGIN_SUCCESS
        - LOGIN_FAILED (with reason)
        - LOGOUT
        - TOKEN_REFRESH
        - PASSWORD_RESET
        - PERMISSION_CHANGED
        - TOKEN_REVOKED
        - SUSPICIOUS_ACTIVITY
        """
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "status": status,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "details": details or {}
        }

        # Store in immutable audit table
        await self.db.execute("""
            INSERT INTO audit_log_authentication (
                timestamp, event_type, user_id, tenant_id,
                status, ip_address, user_agent, details
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, event.values())
```

### 10.2 Compliance Requirements

**SOC 2 Type II:**

- Audit trail for all authentication events
- Secure token storage and transmission
- Rate limiting on authentication endpoints
- Monitoring for suspicious patterns

**GDPR:**

- User consent for data processing
- Right to deletion (archive authentication logs)
- Audit trail retention policies
- Data minimization (collect only necessary claims)

**HIPAA:**

- Secure token transmission (HTTPS only)
- Encryption at rest and in transit
- Access control and audit logging
- Session timeout requirements

---

## 11. Performance Optimization

### 11.1 JWT Caching

Cache JWT validation results to avoid repeated cryptographic operations:

```python
class CachedJWTValidator:
    """Cache JWT validation for performance"""

    def __init__(
        self,
        jwt_validator: JWTTokenValidator,
        cache_ttl: int = 60  # Cache valid tokens for 60 seconds
    ):
        self.jwt_validator = jwt_validator
        self.cache_ttl = cache_ttl
        self.cache = {}

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate token with caching

        Cache hit: 1-2 microseconds
        Cache miss: 5-10 milliseconds (signature verification)
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        if token_hash in self.cache:
            cached = self.cache[token_hash]
            if cached["expires_at"] > datetime.utcnow():
                return cached["payload"]

        # Validate token
        payload = self.jwt_validator.validate_token(token)

        # Cache result
        self.cache[token_hash] = {
            "payload": payload,
            "expires_at": datetime.utcnow() + timedelta(seconds=self.cache_ttl)
        }

        return payload
```

### 11.2 Provider Fallback (Migration)

When migrating between auth providers (for example, cutting over from a legacy issuer to
Auth0), wrap two `AuthProvider` instances and try them in order. Each implements the real
`async get_user_from_token(token) -> UserContext` contract from `fraiseql.auth`:

```python
from fraiseql.auth import AuthProvider, UserContext

async def resolve_user_with_fallback(
    token: str,
    primary_provider: AuthProvider,
    secondary_provider: AuthProvider | None = None,
) -> UserContext:
    """Validate the token with the primary provider, fall back to the secondary.

    Allows migration between providers without downtime.
    """
    try:
        return await primary_provider.get_user_from_token(token)
    except Exception as e:
        if secondary_provider is not None:
            try:
                return await secondary_provider.get_user_from_token(token)
            except Exception:
                raise e  # Surface the primary provider's error
        raise
```

---

## 12. Error Handling

FraiseQL v1's built-in authentication errors live in `fraiseql.auth` and subclass plain
`Exception`: `AuthenticationError`, `TokenExpiredError`, `InvalidTokenError`,
`InsufficientPermissionsError`. Authorization *denials* do not raise an HTTP 4xx from a
router — they surface as a GraphQL error with a stable `extensions.code` (default
`"FORBIDDEN"`), produced by the `Authorizer` / field-authorization machinery in
`fraiseql.security`.

```python
from fraiseql.auth import AuthenticationError  # base; subclasses Exception

class InvalidCredentialsError(AuthenticationError):
    """Invalid username/password."""

class TokenRevokedError(AuthenticationError):
    """Token has been revoked (logout/password change)."""

class CSRFError(AuthenticationError):
    """CSRF token validation failed."""

class RateLimitExceededError(AuthenticationError):
    """Too many authentication attempts."""
```

Your own resolvers raise `graphql.GraphQLError` (optionally with
`extensions={"code": "..."}`) for client-facing failures; the `Authorizer` does this for
you when a decision denies. When auth runs inside the native FastAPI router
(`fraiseql.auth.native.router`), REST endpoints return the usual FastAPI status codes
(`401`/`403`/`429`) — these are HTTP responses from the Python app, not a separate router
layer.

---

## Summary

FraiseQL authentication specification provides:

✅ **Multiple Authentication Schemes**

- OAuth2 (Authorization Code, Client Credentials, Refresh Token)
- SAML 2.0 (Enterprise SSO)
- JWT (Stateless tokens)
- Session cookies (Stateful)
- Custom providers (Extensible)

✅ **Complete Token Lifecycle**

- Generation and signing
- Validation and claims extraction
- Refresh and rotation
- Revocation and expiration

✅ **Enterprise Security**

- Multi-tenant isolation
- CSRF protection
- Rate limiting
- Audit logging
- Compliance support (SOC 2, GDPR, HIPAA)

✅ **Performance**

- Token caching
- Parallel authentication
- Efficient key rotation
- Minimal crypto overhead

✅ **User Experience**

- Seamless token refresh
- Cross-domain SSO support
- Mobile and SPA support
- Traditional web app support

---

**Next**: advanced-optimization.md covers query optimization, database tuning, and scaling strategies.
