#!/usr/bin/env python3
"""
Extella — (re)start local-server plugins on device boot/login.

Local-server plugins (excalidraw, howtocook, contract-agent, the adoption-wizard
bridge, …) run as plain local processes on fixed ports. A machine reboot kills
them and nothing brings them back, so the user opens the plugin and meets a
"needs to set up" card. Run at login by the companion LaunchAgent, this script
reads the plugin registry and (re)starts every local_server whose port isn't
already listening. Idempotent: safe to run repeatedly (skips live ports).
"""
import glob
import json
import os
import socket
import subprocess
import time
from pathlib import Path

REGISTRY = Path.home() / "extella-plugins" / "_registry"
LOG = Path.home() / "extella-plugins" / "_boot" / "restart.log"
CONTROL_STATE = Path.home() / ".extella" / "activity-center" / "services.json"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def port_up(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.5):
            return True
    except Exception:
        return False


def load_disabled(path=CONTROL_STATE):
    """Return services the user switched off in Activity Center."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {
        value
        for value in payload.get("disabled", [])
        if isinstance(value, str)
    }


def start(cmd, cwd):
    env = dict(os.environ)
    # brew is hidden from the Listener's PATH; local servers may need node/yarn/gs.
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
    subprocess.Popen(
        cmd, shell=True, cwd=cwd, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,   # detach: outlive this script
    )


def main():
    if not REGISTRY.is_dir():
        log("no registry dir (%s) — nothing to do" % REGISTRY)
        return
    disabled = load_disabled()
    started = skipped = 0
    for fp in sorted(glob.glob(str(REGISTRY / "*.json"))):
        try:
            d = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception:
            continue
        ui = d.get("ui") or {}
        svc = d.get("service") or {}
        if ui.get("type") != "local_server" and not svc.get("launchCmd"):
            continue
        service_id = d.get("id", Path(fp).stem)
        port = ui.get("port") or svc.get("port")
        root = os.path.expanduser(str(ui.get("rootPath") or "")) or None
        cmd = svc.get("launchCmd")
        if service_id in disabled:
            log("skip %s — switched off in Activity Center" % service_id)
            skipped += 1
            continue
        if not cmd and port and root:
            cmd = "python3 -m http.server %s" % port   # static-site fallback
        if not cmd:
            log("skip %s — no launch command" % service_id)
            skipped += 1
            continue
        if port and port_up(port):
            skipped += 1   # already running
            continue
        # Do not log the raw registry command: it may contain credentials.
        log("starting %s on localhost:%s (project=%s)" % (
            service_id, port or "?", Path(root).name if root else "home"
        ))
        try:
            start(cmd, root or str(Path.home()))
            started += 1
        except Exception as e:
            log("  FAILED %s: %s" % (service_id, str(e)[:120]))
    log("done - started %d, skipped %d" % (started, skipped))


if __name__ == "__main__":
    main()
