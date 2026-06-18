# RBAC Model - Role-Based Access Control

**Version:** 1.0  
**Last Updated:** 2026-05-29  
**Status:** PRODUCTION READY

---

## Overview

The Shopmetrics Dashboard Platform implements a strict multi-tenant RBAC model to ensure:
1. **Tenant Isolation** - Clients can only access their own data
2. **Least Privilege** - Users have minimum necessary permissions
3. **Single Admin** - Only one global administrator account
4. **Audit Trail** - Clear separation of admin vs client actions

---

## User Roles

### ADMIN Role

**Purpose:** System-wide administration and tenant management

**Account:**
- **Email:** `admin@demo.local`
- **User ID:** `user_admin`
- **Role:** `ADMIN`

**Database Record:**
```sql
INSERT INTO dashboard.users (
    user_id, tenant_id, email, name, role, project_ids
) VALUES (
    'user_admin',           -- Unique user ID
    NULL,                   -- NULL = global scope (no tenant restriction)
    'admin@demo.local',     -- Email for login
    'Demo Admin',           -- Display name
    'ADMIN',                -- Role
    ARRAY[]::TEXT[]         -- Empty = access to ALL projects
);
```

**Permissions:**
| Permission | Granted | Notes |
|------------|---------|-------|
| Access all tenants | ✅ | Can view/manage any tenant |
| Access all projects | ✅ | Can view/manage any project |
| Admin endpoints (`/admin/*`) | ✅ | User management, tenant config, etc. |
| Create/edit users | ✅ | Can create both ADMIN and CLIENT users |
| Trigger data refresh | ✅ | Can manually sync Shopmetrics data |
| View run logs | ✅ | Can see sync history |

**JWT Claims:**
```json
{
  "sub": "user_admin",
  "email": "admin@demo.local",
  "role": "ADMIN",
  "tenant_id": null,
  "project_ids": []
}
```

**Access Control Logic:**
```typescript
// Frontend (rbac.ts)
if (role === "ADMIN") {
  return allProjects;  // No filtering
}
```

```python
# Backend (postgres_repository.py)
if claims.role == Role.ADMIN:
    # Query ALL projects
    SELECT * FROM dashboard.projects
```

---

### CLIENT Role

**Purpose:** Tenant-scoped access to specific projects

**Database Record (Example):**
```sql
INSERT INTO dashboard.users (
    user_id, tenant_id, email, name, role, project_ids
) VALUES (
    'user_client',                      -- Unique user ID
    'tenant_labatt',                    -- REQUIRED: Tenant scope
    'client@demo.local',                -- Email for login
    'Demo Client',                      -- Display name
    'CLIENT',                           -- Role
    ARRAY['project_messi_flying_fish']  -- REQUIRED: Assigned projects
);
```

**Permissions:**
| Permission | Granted | Notes |
|------------|---------|-------|
| Access assigned tenant | ✅ | Only `tenant_id` matches their record |
| Access assigned projects | ✅ | Only projects in `project_ids` array |
| Admin endpoints | ❌ | 403 Forbidden |
| Create/edit users | ❌ | Admin-only function |
| Trigger data refresh | ❌ | Admin-only function |
| View run logs | ❌ | Admin-only function |

**JWT Claims:**
```json
{
  "sub": "user_client",
  "email": "client@demo.local",
  "role": "CLIENT",
  "tenant_id": "tenant_labatt",
  "project_ids": ["project_messi_flying_fish"]
}
```

**Access Control Logic:**
```typescript
// Frontend (rbac.ts line 88)
return projects.filter((p) => p.clientSlug === clientId);
// clientSlug maps to tenant_id from backend
```

```python
# Backend (postgres_repository.py line 40-50)
if claims.tenant_id is None or not claims.project_ids:
    return []  # No access

SELECT * FROM dashboard.projects
WHERE tenant_id = %s AND project_id = ANY(%s)
```

---

## Tenant Isolation

### Data Scoping

Every dashboard data row is scoped to a tenant:

```sql
-- All tables include tenant_id
dashboard.tenants (tenant_id PK)
dashboard.projects (tenant_id, project_id PK)
dashboard.visits (tenant_id, project_id, survey_id PK)
dashboard.visit_photos (tenant_id, project_id, survey_id, kind, url PK)
dashboard.project_metrics (tenant_id, project_id, key PK)
```

### Query Enforcement

**Backend Repository (ALL queries include tenant scope):**
```python
def list_visits(self, claims: AuthClaims, project_id: str) -> list[dict]:
    # Enforce tenant + project access
    project = assert_project_access(claims, self.get_project(project_id))
    
    # Query scoped to tenant
    SELECT * FROM dashboard.visits
    WHERE tenant_id = %s AND project_id = %s
```

**Frontend Authorization (rbac.ts):**
```typescript
export async function assertProjectAccess(projectId: string) {
  const session = await requireSession();
  const { role, clientId } = session.user;
  
  if (role === "ADMIN") return;  // Admin has global access
  
  // Client must match tenant
  if (!clientId || project.clientSlug !== clientId) {
    redirect("/dashboard");  // Access denied
  }
}
```

---

## Security Boundaries

### Backend API (Primary Security Boundary)

**ALL endpoints enforce RBAC:**
1. Extract JWT from `Authorization: Bearer <token>` header
2. Decode and validate claims
3. Check role and tenant_id before querying data
4. Never trust client-provided tenant_id parameters

**Example Endpoint:**
```python
@router.get("/projects/{project_id}/summary")
def get_project_summary(
    project_id: str,
    claims=Depends(get_current_claims),
    repository: DashboardRepository = Depends(get_repository),
):
    # assert_project_access enforces tenant isolation
    summary = repository.get_project_summary(claims, project_id)
    return to_public_dict(summary)
```

### Frontend (Defense in Depth)

**Server Components (token never exposed to client):**
```typescript
// src/app/dashboard/page.tsx
export default async function DashboardIndex() {
  const session = await requireSession();  // Server-side
  const projects = await listVisibleProjects();  // Server-side
  
  // Token stays on server, only rendered data goes to client
  return <ProjectList projects={projects} />;
}
```

**Client Components (use server actions):**
```typescript
// src/app/admin/users/users-client.tsx
export async function createUserAction(formData: FormData) {
  "use server";
  
  const cookieStore = await cookies();
  const token = cookieStore.get("auth_token")?.value;  // Server-side only
  
  await adminCreateUser(token, userData);
}
```

---

## User Lifecycle

### Creating a CLIENT User

**Admin Panel Flow:**
1. Admin navigates to `/admin/users`
2. Clicks "Create User"
3. Fills form:
   - Email: `manager@labatt.local`
   - Name: `Store Manager`
   - Role: `CLIENT`
   - Tenant: `tenant_labatt`
   - Projects: `project_messi_flying_fish`
4. Backend creates user with scoped permissions
5. User receives login credentials
6. User logs in → sees ONLY assigned tenant/projects

**SQL Equivalent:**
```sql
INSERT INTO dashboard.users (
    user_id, tenant_id, email, name, role, project_ids
) VALUES (
    'user_abc123',
    'tenant_labatt',
    'manager@labatt.local',
    'Store Manager',
    'CLIENT',
    ARRAY['project_messi_flying_fish']
);
```

### Creating an ADMIN User

**⚠️ WARNING:** Only `admin@demo.local` should exist in production.

**If additional admin is absolutely required:**
1. Must be created by existing admin
2. Requires explicit approval and audit logging
3. Should be temporary (for specific maintenance tasks)
4. Must be deleted after use

**Best Practice:** Use CLIENT role with elevated project access instead of ADMIN role.

---

## Testing RBAC

### Automated Tests

**Test 1: Client Isolation**
```python
def test_client_cannot_access_other_tenant():
    # Login as client_test_1 (tenant_test_01)
    token = login("client-test1@demo.local", "Demo123!")
    
    # Try to access project from tenant_test_02
    response = get("/projects/project_test_client_bravo", token)
    
    assert response.status_code == 403
```

**Test 2: Admin Global Access**
```python
def test_admin_can_access_all_tenants():
    token = login("admin@demo.local", "Demo123!")
    
    # Access any project
    projects = get("/projects", token)
    
    assert len(projects) == total_project_count
```

**Test 3: Client Sees Assigned Projects**
```python
def test_client_sees_only_assigned_projects():
    token = login("client@demo.local", "Demo123!")
    
    projects = get("/projects", token)
    
    assert len(projects) == 1
    assert projects[0].id == "project_messi_flying_fish"
    assert projects[0].tenant_id == "tenant_labatt"
```

### Manual Testing Checklist

- [ ] Admin login → sees all projects
- [ ] Admin can access `/admin/users`
- [ ] Admin can create CLIENT user
- [ ] CLIENT login → sees only assigned projects
- [ ] CLIENT cannot access `/admin/*` (403)
- [ ] CLIENT A cannot see CLIENT B's data
- [ ] CLIENT cannot access projects outside their `project_ids`

---

## Migration History

### 2026-05-29: RBAC Cleanup (Phase 5.1)

**Problem:** Seed script was creating test admin users (`admin_test_1` through `admin_test_10`), violating the single-admin principle.

**Solution:**
1. Modified `scripts/seed_multi_tenant_test_data.py` to only create CLIENT users
2. Created `scripts/cleanup_test_admins.py` to remove existing test admins
3. Executed cleanup: deleted 10 test admin accounts
4. Verified only `admin@demo.local` remains with ADMIN role

**Before:**
```
ADMIN users: 11 (1 legitimate + 10 test)
CLIENT users: 12
```

**After:**
```
ADMIN users: 1 (admin@demo.local only)
CLIENT users: 12
```

---

## Future Enhancements

### Planned (Post-Phase 6)

1. **Role Hierarchies** - Support for custom roles with granular permissions
2. **Project-Level Roles** - Different roles per project (viewer, editor, admin)
3. **Audit Logging** - Track all admin actions for compliance
4. **Session Management** - Admin can revoke user sessions
5. **MFA Support** - Two-factor authentication for admin accounts

### Not Planned (v1)

- SSO integration (SAML/OAuth)
- LDAP/Active Directory sync
- Custom permission sets
- Time-based access restrictions

---

## References

- Phase 5.1 Implementation: `.claude/backend_integration/05.1_phase_5_rbac_fixes.md`
- Backend Repository: `services/common/postgres_repository.py`
- Frontend RBAC: `src/server/rbac.ts`
- Database Schema: `services/ingestion/dashboard_schema.sql`

---

**End of Document**
