# Testing Strategy

## Testing Philosophy

### Test Pyramid
```
        /\
       /  \      E2E Tests (few)
      /----\
     /      \    Integration Tests (some)
    /--------\
   /          \  Unit Tests (many)
  /------------\
```

**Reusable Insight:** Most tests should be unit tests. They're fast, reliable, and cheap. Integration tests verify boundaries. E2E tests verify the whole system.

### Test Categories
- **Unit tests:** Individual functions and classes
- **Integration tests:** Component interactions
- **Contract tests:** Interface guarantees
- **Smoke tests:** Basic system health

## Backend Testing (pytest)

### Test Organization
```
backend_tests/
├── test_security.py        # JWT, password hashing
├── test_repository.py      # InMemory repository
├── test_tenancy.py         # Multi-tenant isolation
├── test_shopmetrics_*.py   # External API client
├── test_transform.py       # Data transformation
├── test_rate_limiter.py    # Rate limiting
├── test_refresh.py         # Ingestion refresh
└── test_password_reset.py  # Password reset flow
```

**Reusable Insight:** Organize tests by feature, not by file. All tests for a feature live together.

### Fixtures and Mocks
- pytest fixtures for setup/teardown
- Mock external API calls
- InMemory repository for testing
- Factory functions for test data

**Reusable Insight:** Fixtures make tests readable. Use them for common setup. Mock external dependencies.

### Known Gaps
- Zero tests for postgres_repository.py
- No HTTP-level two-tenant isolation tests
- Ingestion idempotency untested
- Rate limit thresholds untested

**Reusable Insight:** Test coverage is not 100% coverage. It's testing the right things. Focus on critical paths and edge cases.

## Frontend Testing (Vitest)

### Test Organization
```
tests/
├── rbac.test.ts            # Role-based access control
├── seed-parity.test.ts     # Data baseline verification
└── provider-contract.test.ts # Provider interface contracts
```

**Reusable Insight:** Frontend tests should focus on behavior, not implementation. Test what the user sees, not how it's built.

### Testing Approach
- Node environment for server component tests
- Provider contract tests for interface guarantees
- Data parity tests for consistency

**Reusable Insight:** Test the contracts between layers. If the provider interface is tested, the implementation can change safely.

## Test Data Management

### Factory Functions
- Deterministic test data
- Configurable parameters
- Realistic values
- No external dependencies

**Reusable Insight:** Test data should be generated, not hardcoded. Factories make it easy to create variations.

### Seed Data
- Baseline data for parity tests
- Known quantities for assertions
- Version-controlled
- Regenerated when schema changes

**Reusable Insight:** Seed data is documentation. It shows what valid data looks like.

## Continuous Integration

### CI Pipeline
1. Lint and type check
2. Unit tests
3. Integration tests
4. Build Docker images
5. Smoke tests against built images

**Reusable Insight:** CI should catch problems before they reach production. Fail fast, fail loud.

### Test Execution
- Parallel test execution
- Isolated test databases
- Clean state between tests
- Timeout protection

**Reusable Insight:** Tests should be fast and reliable. Slow tests get skipped. Flaky tests get fixed or deleted.

## Testing Anti-Patterns

### What to Avoid
- Testing implementation details
- Testing framework behavior
- Over-mocking (testing mocks, not code)
- Brittle tests (break on refactoring)
- Slow tests (take minutes to run)

**Reusable Insight:** A test that breaks on refactoring is testing implementation, not behavior. Good tests survive refactoring.

### What to Test
- Public interfaces
- Edge cases
- Error handling
- Business rules
- Integration points

**Reusable Insight:** Test behavior, not implementation. Test boundaries, not internals. Test what matters.
