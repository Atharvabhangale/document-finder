"""External document-source adapters.

Adapters in this package are intentionally not connected to local ingestion until a
caller explicitly orchestrates a synchronization.
"""

from .windchill import (
    WindchillClient,
    WindchillDocument,
    WindchillSettings,
    WindchillSyncState,
)

__all__ = ["WindchillClient", "WindchillDocument", "WindchillSettings", "WindchillSyncState"]
