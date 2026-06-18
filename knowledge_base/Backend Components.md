# Backend Components

## Database and Scalability

- Database should handle 1000 users
- Optimised queries
- Proper indexing
- Less changes when data grows from 100 to 100k

## Security

- Passwords should be stored securely
- HTTPS, TLS configuration and certificate rotation
- Authentication, authorization , roles, and permission
- Multi- tenancy and data isolation
- PII handling, data retention and deletion policies
- Session management and token expiry
- Regulatory compliance (GDPR, HIPAA)
- API keys to be protected
- Secrets management
- Validate user input
    - Input Sanitisation and Injection Prevention
- Rate limiting and abuse prevention
- Dependency scanning and vulnerability patching
- Immune to bots, scrapers and attackers

## Performance

- Fast page load
- Opitmised API
- Cache frequently accessed data
    - Cache strategy and invalidation
- How to handle traffic spikes
- RTO and RPO
- Accessibility

## Monitoring and Logs

- Loggings in important
- Audit trails and tamper evident logging
- Error tracking
- Performance monitoring

## Recovery

- Able to Roll back a bad deployment
- Disaster recovery plan
- Circuit breakers and fallback behavior
- Concurrency handling and race condition prevention

## Testing

- Unit, Integration and end to end testing
- Regression testing
- Load and stress testing
- Chaos engineering and resilience testing
- Test coverage thresholds enforced in CI
- Code review process and standards
- Retry logic with backoff and idempotency