"""Small, dependency-free client for the Zenodo REST API (records + deposit API).

The personal access token is read from ZENODO_TOKEN or the macOS Keychain
(service `zenodo-token`, account `production` or `sandbox`). It is never logged or returned.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

KEYCHAIN_SERVICE = "zenodo-token"
PRODUCTION_URL = "https://zenodo.org"
SANDBOX_URL = "https://sandbox.zenodo.org"
USER_AGENT = "zenodo-mcp/0.1 (+https://github.com/mihirkavi/zenodo-mcp)"
TIMEOUT = 60


class ZenodoError(Exception):
    pass


class MissingToken(ZenodoError):
    pass


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def is_sandbox() -> bool:
    return _truthy(os.environ.get("ZENODO_SANDBOX"))


def base_url() -> str:
    custom = os.environ.get("ZENODO_BASE_URL", "").strip().rstrip("/")
    if custom and not custom.startswith("${"):
        return custom
    return SANDBOX_URL if is_sandbox() else PRODUCTION_URL


def keychain_account() -> str:
    return "sandbox" if is_sandbox() else "production"


# --------------------------------------------------------------------------- token storage

def read_token(required: bool = True) -> str | None:
    env = os.environ.get("ZENODO_TOKEN", "").strip()
    if env and not env.startswith("${"):  # unset host placeholders can arrive literally
        return env
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                            "-a", keychain_account(), "-w"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    if required:
        raise MissingToken("No Zenodo token found. Run `scripts/zenodo-setup-token` (stores it in the macOS "
                           "Keychain) or set ZENODO_TOKEN in the MCP server's environment.")
    return None


def store_token(token: str) -> None:
    """Save the token in the login Keychain. It goes to `security -i` on stdin, so it never appears in
    the process list, shell history or a file."""
    token = token.strip()
    if not token or any(c.isspace() or c == '"' for c in token):
        raise ZenodoError("That doesn't look like a Zenodo personal access token.")
    cmd = (f'add-generic-password -U -s {KEYCHAIN_SERVICE} -a {keychain_account()} '
           f'-l "Zenodo personal access token" -j "Used by zenodo-mcp" -w {token}\n')
    r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0 or "error" in (r.stderr or "").lower():
        raise ZenodoError("Could not save the token to the Keychain.")


def delete_token() -> bool:
    r = subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", keychain_account()],
                       capture_output=True, text=True, timeout=10)
    return r.returncode == 0


def token_status() -> dict:
    t = read_token(required=False)
    if not t:
        return {"stored": False}
    env = os.environ.get("ZENODO_TOKEN", "").strip()
    return {"stored": True, "source": "environment" if env and not env.startswith("${") else "keychain",
            "fingerprint": "…" + t[-4:]}


# --------------------------------------------------------------------------- HTTP

class ZenodoClient:
    def __init__(self, token: str | None = None, base: str | None = None):
        self._token = token
        self.base = (base or base_url()).rstrip("/")

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = read_token()
        return self._token  # type: ignore[return-value]

    def _request(self, method: str, url: str, *, params: dict | None = None, body: Any = None,
                 data: Any = None, headers: dict | None = None, auth: bool = True,
                 content_length: int | None = None) -> Any:
        if not url.startswith("http"):
            url = self.base + url
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, "", [])}
            if clean:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
        h = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if auth:
            h["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if content_length is not None:
            h["Content-Length"] = str(content_length)
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT if content_length is None else 3600) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise ZenodoError(_http_error(e)) from None
        except urllib.error.URLError as e:
            raise ZenodoError(f"Network error reaching Zenodo: {e.reason}") from None
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {"raw": raw.decode(errors="replace")[:2000]}

    # ---- published records (public; token optional but sent if present for higher rate limits)
    def search_records(self, **params) -> dict:
        return self._request("GET", "/api/records", params=params, auth=bool(read_token(required=False)))

    def get_record(self, record_id: str) -> dict:
        return self._request("GET", f"/api/records/{record_id}", auth=bool(read_token(required=False)))

    def search_communities(self, **params) -> dict:
        return self._request("GET", "/api/communities", params=params, auth=False)

    def search_licenses(self, **params) -> dict:
        return self._request("GET", "/api/vocabularies/licenses", params=params, auth=False)

    # ---- deposit API (the user's own uploads)
    def list_depositions(self, **params) -> list:
        return self._request("GET", "/api/deposit/depositions", params=params)

    def get_deposition(self, dep_id: int) -> dict:
        return self._request("GET", f"/api/deposit/depositions/{int(dep_id)}")

    def create_deposition(self, metadata: dict | None = None) -> dict:
        return self._request("POST", "/api/deposit/depositions", body={"metadata": metadata} if metadata else {})

    def update_deposition(self, dep_id: int, metadata: dict) -> dict:
        return self._request("PUT", f"/api/deposit/depositions/{int(dep_id)}", body={"metadata": metadata})

    def delete_deposition(self, dep_id: int) -> dict:
        return self._request("DELETE", f"/api/deposit/depositions/{int(dep_id)}")

    def action(self, dep_id: int, name: str) -> dict:
        assert name in ("publish", "edit", "discard", "newversion")
        return self._request("POST", f"/api/deposit/depositions/{int(dep_id)}/actions/{name}")

    def list_files(self, dep_id: int) -> list:
        return self._request("GET", f"/api/deposit/depositions/{int(dep_id)}/files")

    def delete_file(self, dep_id: int, file_id: str) -> dict:
        return self._request("DELETE", f"/api/deposit/depositions/{int(dep_id)}/files/{file_id}")

    def upload_file(self, bucket_url: str, path: Path, filename: str) -> dict:
        size = path.stat().st_size
        with path.open("rb") as fh:
            return self._request("PUT", f"{bucket_url}/{urllib.parse.quote(filename)}", data=fh,
                                 headers={"Content-Type": "application/octet-stream"}  # bucket API rejects others, content_length=size)


def _http_error(e: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(e.read() or b"{}")
    except ValueError:
        payload = {}
    msg = payload.get("message") or e.reason
    details = payload.get("errors")
    hint = {401: " Check the token (run zenodo_status).",
            403: " The token may lack the deposit:write / deposit:actions scopes, or the record isn't yours.",
            404: " Not found — check the id (draft ids and record ids differ after new versions).",
            429: " Rate limited by Zenodo; wait a minute and retry."}.get(e.code, "")
    out = f"Zenodo HTTP {e.code}: {msg}.{hint}"
    if details:
        out += " Details: " + json.dumps(details)[:800]
    return out


# --------------------------------------------------------------------------- shaping helpers

def creator(c: Any) -> dict:
    """Accept 'Last, First' strings or dicts with name/affiliation/orcid/gnd."""
    if isinstance(c, str):
        return {"name": c.strip()}
    if not isinstance(c, dict) or not c.get("name"):
        raise ZenodoError("Each creator needs a name, e.g. {'name': 'Doe, Jane', 'affiliation': 'MIT', "
                          "'orcid': '0000-0002-1825-0097'}")
    return {k: str(v).strip() for k, v in c.items() if k in ("name", "affiliation", "orcid", "gnd") and v}


def build_metadata(*, title: str | None = None, creators: list | None = None, description: str | None = None,
                   upload_type: str | None = None, publication_type: str | None = None,
                   publication_date: str | None = None, keywords: list | None = None,
                   license: str | None = None, access_right: str | None = None,
                   communities: list | None = None, related_identifiers: list | None = None,
                   version: str | None = None, language: str | None = None, notes: str | None = None,
                   doi: str | None = None, prereserve_doi: bool | None = None,
                   extra: dict | None = None) -> dict:
    md: dict[str, Any] = {}
    if title is not None:
        md["title"] = title
    if creators is not None:
        md["creators"] = [creator(c) for c in creators]
    if description is not None:
        md["description"] = description
    if upload_type is not None:
        md["upload_type"] = upload_type
    if publication_type is not None:
        md["publication_type"] = publication_type
    if publication_date is not None:
        md["publication_date"] = publication_date
    if keywords is not None:
        md["keywords"] = [k for k in (str(x).strip() for x in keywords) if k]
    if license is not None:
        md["license"] = license
    if access_right is not None:
        md["access_right"] = access_right
    if communities is not None:
        md["communities"] = [{"identifier": c} if isinstance(c, str) else c for c in communities]
    if related_identifiers is not None:
        md["related_identifiers"] = related_identifiers
    if version is not None:
        md["version"] = version
    if language is not None:
        md["language"] = language
    if notes is not None:
        md["notes"] = notes
    if doi is not None:
        md["doi"] = doi
    if prereserve_doi is not None:
        md["prereserve_doi"] = prereserve_doi
    if extra:
        md.update(extra)
    return md


def summarize_deposition(d: dict) -> dict:
    md = d.get("metadata", {}) or {}
    links = d.get("links", {}) or {}
    return {
        "id": d.get("id"),
        "record_id": d.get("record_id"),
        "conceptrecid": d.get("conceptrecid"),
        "state": d.get("state"),
        "submitted": d.get("submitted"),
        "title": md.get("title") or d.get("title"),
        "upload_type": md.get("upload_type"),
        "publication_type": md.get("publication_type"),
        "publication_date": md.get("publication_date"),
        "creators": [c.get("name") for c in md.get("creators", [])],
        "doi": d.get("doi") or md.get("doi") or (md.get("prereserve_doi") or {}).get("doi"),
        "doi_status": "registered" if d.get("doi") else ("reserved" if (md.get("prereserve_doi") or {}).get("doi")
                                                          else "none"),
        "license": md.get("license"),
        "access_right": md.get("access_right"),
        "version": md.get("version"),
        "files": [{"id": f.get("id"), "filename": f.get("filename"), "size": f.get("filesize"),
                   "checksum": f.get("checksum")} for f in d.get("files", [])],
        "links": {k: links.get(k) for k in ("html", "latest_draft_html", "record_html", "doi", "latest_html")
                  if links.get(k)},
    }


def summarize_record(r: dict) -> dict:
    md = r.get("metadata", {}) or {}
    rt = md.get("resource_type") or {}
    desc = md.get("description") or ""
    return {
        "id": r.get("id"),
        "doi": r.get("doi") or md.get("doi"),
        "title": md.get("title") or r.get("title"),
        "creators": [c.get("name") for c in md.get("creators", [])],
        "publication_date": md.get("publication_date"),
        "resource_type": rt.get("title") or rt.get("type"),
        "subtype": rt.get("subtype"),
        "version": md.get("version"),
        "keywords": md.get("keywords"),
        "license": (md.get("license") or {}).get("id") if isinstance(md.get("license"), dict) else md.get("license"),
        "access_right": md.get("access_right"),
        "description_excerpt": _strip_html(desc)[:500],
        "stats": {k: (r.get("stats") or {}).get(k) for k in ("downloads", "views", "unique_downloads", "unique_views")
                  if (r.get("stats") or {}).get(k) is not None},
        "url": (r.get("links") or {}).get("self_html") or (r.get("links") or {}).get("html"),
    }


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()
