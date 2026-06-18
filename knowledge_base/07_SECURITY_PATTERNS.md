# Security Patterns

## Authentication Architecture

### JWT-Based Authentication
- JWT tokens contain: sub (user ID), tenant_id, role, project_ids
- Tokens are signed with HS256 algorithm
- Tokens have expiration times
- Tokens are stored in httpOnly cookies

**Reusable Insight:** httpOnly cookies prevent XSS attacks. Never store tokens in localStorage or sessionStorage.

### Token Lifecycle
1. User submits credentials (email + password)
2. Server validates credentials against database
3. Server generates JWT with claims
4. Server sets httpOnly cookie with Secure, SameSite flags
5. Browser sends cookie automatically with requests
6. Server validates token on each request
7. Token blacklist (Redis) for logout

**Reusable Insight:** JWTs are stateless by design. Use a Redis blacklist for logout and token revocation.

### Password Reset Flow
1. User requests password reset
2. Server generates time-limited reset token
3. Token is stored in database with expiration
4. Reset link sent to user email
5. User submits new password with token
6. Server validates token, updates password, invalidates token

**Reusable Insight:** Password reset tokens should be single-use and time-limited. Invalidate them immediately after use.

## Authorization

### Role-Based Access Control (RBAC)
- Roles: ADMIN, CLIENT
- ADMIN: Full access to all features
- CLIENT: Access to assigned projects only
- Role is embedded in JWT claims

**Reusable Insight:** RBAC should be enforced at the data access layer, not the UI layer. The UI can hide features, but the API must enforce access.

### Project-Level Authorization
- Users are assigned to specific projects
- JWT contains list of accessible project IDs
- Repository methods filter by project IDs
- Admin users bypass project restrictions

**Reusable Insight:** Authorization should be a filter, not a gate. Filter results by accessible projects, don't block access entirely.

## Encryption

### Password Hashing
- PBKDF2-SHA256 with 120,000 iterations
- Unique salt per password
- Timing-attack resistant comparison
- Minimum password length enforcement

**Reusable Insight:** PBKDF2 is a well-tested standard. Don't invent your own hashing algorithm. Use the crypto library, not a custom implementation.

### Secret Encryption (AES-256-GCM)
- Provider secrets (API keys, OAuth tokens) encrypted at rest
- AES-256-GCM provides authenticated encryption
- Unique nonce per encryption
- Encryption key from environment variable

**Reusable Insight:** Encrypt sensitive data at rest. Database breaches are common; encrypted data is useless to attackers.

### Key Management
- Encryption keys in environment variables
- Keys rotated via deployment
- No keys in code or configuration files
- Key rotation requires re-encryption of existing data

**Reusable Insight:** Key management is the hardest part of encryption. Start simple (env vars), but plan for rotation from day one.

## Network Security

### Security Headers
- Strict-Transport-Security (HSTS)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- Content-Security-Policy
- Referrer-Policy: strict-origin-when-cross-origin

**Reusable Insight:** Security headers are free protection. Configure them in your reverse proxy, not your application.

### CORS Configuration
- Explicit allowed origins
- No wildcard origins
- Credentials allowed for authenticated requests
- Preflight caching

**Reusable Insight:** CORS is a browser security feature. Configure it correctly to prevent cross-origin data theft.

### Rate Limiting
- Authentication: 10 requests per minute
- Admin operations: 5 requests per hour
- Global API: 100 requests per minute
- Redis-backed for distributed deployments

**Reusable Insight:** Rate limiting prevents abuse. Implement it even if you don't expect attacks.

## Input Validation

### Pydantic Validation
- All request bodies validated against schemas
- Invalid requests return 422 with details
- Type coercion where safe
- Custom validators for business rules

**Reusable Insight:** Validate at the boundary. Never trust input from clients, even authenticated ones.

### SQL Injection Prevention
- Parameterized queries (asyncpg)
- No string concatenation for SQL
- Repository methods use typed parameters

**Reusable Insight:** Parameterized queries are the only defense against SQL injection. Never use string formatting for SQL.

### XSS Prevention
- React auto-escapes output
- No dangerouslySetInnerHTML
- CSP headers as defense in depth

**Reusable Insight:** React handles XSS prevention by default. Only bypass it when absolutely necessary, and sanitize input first.

## Audit and Logging

### Audit Trail
- Login/logout events logged
- Admin actions logged
- Data refresh events logged
- Failed authentication attempts logged

**Reusable Insight:** Log security-relevant events. You can't investigate what you didn't log.

### Sensitive Data Handling
- Passwords never logged
- Tokens never logged
- Secrets redacted in logs
- PII minimized in logs

**Reusable Insight:** Logs are a security liability. Never log sensitive data. Redact secrets, hash PII.
