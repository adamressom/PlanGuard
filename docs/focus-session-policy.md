# Assignment deletion and focus sessions

PlanGuard does not yet persist focus sessions. When that model is introduced, assignment deletion will follow this policy:

- Scheduled or active focus sessions are deleted with the assignment because they are actionable plan items.
- Completed focus sessions are retained as study-history records, with an assignment title snapshot and a nullable `assignment_id` set to `NULL`.
- Database foreign keys will enforce these behaviors rather than relying only on route code.

This keeps the current plan clean without erasing a student's completed study history.
