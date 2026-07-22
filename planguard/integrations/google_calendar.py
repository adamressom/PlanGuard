from .base import CachedIntegration


class GoogleCalendarIntegration(CachedIntegration):
    provider = "google_calendar"

    def fetch(self):
        raise RuntimeError("Google Calendar OAuth is not configured yet")

