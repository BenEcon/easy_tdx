#!/usr/bin/env bash
set -euo pipefail
release=/home/opc/apps/easy_tdx-release-20261009-platform
previous=/home/opc/apps/easy_tdx-release-20261009-research
backup=/home/opc/backups/tdx-20261009-platform
expected=sha256:83fde4353a5c84db8ddf9902f9bbc48289afdfc91ac1918bb9bbda6d891d5461
next_image=sha256:1c3afdeee600f50c019a3f1352e506476c3ca16e5d78a2ecd567de6f4b8a9f60
test "$(sudo docker inspect easy-tdx --format '{{.Image}}')" = "$expected"
test "$(sudo docker image inspect easy-tdx:research-20261009 --format '{{.Id}}')" = "$expected"
test "$(sudo docker image inspect easy-tdx:platform-20261009 --format '{{.Id}}')" = "$next_image"
test "$(sudo docker inspect easy-tdx --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = easy_tdx_data
test "$(sudo docker inspect easy-tdx --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')" = 172.22.0.1
test ! -e "$backup"
cp "$previous/compose.yaml" "$release/compose.yaml"
sudo docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" config --quiet
mkdir -m 700 "$backup"
cp "$previous/compose.yaml" "$previous/release-image.yaml" "$backup/"
sudo cp /www/server/panel/vhost/nginx/tdx.bowenv.com.conf "$backup/nginx.conf"
rollback() {
  echo 'Restoring previous application image (data retained).' >&2
  sudo docker compose -p easy_tdx -f "$previous/compose.yaml" -f "$previous/release-image.yaml" up -d --no-build --pull never easy-tdx
}
trap 'rollback' ERR
sudo docker stop --time 30 easy-tdx
sudo tar -czf "$backup/data.tar.gz" -C /var/lib/docker/volumes/easy_tdx_data/_data .
sudo chmod 600 "$backup/data.tar.gz"
sudo tar -tzf "$backup/data.tar.gz" >/dev/null
sudo sha256sum "$backup/data.tar.gz"
sudo docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" up -d --no-build --pull never easy-tdx
for attempt in {1..24}; do
  health=$(sudo docker inspect easy-tdx --format '{{.State.Health.Status}}')
  if [ "$health" = healthy ]; then
    curl --fail --silent http://127.0.0.1:18002/api/v1/auth/status
    test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18002/api/v1/bars?code=300750)" = 401
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
