# Windchill source boundary

`document_finder.sources.windchill` is an isolated preparation layer for a future Windchill WRS synchronization. It is not invoked by `ingest_directory`, the API, or the frontend.

The adapter normalizes a configured response contract into `WindchillDocument`, retaining a stable remote identity, document number, version, iteration, lifecycle state, modified timestamp, filename, and primary-content reference. `list_released_documents()` retains only documents whose lifecycle state is `Released`; `download_primary_content()` returns raw content bytes for a caller to stage and pass through the existing DOCX/PDF ingestion path.

Required future environment configuration:

- `WINDCHILL_BASE_URL`
- `WINDCHILL_USERNAME`
- `WINDCHILL_PASSWORD`
- `WINDCHILL_DOCUMENTS_PATH` — verified WRS document-collection path
- `WINDCHILL_LIBRARY_PARAMETER` / `WINDCHILL_FOLDER_PARAMETER` — verified parameter names for the configured scope

Optional scope and content configuration:

- `WINDCHILL_LIBRARY_ID` / `WINDCHILL_FOLDER_ID` — IDs used only with their corresponding verified parameter name
- `WINDCHILL_CONTENT_PATH_TEMPLATE` — a verified content path template using `{document_identity}`

No endpoint path, response field name, authentication scheme beyond the placeholder basic-auth transport, Library/folder identifier, or WRS pagination contract has been verified against an actual Windchill server. The test contract uses neutral `items` and `next` fields only. These must be confirmed and configured once Windchill 12.0.2.19 access is available.

`WindchillSyncState` is the comparison record for a future synchronizer: identity, version, iteration, lifecycle state, last-modified timestamp, and optional content hash. It supports detecting new, changed, and unchanged remote documents without connecting this source boundary to the current local ingestion pipeline.
