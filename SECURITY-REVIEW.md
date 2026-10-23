# Security Review

## Findings

### HIGH — Active environment has debug mode enabled and a weak secret key

**Confidence:** 9/10 for the environment used by the deployment check; whether production uses the same environment is unverified.  
**Affected file:** `config/settings.py` (lines 22–25)

`manage.py check --deploy` reported Django warnings `security.W009` (the configured `SECRET_KEY` fails Django's strength checks) and `security.W018` (`DEBUG` is `True`) for the currently loaded environment. If these values are used on a public deployment, debug pages can expose internal details and a weak key can undermine signed data.

**Recommended remediation:** Before deployment, use a newly generated, high-entropy secret key from a protected environment variable or secret store, rotate any weak key that has been used publicly, and set `DEBUG=False`. Verify this against the production environment rather than assuming the local `.env` is the deployment configuration.

### MEDIUM — DOM-based cross-site scripting in toast messages

**Confidence:** 9/10  
**Affected files:**

- `tourist/templates/tourist/plan_my_trip.html` (lines 1634, 1656–1659)
- `itineraries/templates/itineraries/view.html` (lines 504, 526–529)

Both pages read a `toast` query parameter and interpolate its value into a toast using `innerHTML`. A crafted link opened by a signed-in tourist can execute attacker-controlled JavaScript in the app's origin.

**Recommended remediation:** Treat the query parameter as plain text and insert it with `textContent` (or an equivalent safe text-rendering API). Do not allow URL parameters to supply HTML.

### MEDIUM — Production encryption controls are not established by application settings

**Confidence:** 9/10 that these controls are absent from the repository configuration; actual deployment controls are unverified.  
**Affected file:** `config/settings.py` (middleware and database configuration; security flags and HSTS are not configured)

The application enables Django's `SecurityMiddleware`, but does not configure HTTPS redirection, HSTS, or secure session/CSRF cookie flags. `manage.py check --deploy` confirmed warnings for missing HTTPS redirection, HSTS, and secure-cookie settings. The configured database is a local SQLite file, and media is stored in a local directory; the application does not configure encryption at rest for either. Deployment-level TLS, encrypted disks/media storage, and encrypted backups cannot be verified from this repository.

**Recommended remediation:** Confirm that the production edge enforces HTTPS, then configure Django's production HTTPS/HSTS and secure-cookie settings appropriately. Confirm encryption for database, media, and backups at the hosting/storage layer. Do not enable HSTS or redirects locally without accounting for the deployment proxy and HTTPS termination.
