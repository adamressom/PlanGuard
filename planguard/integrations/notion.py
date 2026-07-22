from .base import CachedIntegration


class NotionIntegration(CachedIntegration):
    provider = "notion"

    def fetch(self):
        raise RuntimeError("Notion OAuth is not configured yet")

