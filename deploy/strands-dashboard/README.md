# Strands dashboard on the Ubuntu server (2026-11-22)

- Code: `_dashboard/` here = GPT add-on versions + server mode. With no env vars set it runs exactly as on the PC.
- Server mode env: DASH_SERVER=1, DASH_PORT=8770, DASH_BIND=127.0.0.1, DASH_HOSTS=dashboard.austin-unowitz.com.
  In server mode the "Open in Word" button downloads a copy (/file, token-checked) instead of launching Word.
- Data: the Strands folder syncs PC <-> server (/home/pancds/Strands) with Syncthing; `stignore.txt` is the .stignore.
  Word's `~$` lock files are deliberately synced, so the server refuses to write while a strand is open in Word on the PC.
- Service: `strands-dashboard.service` (runs as pancds so it uses pancds's Codex login).
- Public: Cloudflare tunnel public hostname dashboard.austin-unowitz.com -> http://127.0.0.1:8770, behind a Cloudflare Access app.
