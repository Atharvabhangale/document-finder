"""Isolated, configuration-driven boundary for a future Windchill WRS source.

No Windchill endpoint shape is assumed here.  A deployment must supply the
verified collection and content paths, plus any response-field mapping required
by its Windchill 12.0.2.19 WRS configuration.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from urllib.parse import urljoin
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class WindchillError(RuntimeError):
    """Base error for the isolated Windchill source boundary."""


class WindchillConfigurationError(WindchillError):
    """Required future integration configuration is absent or invalid."""


class WindchillAuthenticationError(WindchillError):
    """The configured service account was rejected."""


class WindchillApiError(WindchillError):
    """The remote service or network failed."""


class WindchillMalformedResponseError(WindchillError):
    """A response does not match the configured source contract."""


class WindchillDuplicateDocumentError(WindchillError):
    """One stable identity appeared with conflicting source state."""


@dataclass(frozen=True)
class WindchillFieldMap:
    """Names in the adapter's *configured response contract*, not WRS claims."""

    identity: str = "identity"
    document_number: str = "document_number"
    filename: str = "filename"
    version: str = "version"
    iteration: str = "iteration"
    lifecycle_state: str = "lifecycle_state"
    last_modified: str = "last_modified"
    content_url: str = "content_url"


@dataclass(frozen=True)
class WindchillSettings:
    base_url: str | None
    username: str | None
    password: str | None
    library_id: str | None
    folder_id: str | None
    documents_path: str | None = None
    content_path_template: str | None = None
    library_parameter_name: str | None = None
    folder_parameter_name: str | None = None
    field_map: WindchillFieldMap = field(default_factory=WindchillFieldMap)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "WindchillSettings":
        env = os.environ if environ is None else environ
        return cls(
            base_url=env.get("WINDCHILL_BASE_URL"),
            username=env.get("WINDCHILL_USERNAME"),
            password=env.get("WINDCHILL_PASSWORD"),
            library_id=env.get("WINDCHILL_LIBRARY_ID"),
            folder_id=env.get("WINDCHILL_FOLDER_ID"),
            documents_path=env.get("WINDCHILL_DOCUMENTS_PATH"),
            content_path_template=env.get("WINDCHILL_CONTENT_PATH_TEMPLATE"),
            library_parameter_name=env.get("WINDCHILL_LIBRARY_PARAMETER"),
            folder_parameter_name=env.get("WINDCHILL_FOLDER_PARAMETER"),
        )

    def require_listing_configuration(self) -> None:
        missing = [name for name, value in {
            "WINDCHILL_BASE_URL": self.base_url,
            "WINDCHILL_USERNAME": self.username,
            "WINDCHILL_PASSWORD": self.password,
            "WINDCHILL_DOCUMENTS_PATH": self.documents_path,
        }.items() if not value]
        if missing:
            raise WindchillConfigurationError("Missing Windchill configuration: " + ", ".join(missing))
        if self.library_id and not self.library_parameter_name:
            raise WindchillConfigurationError("WINDCHILL_LIBRARY_PARAMETER is required when WINDCHILL_LIBRARY_ID is set.")
        if self.folder_id and not self.folder_parameter_name:
            raise WindchillConfigurationError("WINDCHILL_FOLDER_PARAMETER is required when WINDCHILL_FOLDER_ID is set.")


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WindchillMalformedResponseError("Windchill response was not valid JSON.") from error


class HttpTransport(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str] | None = None) -> HttpResponse: ...


class UrllibTransport:
    """Standard-library transport. It performs no request until client methods are called."""

    def get(self, url: str, *, headers: Mapping[str, str], params: Mapping[str, str] | None = None) -> HttpResponse:
        if params:
            from urllib.parse import urlencode
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=30) as response:  # nosec B310: URL is administrator-configured.
                return HttpResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            return HttpResponse(error.code, dict(error.headers.items()) if error.headers else {}, error.read())
        except Exception as error:
            raise WindchillApiError(f"Windchill request failed: {error}") from error


@dataclass(frozen=True)
class WindchillDocument:
    """Normalized metadata for one WTDocument revision/iteration."""

    identity: str
    document_number: str
    filename: str
    version: str
    iteration: str
    lifecycle_state: str
    last_modified: str
    content_url: str | None
    raw_metadata: Mapping[str, Any]

    @property
    def is_released(self) -> bool:
        return self.lifecycle_state.strip().casefold() == "released"

    @property
    def source_key(self) -> str:
        """Stable remote identity for future document-to-local sync mapping."""
        return self.identity

    @property
    def revision_key(self) -> str:
        return f"{self.identity}:{self.version}:{self.iteration}"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], fields: WindchillFieldMap) -> "WindchillDocument":
        if not isinstance(payload, Mapping):
            raise WindchillMalformedResponseError("Windchill document entry must be an object.")

        def required(name: str) -> str:
            value = payload.get(name)
            if value is None or not str(value).strip():
                raise WindchillMalformedResponseError(f"Windchill document is missing required field '{name}'.")
            return str(value)

        content_value = payload.get(fields.content_url)
        return cls(
            identity=required(fields.identity), document_number=required(fields.document_number),
            filename=required(fields.filename), version=required(fields.version), iteration=required(fields.iteration),
            lifecycle_state=required(fields.lifecycle_state), last_modified=required(fields.last_modified),
            content_url=str(content_value) if content_value else None, raw_metadata=dict(payload),
        )


@dataclass(frozen=True)
class WindchillSyncState:
    """Minimal persisted comparison state a future synchronizer can store."""

    identity: str
    version: str
    iteration: str
    lifecycle_state: str
    last_modified: str
    content_sha256: str | None = None

    @classmethod
    def from_document(cls, document: WindchillDocument, content: bytes | None = None) -> "WindchillSyncState":
        return cls(
            identity=document.identity, version=document.version, iteration=document.iteration,
            lifecycle_state=document.lifecycle_state, last_modified=document.last_modified,
            content_sha256=hashlib.sha256(content).hexdigest() if content is not None else None,
        )

    def has_changed(self, previous: "WindchillSyncState | None") -> bool:
        return previous is None or self != previous


def deduplicate_documents(documents: list[WindchillDocument]) -> list[WindchillDocument]:
    """Keep exact repeated list entries; reject conflicting entries conservatively."""
    unique: dict[str, WindchillDocument] = {}
    for document in documents:
        previous = unique.get(document.identity)
        if previous is None:
            unique[document.identity] = document
        elif previous.revision_key != document.revision_key or previous.last_modified != document.last_modified:
            raise WindchillDuplicateDocumentError(
                f"Conflicting revisions for Windchill identity {document.identity!r}; sync selection needs verification."
            )
    return list(unique.values())


class WindchillClient:
    """Configurable WRS client boundary; no endpoint is assumed or contacted on construction."""

    def __init__(self, settings: WindchillSettings, transport: HttpTransport | None = None):
        self.settings = settings
        self.transport = transport or UrllibTransport()

    def _headers(self) -> dict[str, str]:
        if not self.settings.username or self.settings.password is None:
            raise WindchillConfigurationError("WINDCHILL_USERNAME and WINDCHILL_PASSWORD are required.")
        token = base64.b64encode(f"{self.settings.username}:{self.settings.password}".encode("utf-8")).decode("ascii")
        return {"Accept": "application/json", "Authorization": f"Basic {token}"}

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("https://", "http://")):
            return path_or_url
        if not self.settings.base_url:
            raise WindchillConfigurationError("WINDCHILL_BASE_URL is required.")
        return urljoin(self.settings.base_url.rstrip("/") + "/", path_or_url.lstrip("/"))

    @staticmethod
    def _check_response(response: HttpResponse) -> None:
        if response.status_code in {401, 403}:
            raise WindchillAuthenticationError(f"Windchill authentication failed ({response.status_code}).")
        if response.status_code < 200 or response.status_code >= 300:
            raise WindchillApiError(f"Windchill API returned HTTP {response.status_code}.")

    def list_released_documents(self) -> list[WindchillDocument]:
        """List all configured-source pages and retain only exact Released state documents."""
        self.settings.require_listing_configuration()
        next_url: str | None = self._url(self.settings.documents_path or "")
        params: Mapping[str, str] | None = {
            key: value for key, value in (
                (self.settings.library_parameter_name, self.settings.library_id),
                (self.settings.folder_parameter_name, self.settings.folder_id),
            ) if key and value
        }
        documents: list[WindchillDocument] = []
        while next_url:
            response = self.transport.get(next_url, headers=self._headers(), params=params)
            self._check_response(response)
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise WindchillMalformedResponseError("Windchill listing response must be an object.")
            entries = payload.get("items")
            if not isinstance(entries, list):
                raise WindchillMalformedResponseError("Windchill listing response must contain an 'items' array.")
            parsed = [WindchillDocument.from_payload(entry, self.settings.field_map) for entry in entries]
            documents.extend(document for document in parsed if document.is_released)
            next_value = payload.get("next")
            if next_value is not None and not isinstance(next_value, str):
                raise WindchillMalformedResponseError("Windchill listing 'next' value must be a URL string or null.")
            next_url = self._url(next_value) if next_value else None
            params = None  # pagination links are opaque server-provided URLs.
        return deduplicate_documents(documents)

    def download_primary_content(self, document: WindchillDocument) -> bytes:
        """Download bytes only from configured or server-supplied content references."""
        target = document.content_url
        if not target and self.settings.content_path_template:
            target = self.settings.content_path_template.format(document_identity=document.identity)
        if not target:
            raise WindchillConfigurationError(
                "No content URL was supplied and WINDCHILL_CONTENT_PATH_TEMPLATE is not configured."
            )
        response = self.transport.get(self._url(target), headers=self._headers())
        self._check_response(response)
        if not response.body:
            raise WindchillMalformedResponseError("Windchill primary-content response was empty.")
        return response.body
