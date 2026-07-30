# PlanGuard JSON API

The stable JSON surface is versioned under `/api/v1`. Existing unversioned
endpoints remain for the current browser frontend.

## Response convention

Successful responses use:

```json
{
  "data": {},
  "meta": {}
}
```

`meta` is included only when useful, such as collection counts or cached-sync
warnings.

Failures use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Assignment validation failed.",
    "fields": {
      "title": "Title is required."
    }
  }
}
```

All endpoints require the signed-in PlanGuard session. User-owned records that
do not exist or belong to another user return the same `404 not_found`
response.

## Assignments

```text
GET    /api/v1/assignments
POST   /api/v1/assignments
GET    /api/v1/assignments/{id}
PATCH  /api/v1/assignments/{id}
DELETE /api/v1/assignments/{id}
GET    /api/v1/assignments/{id}/priority-explanation
```

Assignment create and update requests use `course_impact` for the course-weight
percentage and ISO 8601 strings for deadlines.

## Focus sessions

```text
GET  /api/v1/focus-sessions
GET  /api/v1/focus-sessions/active
POST /api/v1/focus-sessions
POST /api/v1/focus-sessions/{id}/pause
POST /api/v1/focus-sessions/{id}/resume
POST /api/v1/focus-sessions/{id}/end
```

Start requests require `assignment_id` and `planned_minutes`. End requests may
include `{"reason": "timer_complete"}`.

## Integrations

Providers are `google_calendar` and `notion`.

```text
GET  /api/v1/integrations/{provider}/status
POST /api/v1/integrations/{provider}/connect
POST /api/v1/integrations/{provider}/disconnect
POST /api/v1/integrations/google_calendar/sync
```

Connect returns an `authorization_url`; the browser must navigate there to
complete OAuth or the clearly labelled demo consent flow. Notion imports use
the source-selection and mapping workflow rather than a generic sync endpoint.
