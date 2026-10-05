#!/usr/bin/env bash
set -euo pipefail
release=/home/opc/apps/easy_tdx-release-20261005-research-indent
previous=/home/opc/apps/easy_tdx-release-20261005-structure-hover
backup=/home/opc/backups/tdx-20261005-research-indent
expected=sha256:6596c28473bc150838a4d1947005f471239f6871e851b68cb77ed891d7c1b09e
test "$(sudo docker inspect easy-tdx --format '{{.Image}}')" = "$expected"
test "$(sudo docker image inspect easy-tdx:structure-hover-20261005 --format '{{.Id}}')" = "$expected"
test "$(sudo docker inspect easy-tdx --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = easy_tdx_data
test ! -e "$backup"
cp "$previous/compose.yaml" "$release/compose.yaml"
sudo docker build --pull=false -t easy-tdx:research-indent-20261005 "$release"
mkdir -m 700 "$backup"
cp "$previous/compose.yaml" "$previous/release-image.yaml" "$backup/"
rollback() {
  sudo docker compose -p easy_tdx -f "$previous/compose.yaml" -f "$previous/release-image.yaml" up -d --no-build --pull never easy-tdx
}
trap 'rollback' ERR
sudo docker stop easy-tdx
sudo tar -czf "$backup/data.tar.gz" -C /var/lib/docker/volumes/easy_tdx_data/_data .
sudo chmod 600 "$backup/data.tar.gz"
sudo tar -tzf "$backup/data.tar.gz" >/dev/null
sudo docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" up -d --no-build --pull never easy-tdx
for attempt in {1..24}; do
  health=$(sudo docker inspect easy-tdx --format '{{.State.Health.Status}}')
  if [ "$health" = healthy ]; then
    curl --fail --silent http://127.0.0.1:18002/api/v1/auth/status
    sudo docker inspect easy-tdx --format '{{.Config.Image}} {{.Image}} {{.State.Status}} {{.State.Health.Status}}'
    trap - ERR
    exit 0
  fi
  sleep 5
done
echo 'Health check failed; rolling back.' >&2
rollback
trap - ERR
exit 1
