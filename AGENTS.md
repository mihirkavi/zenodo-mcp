# Agent guide: zenodo-mcp

- Never read, print, log or commit the Zenodo token. It lives only in the macOS Keychain (service `zenodo-token`) or `ZENODO_TOKEN`. Users set it with `scripts/zenodo-setup-token`; never ask for it in chat.
- Publishing is irreversible (it mints a DOI). Keep `zenodo_publish`, `zenodo_delete_draft`, `zenodo_delete_file` and `zenodo_discard_changes` preview-first behind `confirm=true`. Don't add bypasses.
- Test destructive flows with `ZENODO_SANDBOX=1` (sandbox.zenodo.org), never against production records.
- Never commit papers, PDFs or personal data. Tests use fake data only.
- Run the offline tests before committing: `uv run --with mcp==2.3.0 python -m unittest discover -s tests`.
- Layout: `server/zenodo_client.py` (HTTP, Keychain, shaping), `server/zenodo_mcp.py` (tools), `scripts/zenodo-setup-token`.
