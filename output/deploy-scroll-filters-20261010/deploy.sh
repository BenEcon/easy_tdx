#!/usr/bin/env bash
set -euo pipefail
release=/home/opc/apps/easy_tdx-release-20261010-scroll-filters
previous=/home/opc/apps/easy_tdx-release-20261010-tracking-history-signals
backup=/home/opc/backups/tdx-20261010-scroll-filters
expected=sha256:936c3f3a821773aba7162c02c95b6e7d223e93e2d69001d0446dda99ac29094e
test "$(sudo -n docker inspect easy-tdx --format '{{.Image}}')" = "$expected"
test "$(sudo -n docker image inspect easy-tdx:tracking-history-signals-20261010 --format '{{.Id}}')" = "$expected"
test "$(sha256sum "$previous/compose.yaml" | cut -d' ' -f1)" = f948b0eb33797caa5dd6de9bf419f8db47d6d0eaf2b035832808ef1efcd2cb6f
test "$(sudo -n docker inspect easy-tdx --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = easy_tdx_data
test "$(sudo -n docker inspect easy-tdx --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')" = 172.22.0.1
test ! -e "$backup"
cd "$release"
sudo -n docker build --pull=false -t easy-tdx:scroll-filters-20261010 .
if sudo -n docker inspect easy-tdx-scroll-filters-smoke >/dev/null 2>&1; then exit 1; fi
sudo -n docker run -d --name easy-tdx-scroll-filters-smoke --network none --tmpfs /data:rw,uid=10001,gid=10001 easy-tdx:scroll-filters-20261010
cleanup_smoke(){ sudo -n docker rm -f easy-tdx-scroll-filters-smoke >/dev/null; }
trap cleanup_smoke EXIT
ready=false
for attempt in {1..24}; do
  if sudo -n docker exec easy-tdx-scroll-filters-smoke python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/auth/status', timeout=3)" >/dev/null 2>&1; then ready=true; break; fi
  sleep 2
done
test "$ready" = true
sudo -n docker exec -i easy-tdx-scroll-filters-smoke python - <<'PY'
import re, urllib.request
base='http://127.0.0.1:8000'
html=urllib.request.urlopen(base+'/tracking').read().decode()
asset=re.search(r'src="([^"]+/index-[^"]+\.js)"',html).group(1)
js=urllib.request.urlopen(base+asset).read().decode()
assert 'TrackingView-' in js and 'QuantResearchView-' in js
for path in ['/opt/easy_tdx/web-ui/dist','/usr/local/lib/python3.12/site-packages/easy_tdx/web/dist']:
 from pathlib import Path
 content='\n'.join(p.read_text() for p in Path(path).glob('assets/TrackingView-*.js'))
 assert '可多选' in content and '独立上下及左右滚动' in content
print('Isolated candidate HTTP/static checks passed; no production data mounted.')
PY
cleanup_smoke
trap - EXIT
cp "$previous/compose.yaml" "$release/compose.yaml"
sudo -n docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" config --quiet
mkdir -m 700 "$backup"
cp "$previous/compose.yaml" "$previous/release-image.yaml" "$backup/"
sudo -n docker inspect easy-tdx --format '{{.Image}}' > "$backup/previous-image.txt"
rollback(){ sudo -n docker compose -p easy_tdx -f "$previous/compose.yaml" -f "$previous/release-image.yaml" up -d --no-build --pull never easy-tdx; }
trap rollback ERR
sudo -n docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" up -d --no-build --pull never easy-tdx
for attempt in {1..24}; do
  if [ "$(sudo -n docker inspect easy-tdx --format '{{.State.Health.Status}}')" = healthy ]; then
    curl --fail --silent http://127.0.0.1:18002/api/v1/auth/status
    test "$(curl -sS -o /dev/null -w '%{http_code}' -H 'Origin: https://tdx.bowenv.com' -H 'Content-Type: application/json' -d '{}' https://tdx.bowenv.com/api/v1/research/factors/compute)" = 401
    test "$(curl -sS -o /dev/null -w '%{http_code}' -H 'Origin: https://untrusted.invalid' -H 'Content-Type: application/json' -d '{}' https://tdx.bowenv.com/api/v1/research/factors/compute)" = 403
    sudo -n docker inspect easy-tdx --format '{{.Config.Image}} {{.Image}} {{.State.Status}} {{.State.Health.Status}}'
    trap - ERR
    exit 0
  fi
  sleep 3
done
rollback
trap - ERR
exit 1
