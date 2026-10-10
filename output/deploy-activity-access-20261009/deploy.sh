#!/usr/bin/env bash
set -euo pipefail
release=/home/opc/apps/easy_tdx-release-20261009-activity-access
previous=/home/opc/apps/easy_tdx-release-20261009-period-evidence
backup=/home/opc/backups/tdx-20261009-activity-access
nginx=/www/server/panel/vhost/nginx/tdx.bowenv.com.conf
expected=sha256:2532172e84c5b6be17cc713eeb6f077ec378eda3c6de447288a2ed868c5c73c0
test "$(sudo docker inspect easy-tdx --format '{{.Image}}')" = "$expected"
test "$(sudo docker image inspect easy-tdx:period-evidence-20261009 --format '{{.Id}}')" = "$expected"
test "$(sudo docker inspect easy-tdx --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = easy_tdx_data
test "$(sudo docker inspect easy-tdx --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')" = 172.22.0.1
test "$(cat "$release/smoke-passed")" = "$(sudo docker image inspect easy-tdx:activity-access-20261009 --format '{{.Id}}')"
test ! -e "$backup"
cp "$previous/compose.yaml" "$release/compose.yaml"
sudo docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" config --quiet
mkdir -m 700 "$backup"
cp "$previous/compose.yaml" "$previous/release-image.yaml" "$backup/"
sudo cp "$nginx" "$backup/nginx.conf"
rollback() {
  echo 'Restoring previous application and proxy configuration; retaining current data.' >&2
  sudo cp "$backup/nginx.conf" "$nginx"
  sudo /www/server/nginx/sbin/nginx -t && sudo /www/server/nginx/sbin/nginx -s reload
  sudo docker compose -p easy_tdx -f "$previous/compose.yaml" -f "$previous/release-image.yaml" up -d --no-build --pull never easy-tdx
}
trap rollback ERR
sudo docker stop --time 30 easy-tdx
sudo tar -czf "$backup/data.tar.gz" -C /var/lib/docker/volumes/easy_tdx_data/_data .
sudo chmod 600 "$backup/data.tar.gz"
sudo tar -tzf "$backup/data.tar.gz" >/dev/null
sudo sha256sum "$backup/data.tar.gz"
# Nginx must admit the app's bounded 26 MiB archive envelope. Other API routes
# retain their smaller application limits and archive uploads require auth.
sudo python3 - "$nginx" <<'PY'
import pathlib,sys
path=pathlib.Path(sys.argv[1]); old=path.read_text()
assert old.count('client_max_body_size 10m;') == 1, 'unexpected proxy config'
path.write_text(old.replace('client_max_body_size 10m;', 'client_max_body_size 26m;'))
PY
sudo /www/server/nginx/sbin/nginx -t
sudo /www/server/nginx/sbin/nginx -s reload
sudo docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" up -d --no-build --pull never easy-tdx
for attempt in {1..24}; do
  health=$(sudo docker inspect easy-tdx --format '{{.State.Health.Status}}')
  if [ "$health" = healthy ]; then
    curl --fail --silent http://127.0.0.1:18002/api/v1/auth/status
    for path in bars?code=300750 admin/activity/events admin/activity/summary research/archives; do
      test "$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:18002/api/v1/$path")" = 401
    done
    test "$(curl --silent --output /dev/null --write-out '%{http_code}' -H 'Origin: https://untrusted.invalid' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:18002/api/v1/auth/login)" = 403
    sudo docker inspect easy-tdx --format '{{.Config.Image}} {{.Image}} {{.State.Status}} {{.State.Health.Status}}'
    trap - ERR
    exit 0
  fi
  sleep 5
done
echo 'Health check failed.' >&2
rollback
trap - ERR
exit 1
