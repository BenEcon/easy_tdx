#!/usr/bin/env bash
set -euo pipefail
release=/home/opc/apps/easy_tdx-release-20261010-tracking-history-signals
incoming=/home/opc/apps/easy_tdx-origin-proxy-20261010
backup=/home/opc/backups/tdx-20261010-origin-proxy
expected=sha256:936c3f3a821773aba7162c02c95b6e7d223e93e2d69001d0446dda99ac29094e
test "$(sudo -n docker inspect easy-tdx --format '{{.Image}}')" = "$expected"
test "$(sudo -n docker inspect easy-tdx --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')" = 172.22.0.1
test "$(sudo -n docker inspect easy-tdx --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = easy_tdx_data
test "$(sha256sum "$release/compose.yaml" | cut -d ' ' -f1)" = 6e43b3a8bcf95574e08ad16b4a11e291b79bbbb299b8ae7183c5b76c406a77d6
test "$(sha256sum "$release/release-image.yaml" | cut -d ' ' -f1)" = ceb3742b8747a5a9753685877519a8518dd63be33b029c3ac40e2dd765dfddad
sudo -n docker compose -p easy_tdx -f "$incoming/compose.yaml" -f "$release/release-image.yaml" config --quiet
test ! -e "$backup"
mkdir -m 700 "$backup"
cp -p "$release/compose.yaml" "$release/release-image.yaml" "$backup/"
rollback() {
  echo 'Restoring previous proxy configuration; keeping image and all user data.' >&2
  cp -p "$backup/compose.yaml" "$release/compose.yaml"
  sudo -n docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" up -d --no-build --pull never easy-tdx
}
trap 'rollback' ERR
cp "$incoming/compose.yaml" "$release/compose.yaml"
sudo -n docker compose -p easy_tdx -f "$release/compose.yaml" -f "$release/release-image.yaml" up -d --no-build --pull never easy-tdx
for attempt in {1..24}; do
  health=$(sudo -n docker inspect easy-tdx --format '{{.State.Health.Status}}')
  if [ "$health" = healthy ]; then
    test "$(sudo -n docker inspect easy-tdx --format '{{.Image}}')" = "$expected"
    test "$(sudo -n docker inspect easy-tdx --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')" = 172.22.0.1
    test "$(curl --silent --output /dev/null --write-out '%{http_code}' -H 'Host: tdx.bowenv.com' -H 'X-Forwarded-Proto: https' -H 'Origin: https://tdx.bowenv.com' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:18002/api/v1/research/factors/compute)" = 401
    test "$(curl --silent --output /dev/null --write-out '%{http_code}' -H 'Host: tdx.bowenv.com' -H 'X-Forwarded-Proto: https' -H 'Origin: https://untrusted.invalid' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:18002/api/v1/research/factors/compute)" = 403
    curl --fail --silent http://127.0.0.1:18002/api/v1/auth/status
    sudo -n docker inspect easy-tdx --format '{{.Config.Image}} {{.State.Status}} {{.State.Health.Status}}'
    sha256sum "$release/compose.yaml"
    trap - ERR
    exit 0
  fi
  sleep 5
done
echo 'Proxy deployment health check failed.' >&2
rollback
trap - ERR
exit 1
