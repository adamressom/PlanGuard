# PlanGuard User Story Input

Use this document as source material for generating user stories, acceptance criteria, and implementation tasks. PlanGuard is a decision-first study planner that helps students decide what to work on next by ranking assignments using deadline urgency, difficulty, estimated effort, course impact, progress, and available study time.

## Product Goal

Create a complete student planning app where a user can:

- Create an account and securely manage their own assignments.
- Add, edit, complete, and delete assignments.
- See a ranked priority queue of what to study next.
- Understand why each assignment received its priority score.
- Schedule or start focus blocks based on their available time.
- Connect Google Calendar and Notion to import workload and avoid calendar conflicts.
- Continue using cached planning data when external integrations fail.

## Current State

The existing app is a lean Flask prototype. It includes:

- Flask application structure.
- SQLAlchemy models for users, assignments, and integration state.
- A deterministic priority scoring service.
- Landing page and dashboard concept.
- Placeholder Google Calendar and Notion integration classes.
- Basic route and priority tests.

The dashboard currently uses hardcoded demo assignments rather than real database-backed user data. Authentication, assignment CRUD, real OAuth integrations, scheduling, and focus-session persistence still need to be built.

## User Story Areas

### 1. User Authentication

The app needs account creation and sign-in so each student has a private workspace.

Needed capabilities:

- Register with email, display name, and password.
- Sign in and sign out.
- Protect dashboard and app routes from anonymous access.
- Store passwords securely using hashing.
- Keep each user's assignments and integration settings separate.
- Show useful errors for invalid credentials or duplicate accounts.

### 2. Assignment Management

Students need to manage their real assignments instead of seeing demo data.

Needed capabilities:

- Add an assignment from the dashboard.
- Edit assignment details.
- Delete an assignment.
- Mark an assignment complete or incomplete.
- Track progress from 0 to 100 percent.
- Store assignment fields in the database.
- Validate required fields and sensible ranges.
- Show empty states when no assignments exist.

Suggested assignment fields:

- Title.
- Course.
- Deadline.
- Difficulty from 1 to 5.
- Estimated minutes.
- Course weight or grade impact.
- Progress percent.
- Completion status.
- Optional notes.
- Optional source integration/provider ID.

### 3. Priority Queue

Students need a ranked list that reflects their current workload and available study time.

Needed capabilities:

- Load assignments from the database for the signed-in user.
- Exclude or visually separate completed assignments.
- Rank active assignments using the existing priority engine.
- Allow the user to set available study time.
- Recalculate priorities when assignments or availability change.
- Highlight the top recommended assignment.
- Handle overdue assignments clearly.
- Handle assignments with missing or edge-case data safely.

### 4. Explain-My-Score

Students need to trust the recommendation, not just see a number.

Needed capabilities:

- Show the final priority score for each assignment.
- Break the score into contributing factors:
  - Deadline urgency.
  - Difficulty.
  - Course impact.
  - Estimated effort/time fit.
  - Current progress.
- Provide plain-language explanations for why an assignment ranks high or low.
- Make the explanation available from each assignment row.
- Include tests for score explanation output.

### 5. Focus Blocks

Students need to turn a recommendation into an actual study session.

Needed capabilities:

- Start a focus block for the recommended assignment.
- Show a working timer.
- Pause, resume, and end a focus block.
- Persist completed focus sessions.
- Update assignment progress after a session.
- Associate focus sessions with assignments and users.
- Show recent focus history or completed study time.

### 6. Calendar-Aware Scheduling

Students need PlanGuard to protect real study time around existing commitments.

Needed capabilities:

- Represent available study windows.
- Detect conflicts with calendar events.
- Recommend focus block times that fit the assignment's estimated effort.
- Support splitting large assignments into multiple blocks.
- Allow users to accept, adjust, or dismiss suggested blocks.
- Optionally export accepted focus blocks to Google Calendar.

### 7. Google Calendar Integration

Students need to connect their calendar so PlanGuard can avoid conflicts.

Needed capabilities:

- Start Google Calendar OAuth connection.
- Handle OAuth callback.
- Store access and refresh tokens securely.
- Refresh expired tokens.
- Fetch calendar events.
- Cache fetched calendar data.
- Show connected, disconnected, syncing, synced, and error states.
- Display last synced timestamp.
- Retry failed syncs with backoff.
- Fall back to cached calendar data when live sync fails.

### 8. Notion Integration

Students need to connect Notion so PlanGuard can import assignments or tasks.

Needed capabilities:

- Start Notion OAuth connection.
- Handle OAuth callback.
- Store tokens securely.
- Let the user choose a Notion database or source.
- Map Notion properties to assignment fields.
- Import assignments from Notion.
- Avoid duplicate imports.
- Cache imported data.
- Show connected, disconnected, syncing, synced, and error states.
- Retry failed syncs with backoff.

### 9. Integration Status UI

The current dashboard labels integrations as ready even though they are placeholders. The UI needs truthful connection states.

Needed capabilities:

- Show "Connect" when an integration is disconnected.
- Show "Syncing" during sync.
- Show "Synced" only after a successful sync.
- Show "Using cached data" when fallback data is active.
- Show actionable error messages when sync fails.
- Allow users to disconnect an integration.

### 10. Dashboard UX States

The dashboard needs to handle real-life app states gracefully.

Needed capabilities:

- First-time user state.
- No assignments state.
- Loading state.
- Sync failure state.
- Overdue assignments state.
- Completed assignments state.
- "Nothing urgent" state.
- Mobile-friendly layout.
- Keyboard-accessible dialogs and controls.

### 11. API Layer

The app needs JSON endpoints for interactive frontend behavior and future integrations.

Needed capabilities:

- Assignment create/read/update/delete endpoints.
- Focus session endpoints.
- Priority explanation endpoint.
- Integration connect/status/sync endpoints.
- Consistent JSON error responses.
- Server-side validation.
- Tests for API success and failure cases.

### 12. Database and Migrations

The app currently creates tables directly on startup. A complete app needs migration support.

Needed capabilities:

- Add Flask-Migrate or Alembic.
- Create initial migration scripts.
- Remove reliance on startup-only `db.create_all()` for production.
- Support local development and production database configuration.
- Add sample or seed data for demos.

### 13. Security and Privacy

The app handles student workload and external account data, so it needs stronger security.

Needed capabilities:

- Secure secret configuration.
- Password hashing.
- CSRF protection for forms.
- Secure session cookies.
- Token encryption for OAuth credentials.
- User authorization checks on all user-owned records.
- Safe handling of provider errors and sensitive logs.
- Basic rate limiting for auth routes.

### 14. Testing

The current tests cover the health route, landing/dashboard rendering, and priority scoring. More coverage is needed before the app is complete.

Needed test areas:

- Authentication flows.
- Assignment CRUD.
- User data isolation.
- Form validation.
- API validation and error responses.
- Focus session lifecycle.
- Integration fallback behavior.
- OAuth status handling.
- Priority explanation behavior.
- Dashboard empty/error states.

### 15. Accessibility and Responsive Polish

The app should work well for students on laptops and phones.

Needed capabilities:

- Keyboard navigation.
- Dialog focus management.
- Visible focus styles.
- Screen-reader labels for controls.
- Sufficient color contrast.
- Responsive assignment rows and panels.
- Text that does not overflow on small screens.
- Mobile-friendly forms and buttons.

### 16. Content and Encoding Cleanup

Some text may display incorrectly depending on file encoding or terminal rendering.

Needed capabilities:

- Verify templates render proper punctuation and symbols in the browser.
- Replace broken text such as mojibake characters if they appear in the UI.
- Keep UI copy consistent between landing page, dashboard, and integration states.

## Suggested Milestones

### Milestone 1: Real Assignments

Users can sign in and manage real database-backed assignments.

Potential stories:

- As a student, I can register and sign in so that my planning data is private.
- As a student, I can add an assignment so that PlanGuard can rank it.
- As a student, I can edit or delete an assignment so that my plan stays accurate.
- As a student, I can mark an assignment complete so that it no longer clutters my active queue.

### Milestone 2: Trustworthy Priority Queue

Users can see and understand ranked recommendations.

Potential stories:

- As a student, I can see my assignments ranked by priority so that I know what to work on next.
- As a student, I can see why an assignment has a high score so that I trust the recommendation.
- As a student, I can update my available study time so that recommendations fit my day.

### Milestone 3: Focus Workflow

Users can act on a recommendation.

Potential stories:

- As a student, I can start a focus block from the top recommendation so that I can begin studying quickly.
- As a student, I can pause and finish a focus session so that interruptions are handled realistically.
- As a student, I can update progress after a focus session so that future priorities adapt.

### Milestone 4: Connected Planning

Users can connect external tools and get calendar-aware recommendations.

Potential stories:

- As a student, I can connect Google Calendar so that PlanGuard avoids scheduling over existing events.
- As a student, I can connect Notion so that assignments can be imported automatically.
- As a student, I can see integration sync status so that I know whether my plan is current.
- As a student, I can keep using cached data when sync fails so that I am not blocked.

### Milestone 5: Production Readiness

The app is secure, tested, and reliable enough for real users.

Potential stories:

- As a developer, I can run database migrations so that schema changes are controlled.
- As a developer, I can run a full test suite so that core workflows are protected.
- As a student, I can use the app on mobile and with keyboard navigation so that it works in my normal study environment.
- As a student, my credentials and integration tokens are protected so that my data remains private.

