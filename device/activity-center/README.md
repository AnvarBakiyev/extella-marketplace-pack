# Extella Activity Center

Activity Center turns the raw `extella-listener` stream into a human-readable,
always-visible task feed in Extella Desktop.

It consists of two deliberately separate pieces:

1. `toolbar/src/panels/activity-center.js` renders the bottom-right widget and
   links recurring tasks to **Plugins → Расписания**.
2. This directory installs a local device bridge. It stores only
   allow-listed lifecycle fields in `~/.extella/activity-center/events.jsonl`
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
service switched off there is recorded in
`~/.extella/activity-center/services.json`, so the 10-minute boot checker does
not immediately bring it back.

## Install

The repository `install.sh` installs this observer automatically on macOS after
deploying the modular toolbar. For observer-only development:

```bash
python3 device/activity-center/install.py
curl -s http://127.0.0.1:8799/api/health
curl -s http://127.0.0.1:8799/api/activity
curl -s http://127.0.0.1:8799/api/services
```

Restart Extella after installing so the listener loads the instrumentation
hook. Uninstall only the device observer with:

```bash
python3 device/activity-center/uninstall.py
```

## Test

```bash
python3 -m unittest discover -s device/activity-center/tests -v
node --check toolbar/src/panels/activity-center.js
cd toolbar && node build.js
```

The Activity Center was first validated as a local override before being ported
here. Do not copy the live 4.5 MB `toolbar.js` back into git; this repository's
modular sources remain the source of truth.
