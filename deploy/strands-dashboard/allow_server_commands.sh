#!/usr/bin/env bash
# Run on the server as pancds. Lets Claude's Remote Control session run ordinary
# commands without prompting; deletes, wipes, reboots, force-pushes and firewall
# changes still ask. Backs up the old settings first.
set -e
F=~/.claude/settings.json
mkdir -p ~/.claude; [ -f "$F" ] || echo '{}' > "$F"
cp "$F" "$F.bak-2026-11-22"
python3 - "$F" <<'PY'
import json, sys
f = sys.argv[1]; s = json.load(open(f))
p = s.setdefault("permissions", {})
allow = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebFetch"]
ask = ["Bash(rm:*)", "Bash(sudo rm:*)", "Bash(rmdir:*)", "Bash(sudo rmdir:*)", "Bash(shred:*)",
 "Bash(unlink:*)", "Bash(dd:*)", "Bash(sudo dd:*)", "Bash(mkfs:*)", "Bash(sudo mkfs:*)",
 "Bash(sudo fdisk:*)", "Bash(sudo parted:*)", "Bash(sudo reboot:*)", "Bash(sudo shutdown:*)",
 "Bash(sudo poweroff:*)", "Bash(sudo apt remove:*)", "Bash(sudo apt purge:*)", "Bash(sudo apt autoremove:*)",
 "Bash(docker rm:*)", "Bash(docker rmi:*)", "Bash(docker volume rm:*)", "Bash(docker system prune:*)",
 "Bash(sudo docker rm:*)", "Bash(sudo docker system prune:*)", "Bash(git push --force:*)",
 "Bash(git reset --hard:*)", "Bash(git clean:*)", "Bash(sudo userdel:*)", "Bash(sudo chmod -R:*)",
 "Bash(sudo chown -R:*)", "Bash(sudo ufw:*)", "Bash(sudo iptables:*)"]
for k, v in (("allow", allow), ("ask", ask)):
    cur = p.setdefault(k, [])
    cur += [x for x in v if x not in cur]
json.dump(s, open(f, "w"), indent=2)
print("Updated", f)
PY
