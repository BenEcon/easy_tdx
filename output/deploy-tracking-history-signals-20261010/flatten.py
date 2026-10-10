"""Flatten a pristine, stopped image container; never export production user data."""
import json
import subprocess

base = "easy-tdx:tracking-background-20261010"
docker = ["sudo", "docker"]
info = json.loads(subprocess.check_output(docker + ["image", "inspect", base]))[0]
assert info["Id"] == "sha256:f4c6410a0a1cbe490dd0f8b39c0acd0a722bae05468861a18b48b9fa552cda97"
config = info["Config"]
changes = []
for item in config.get("Env", []):
    key, value = item.split("=", 1)
    changes += ["--change", "ENV " + key + "=" + json.dumps(value)]
for key in ("User", "WorkingDir"):
    if config.get(key):
        changes += ["--change", ("USER " if key == "User" else "WORKDIR ") + config[key]]
for key in ("Entrypoint", "Cmd"):
    if config.get(key):
        changes += ["--change", key.upper() + " " + json.dumps(config[key])]
for port in config.get("ExposedPorts", {}):
    changes += ["--change", "EXPOSE " + port]
for volume in config.get("Volumes") or {}:
    changes += ["--change", "VOLUME " + json.dumps([volume])]
container = subprocess.check_output(docker + ["create", base]).decode().strip()
try:
    export = subprocess.Popen(docker + ["export", container], stdout=subprocess.PIPE)
    try:
        result = subprocess.run(docker + ["import", *changes, "-", "easy-tdx:tracking-background-flat-20261010"], stdin=export.stdout)
        export.stdout.close()
        assert export.wait() == 0 and result.returncode == 0
    finally:
        if export.poll() is None:
            export.terminate()
            export.wait()
finally:
    # Only the pristine temporary container and any empty anonymous volumes it created.
    subprocess.run(docker + ["rm", "-v", container], check=True)
