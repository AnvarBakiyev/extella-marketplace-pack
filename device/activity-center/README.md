# Extella Activity Center

Activity Center turns the raw `extella-listener` stream into a human-readable,
always-visible task feed in Extella Desktop.

It consists of two deliberately separate pieces:

1. `toolbar/src/panels/activity-center.js` renders the bottom-right widget and
   links recurring tasks to **Plugins → Расписания**.
2. This directory contains the local device bridge installed by the unified
   Extella Client installer. It stores only allow-listed lifecycle fields in
   the platform-native Extella data directory
   and serves the normalized feed on `http://127.0.0.1:8799`. The bridge also
   exposes localhost services declared in the Extella plugin registry, with a
   narrow start/stop endpoint protected by an in-memory control token.

The raw task result is never persisted. Tokens, arbitrary arguments, message
contents, and listener command lines are not part of the API payload.
Registry launch commands and full project paths are likewise never returned to
the toolbar. A process can be stopped only when its cwd or LaunchAgent proves
that it belongs to the selected service.

Successful result events are terminal even when an older listener omits the
separate `completed` event. This prevents finished Excel and other one-off
operations from remaining in **Сейчас** forever. Expanded completed rows have
**Убрать запись из ленты**, and the panel header has **Очистить выполненные**.
These actions hide lifecycle records; they do not delete user files or Excel
workbooks. A genuinely active listener task is cancelled with the native red
**Cancel** button in Extella's bottom status bar.

In **Plugins → Расписания**, the **Локальные сервисы Extella** block shows each
registered localhost, port, PID, process name, source, and current state. A
service switched off there is recorded in platform-native controller state.
The one Activity Center controller honors that state during login autostart and
never runs a separate shell-based boot checker.

## Install

Activity Center is a required bundled component and is installed atomically on
all supported targets by `installer/client_install.py`. The old standalone
`install.py` and `uninstall.py` entrypoints are retained only to fail safely;
they make no changes. For read-only local bridge development:

```bash
curl -s http://127.0.0.1:8799/api/health
curl -s http://127.0.0.1:8799/api/activity
curl -s http://127.0.0.1:8799/api/services
```

Use the verified native bootstrap with `--uninstall`/`-Uninstall` for removal;
it preserves user-owned data and removes only resources recorded by the
versioned installer.

## Test

```bash
PYTHONPATH=runtime python3 -m unittest discover -s device/activity-center/tests -v
```

The canonical toolbar panel source lives in the isolated toolbar repository;
the marketplace receives only its reproducibly built `toolbar.js` artifact.
