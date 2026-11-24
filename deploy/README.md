# Deployment: Austin's Zotero MCP server

This folder holds the files that run zotero-mcp as a remote MCP server for
ChatGPT/Codex and Claude. No secrets live here.

| File | Lives on the server at | Purpose |
|---|---|---|
| `serve_zotero_oauth.py` | `/opt/zotero-mcp/serve_zotero_oauth.py` | Wraps `zotero-mcp serve` in GitHub OAuth; only logins in `ZMCP_ALLOWED_GITHUB_LOGINS` get in. Fails closed. |
| `zotero-mcp.env.example` | `/opt/zotero-mcp/zotero-mcp.env` (mode 600, owner `zoteromcp`) | Template. Fill in on the server only. |
| `zotero-mcp.service` | `/etc/systemd/system/zotero-mcp.service` | systemd unit, listens on 127.0.0.1:8765. |

Public URL: `https://zotero-mcp.austin-unowitz.com/mcp`, through a dedicated
Cloudflare tunnel (`/opt/zotero-mcp/tunnel/docker-compose.yml`; its token is in
a root-only `tunnel.env` that is never committed).

Mode: Zotero **web API** (`ZOTERO_LOCAL=false`). PDFs come from Zotero cloud
file storage, so page-level reading works for any item whose PDF has synced.

## Update the server from this repo

```bash
sudo -u zoteromcp /opt/zotero-mcp/venv/bin/pip install --upgrade "git+https://github.com/poststructural/zotero-mcp.git@main"
sudo install -o zoteromcp -g zoteromcp -m 644 deploy/serve_zotero_oauth.py /opt/zotero-mcp/
sudo systemctl restart zotero-mcp && systemctl status zotero-mcp --no-pager
```

(A private repo needs a deploy key or token on the server for the pip step.)

## Undo / stop

```bash
sudo systemctl disable --now zotero-mcp
sudo docker compose -f /opt/zotero-mcp/tunnel/docker-compose.yml down
```

## Provenance log (opt-in, phase 1)

The `provenance` toolset is off by default. To enable it on the server, add to
`/opt/zotero-mcp/zotero-mcp.env`:

```bash
ZOTERO_MCP_TOOLSETS=default,provenance   # `all` does not include it; name it
ZOTERO_MCP_PROVENANCE_DB=/opt/zotero-mcp/data/provenance.db
ZOTERO_MCP_LIBRARY=uconn                  # "open via UConn" links in discover_access
ZOTERO_MCP_CONTACT_EMAIL=                 # optional; contact address for OpenAlex's polite pool
CORE_API_KEY=                             # optional; free key from core.ac.uk/services/api
```

then `sudo install -d -o zoteromcp -g zoteromcp -m 700 /opt/zotero-mcp/data` and
restart. The tools write only to that SQLite file, never to Zotero. Back it up
with the rest of `/opt/zotero-mcp/data`.
