from dataclasses import dataclass


@dataclass
class SyncResult:
    ok: bool
    data: list
    source: str
    message: str = ""


class CachedIntegration:
    provider = "external"

    def fetch(self):
        """Implement OAuth API retrieval in the full build."""
        raise NotImplementedError

    def fetch_with_fallback(self, cached_data=None):
        try:
            return SyncResult(True, self.fetch(), self.provider)
        except Exception as exc:  # boundary intentionally catches provider failures
            return SyncResult(False, cached_data or [], "cache", str(exc))

