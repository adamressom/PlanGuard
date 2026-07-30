# Google Calendar integration

PlanGuard supports three modes: `disabled`, `demo`, and `live`.

## Demo

Configure `GOOGLE_CALENDAR_MODE=demo`. No Google account, OAuth credential,
encryption key, or network call is required. Choose **Connect demo calendar**
on the dashboard and approve the clearly labelled internal demo consent page.
PlanGuard then supplies generic simulated busy periods to the real scheduling
engine.

## Live configuration

Create a Google Cloud web OAuth client, enable the Calendar API, configure its
consent screen, and register the exact callback URI:

```text
http://localhost:5000/integrations/google-calendar/callback
```

Production callback URIs must use HTTPS. Keep these values outside source
control:

```text
GOOGLE_CALENDAR_MODE=live
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=https://example.com/integrations/google-calendar/callback
TOKEN_ENCRYPTION_KEY=...
TOKEN_ENCRYPTION_KEY_VERSION=v1
DEFAULT_TIMEZONE=America/New_York
```

Generate the token key with `cryptography.fernet.Fernet.generate_key()`. It must
be independent of Flask's `SECRET_KEY`. Live production startup fails if any
required setting is missing.

## Privacy and security

External commitments are normalized to generic `Busy` ranges. PlanGuard does
not need event titles, descriptions, attendees, locations, or meeting links.
Credentials live in a separate table under authenticated encryption and are
never serialized, placed in sessions, cached with events, or rendered.

OAuth state is random, user-bound, provider-bound, expires after ten minutes,
and is consumed once. Provider error descriptions are not rendered. Disconnect
clears credentials and cached conflicts without deleting assignments or focus
history. Tests inject provider behavior and require no live Google calls.

The scheduler checks calendar conflicts while recommending and again when a
student accepts or manually adjusts a block.

## Live synchronization and cached fallback

Live synchronization reads every selected calendar with reader access or
better. It follows calendar and event pagination, expands recurring events, and
queries from the beginning of today through eight days ahead. Cancelled,
declined, transparent, and working-location events are ignored. Opaque timed
and all-day events become generic UTC `Busy` ranges.

The cache is a versioned, privacy-reduced snapshot containing only its time
zone, exact coverage range, and merged busy ranges. A complete successful sync
replaces it atomically and updates `last_synced_at`; an empty complete result is
valid and clears old conflicts. Partial or failed retrieval never overwrites the
last complete cache.

Transient reads use at most three attempts with bounded exponential backoff.
When all attempts fail, PlanGuard uses the previous cache if it fully covers the
planning range. The dashboard distinguishes live, cached, syncing, stale, and
error states. Disconnecting clears both credentials and cached availability.

Status is derived from real connection and synchronization transitions.
`Synced` appears only after a complete successful API sync, while `Using cached
data` appears after a failed live attempt with valid cache coverage. The last
successful sync time is retained separately from the latest attempt.
