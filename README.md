# zenodo-mcp

An MCP server that lets Claude, Codex and other MCP clients work with [Zenodo](https://zenodo.org). It can search research papers and preprints, then draft, upload and publish your own preprints with a DOI, all from chat.

Publishing to Zenodo is permanent. This server never publishes or deletes anything until you have seen a preview and approved that exact action.

## What it does

| Tool | Purpose |
|---|---|
| `zenodo_status` | Shows the instance (production or sandbox) and whether the token works |
| `zenodo_search_records` | Searches published records (Elasticsearch syntax), with filters for preprints, communities and sort order |
| `zenodo_get_record` | Gets one record's metadata, files and download links |
| `zenodo_search_communities` / `zenodo_search_licenses` | Look up community slugs and license ids |
| `zenodo_list_my_uploads` / `zenodo_get_upload` | List and inspect your own drafts and published uploads |
| `zenodo_create_preprint_draft` | Creates a private draft (by default upload type `publication` and subtype `preprint`) and reserves its DOI |
| `zenodo_update_metadata` | Changes only the fields you pass; `extra` covers any other deposit field |
| `zenodo_upload_file` | Uploads a local file, such as the PDF, to a draft |
| `zenodo_delete_file` | Removes a file from a draft (preview first, then `confirm=true`) |
| `zenodo_publish` | Publishes and registers the DOI (preview and checklist first, then `confirm=true`) |
| `zenodo_edit_published` / `zenodo_discard_changes` | Correct the metadata of a published record |
| `zenodo_new_version` | Starts a new version of a published preprint, which gets its own DOI |
| `zenodo_delete_draft` | Deletes an unpublished draft (preview first, then `confirm=true`) |

Typical flow: create the draft, upload the PDF, review it with `zenodo_get_upload`, then call `zenodo_publish` to see the preview and publish once you approve.

## Setup

Requirements: macOS (the token is stored in the Keychain) or any OS with `ZENODO_TOKEN` set, plus [uv](https://docs.astral.sh/uv/). uv installs the Python dependency (`mcp`) automatically.

1. Create a token at <https://zenodo.org/account/settings/applications/tokens/new/> with the scopes **deposit:write** and **deposit:actions**.
2. Store it:
   ```sh
   git clone https://github.com/mihirkavi/zenodo-mcp && cd zenodo-mcp
   scripts/zenodo-setup-token          # hidden prompt, saves to the macOS Keychain, verifies the token
   scripts/zenodo-setup-token --status # check it later
   ```
3. Register the server.
   - Claude Code:
     ```sh
     claude mcp add --scope user zenodo -- uv run --quiet --script "$PWD/server/zenodo_mcp.py"
     ```
   - Codex (`~/.codex/config.toml`):
     ```toml
     [mcp_servers.zenodo]
     command = "uv"
     args = ["run", "--quiet", "--script", "/absolute/path/to/zenodo-mcp/server/zenodo_mcp.py"]
     ```
   - Other clients: use the same command. Without the Keychain, pass the token as the `ZENODO_TOKEN` environment variable.

### Sandbox for testing

Set `ZENODO_SANDBOX=1` to use <https://sandbox.zenodo.org>. Sandbox DOIs are not real, and the sandbox needs its own account and token (`ZENODO_SANDBOX=1 scripts/zenodo-setup-token`). `ZENODO_BASE_URL` points the server at any other InvenioRDM/Zenodo instance.

## Security

- The token is read from `ZENODO_TOKEN` or the Keychain (service `zenodo-token`, account `production` or `sandbox`). It is never returned by a tool or logged, and only its last 4 characters are ever shown.
- Publishing, deleting a draft or file, and discarding edits are all preview-first. They need a second call with `confirm=true`.
- Text from Zenodo records is treated as untrusted data.

## Development

```sh
uv run --with mcp==2.3.0 python -m unittest discover -s tests   # offline tests, no token needed
```

## Status and limitations

- Version 0.1. Searching, drafts, file upload, publishing and new versions use Zenodo's legacy deposit API (`/api/deposit/depositions`), which Zenodo still supports. Search uses `/api/records`.
- Search, communities and licenses were tested against live Zenodo. The deposit tools work with a real token but have no automated tests against the live service; to try them, use the sandbox first.
- Not yet supported: community review requests through the newer InvenioRDM requests API, restricted-file access grants, and uploads over the 50 GB per-record limit.

## License

MIT
