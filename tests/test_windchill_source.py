from __future__ import annotations

import json
from dataclasses import replace

import pytest

from document_finder.sources.windchill import (
    HttpResponse,
    WindchillApiError,
    WindchillAuthenticationError,
    WindchillClient,
    WindchillConfigurationError,
    WindchillDocument,
    WindchillDuplicateDocumentError,
    WindchillMalformedResponseError,
    WindchillSettings,
    WindchillSyncState,
)


def payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "identity": "OR:wt.doc.WTDocument:42", "document_number": "SOP-001",
        "filename": "Example SOP.pdf", "version": "A", "iteration": "3",
        "lifecycle_state": "Released", "last_modified": "2026-08-19T10:00:00Z",
        "content_url": "/configured/content/42",
    }
    value.update(overrides)
    return value


class MockTransport:
    def __init__(self, responses: list[HttpResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get(self, url: str, *, headers: object, params: dict[str, str] | None = None) -> HttpResponse:
        self.calls.append((url, params))
        return self.responses.pop(0)


def response(status: int, value: object, **headers: str) -> HttpResponse:
    body = value if isinstance(value, bytes) else json.dumps(value).encode()
    return HttpResponse(status, headers, body)


def settings() -> WindchillSettings:
    return WindchillSettings(
        base_url="https://windchill.example.invalid", username="service", password="secret",
        library_id="library", folder_id="folder", documents_path="/configured/documents",
        library_parameter_name="configured_library", folder_parameter_name="configured_folder",
    )


def test_metadata_identity_version_lifecycle_and_modified_parsing() -> None:
    document = WindchillDocument.from_payload(payload(), settings().field_map)
    assert document.source_key == "OR:wt.doc.WTDocument:42"
    assert document.revision_key.endswith(":A:3")
    assert document.document_number == "SOP-001"
    assert document.is_released and document.last_modified == "2026-08-19T10:00:00Z"


def test_released_filter_and_pagination() -> None:
    transport = MockTransport([
        response(200, {"items": [payload(), payload(identity="draft", lifecycle_state="In Work")], "next": "/configured/page-2"}),
        response(200, {"items": [payload(identity="OR:wt.doc.WTDocument:43", document_number="SOP-002")], "next": None}),
    ])
    documents = WindchillClient(settings(), transport).list_released_documents()
    assert [document.document_number for document in documents] == ["SOP-001", "SOP-002"]
    assert transport.calls[0][1] == {"configured_library": "library", "configured_folder": "folder"}
    assert transport.calls[1][1] is None


def test_download_content_and_http_failures() -> None:
    document = WindchillDocument.from_payload(payload(), settings().field_map)
    assert WindchillClient(settings(), MockTransport([response(200, b"%PDF-content")])).download_primary_content(document) == b"%PDF-content"
    with pytest.raises(WindchillAuthenticationError):
        WindchillClient(settings(), MockTransport([response(401, {})])).list_released_documents()
    with pytest.raises(WindchillApiError):
        WindchillClient(settings(), MockTransport([response(500, {})])).list_released_documents()


def test_malformed_responses_and_missing_configuration() -> None:
    with pytest.raises(WindchillMalformedResponseError):
        WindchillClient(settings(), MockTransport([response(200, {"items": [payload(version="")]})])).list_released_documents()
    with pytest.raises(WindchillMalformedResponseError):
        WindchillClient(settings(), MockTransport([response(200, {"value": []})])).list_released_documents()
    with pytest.raises(WindchillConfigurationError):
        WindchillClient(replace(settings(), documents_path=None), MockTransport([])).list_released_documents()
    with pytest.raises(WindchillConfigurationError):
        WindchillClient(replace(settings(), library_parameter_name=None), MockTransport([])).list_released_documents()


def test_duplicate_change_and_unchanged_detection() -> None:
    original = WindchillDocument.from_payload(payload(), settings().field_map)
    state = WindchillSyncState.from_document(original, b"content")
    assert not state.has_changed(WindchillSyncState.from_document(original, b"content"))
    changed = WindchillDocument.from_payload(payload(iteration="4", last_modified="2026-08-20T10:00:00Z"), settings().field_map)
    assert WindchillSyncState.from_document(changed, b"new-content").has_changed(state)
    transport = MockTransport([response(200, {"items": [payload(), payload()], "next": None})])
    assert len(WindchillClient(settings(), transport).list_released_documents()) == 1
    conflicting = MockTransport([response(200, {"items": [payload(), payload(iteration="4")], "next": None})])
    with pytest.raises(WindchillDuplicateDocumentError):
        WindchillClient(settings(), conflicting).list_released_documents()
