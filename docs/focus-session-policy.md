# Assignment deletion and focus sessions

PlanGuard persists focus sessions and applies this policy when an assignment is deleted:

- Scheduled or active focus sessions are deleted with the assignment because they are actionable plan items.
- Completed and manually ended focus sessions are retained as study-history records, with a frozen duration, assignment title snapshot, and nullable `assignment_id` set to `NULL`.
- The shared assignment service enforces the policy for both page and JSON deletion routes.

This keeps the current plan clean without erasing a student's completed study history.
