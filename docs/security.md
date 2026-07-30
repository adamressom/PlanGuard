# Security and privacy

PlanGuard treats passwords, session credentials, and provider tokens as secrets.

- Set `SECRET_KEY` through the deployment environment. Production startup refuses
  to run without it.
- Set `TOKEN_ENCRYPTION_KEY` independently for live Google Calendar or Notion.
  OAuth access and refresh tokens are authenticated-encrypted at rest and are
  never rendered or logged.
- Passwords are stored with Werkzeug's password hashing, never as plaintext.
- Browser forms and authenticated JSON mutations require a CSRF token. The
  frontend sends the token in `X-CSRFToken` for JSON requests.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.
  Production also uses a `__Host-` cookie name.
- Login and registration POST requests are rate limited. Configure the threshold
  with `AUTH_RATE_LIMIT` (default `10 per minute`).
- `RATELIMIT_STORAGE_URI=memory://` is suitable for a single-process demo. Use a
  shared Flask-Limiter-compatible backend in a multi-process production
  deployment.

Provider failures are represented internally by controlled error codes. Raw OAuth
error descriptions, response bodies, authorization codes, and tokens must not be
included in application logs.
