"""Turn low-level listener lifecycle events into a human-readable activity feed."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SEMANTICS: dict[str, dict[str, Any]] = {
    "_etb_registry_read": {
        "running": "Обновляется список плагинов",
        "completed": "Обновлён список плагинов",
        "interrupted": "Прервано обновление списка плагинов",
        "detail": "Extella перечитала локальный реестр расширений.",
        "category": "system",
        "origin": "Extella Desktop · реестр плагинов",
        "purpose": "Обновляет список доступных расширений и их состояние.",
        "recurring": False,
    },
    "wz_scheduler_tick": {
        "running": "Проверяется расписание",
        "completed": "Проверено расписание",
        "interrupted": "Прервана проверка расписания",
        "detail": "Extella проверила, пора ли запускать автоматизации.",
        "category": "background",
        "origin": "AI Автоматизации · планировщик Extella",
        "purpose": "Проверяет расписания и запускает автоматизации, когда наступает их время.",
        "recurring": True,
        "manageTarget": "automations",
        "manageLabel": "Открыть расписание",
    },
    "wz_connector_telegram": {
        "running": "Проверяется Telegram",
        "completed": "Проверен Telegram",
        "interrupted": "Прервана проверка Telegram",
        "detail": "Extella проверила новые входящие сообщения.",
        "category": "background",
        "origin": "AI Автоматизации · Telegram-коннектор",
        "purpose": "Проверяет, появились ли новые входящие сообщения в подключённом Telegram.",
        "recurring": True,
        "manageTarget": "automations",
        "manageLabel": "Открыть AI Автоматизации",
    },
    "ta_wa_inbound_tick": {
        "running": "Проверяется WhatsApp",
        "completed": "Проверен WhatsApp",
        "interrupted": "Прервана проверка WhatsApp",
        "detail": "Extella проверила входящие сообщения WhatsApp.",
        "category": "background",
        "origin": "AI Автоматизации · WhatsApp-коннектор",
        "purpose": "Проверяет, появились ли новые входящие сообщения в подключённом WhatsApp.",
        "recurring": True,
        "manageTarget": "automations",
        "manageLabel": "Открыть AI Автоматизации",
    },
    "wz_workspace": {
        "running": "Обновляются рабочие пространства",
        "completed": "Обновлены рабочие пространства",
        "interrupted": "Прервано обновление рабочих пространств",
        "detail": "Список рабочих пространств синхронизирован.",
        "category": "system",
        "origin": "Extella Desktop · рабочие пространства",
        "purpose": "Поддерживает список рабочих пространств в актуальном состоянии.",
        "recurring": False,
    },
    "test_ping": {
        "running": "Проверяется соединение",
        "completed": "Проверено соединение",
        "interrupted": "Прервана проверка соединения",
        "detail": "Extella убедилась, что локальный исполнитель доступен.",
        "category": "system",
        "origin": "Extella Desktop · локальный listener",
        "purpose": "Проверяет, что локальный исполнитель доступен для новых задач.",
        "recurring": False,
    },
}


def read_events(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    tail: deque[str] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        tail.extend(handle)
    events: list[dict[str, Any]] = []
    for line in tail:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type"):
            events.append(event)
    return sorted(events, key=lambda item: item.get("ts", ""))


def _humanize_function(name: str) -> str:
    words = [part for part in name.strip("_").split("_") if part]
    return " ".join(words) if words else "операция Extella"


def _friendly_detail(function_name: str, summary: dict[str, Any]) -> str:
    base = SEMANTICS.get(function_name, {}).get(
        "detail", f"Выполнена операция: {_humanize_function(function_name)}."
    )
    if function_name == "wz_scheduler_tick":
        checked = summary.get("checked")
        if summary.get("noRuns"):
            count = f"Проверено автоматизаций: {checked}. " if checked is not None else ""
            return count + "Запусков не потребовалось."
    if function_name in {"wz_connector_telegram", "ta_wa_inbound_tick"}:
        if summary.get("noMessages") or summary.get("processed") == 0:
            return "Новых сообщений нет."
    return base


def _to_public(task: dict[str, Any]) -> dict[str, Any]:
    status = task.get("status", "running")
    function_name = task.get("function") or ""
    semantic = SEMANTICS.get(function_name, {})
    if status == "interrupted":
        running_title = semantic.get("running", "Выполнялась задача Extella")
        title = semantic.get("interrupted") or running_title.replace(
            "Проверяется", "Прервана проверка"
        ).replace("Обновляется", "Прервано обновление").replace(
            "Обновляются", "Прервано обновление"
        )
        detail = "Listener был перезапущен до подтверждения результата."
        category = semantic.get("category", "action")
    elif function_name:
        title = semantic.get(status) or semantic.get("completed") or f"Задача: {_humanize_function(function_name)}"
        detail = _friendly_detail(function_name, task.get("summary") or {})
        category = semantic.get("category", "action")
    else:
        title = "Extella выполняет задачу" if status == "running" else "Выполнена задача Extella"
        detail = "Название операции пока определяется."
        category = "action"

    summary = task.get("summary") or {}
    source_ids = [
        str(source_id)
        for source_id in summary.get("sourceIds") or []
        if isinstance(source_id, str)
    ][:5]

    return {
        "id": task["id"],
        "shortId": task["id"][:8],
        "status": status,
        "title": title,
        "detail": detail,
        "category": category,
        "function": function_name or None,
        "origin": semantic.get("origin", "Extella · локальный исполнитель"),
        "purpose": semantic.get(
            "purpose",
            (
                f"Выполняет операцию {_humanize_function(function_name)}."
                if function_name
                else "Выполняет локальную операцию Extella."
            ),
        ),
        "recurring": bool(semantic.get("recurring", False)),
        "mode": (
            "Регулярная фоновая задача"
            if semantic.get("recurring")
            else "Служебная задача Extella"
        ),
        "manageTarget": semantic.get("manageTarget"),
        "manageLabel": semantic.get("manageLabel"),
        "sourceIds": source_ids,
        "channel": summary.get("channel"),
        "startedAt": task.get("startedAt"),
        "completedAt": task.get("completedAt"),
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _attach_scheduler_sources(tasks: list[dict[str, Any]]) -> None:
    """Link connector rows to the scheduler cycle that launched them.

    The Telegram worker result does not repeat its session id. The parent
    scheduler result does, so we attach it only when the channel matches and
    both tasks completed in the same short polling cycle.
    """
    scheduler_tasks = [
        task
        for task in tasks
        if task.get("function") == "wz_scheduler_tick" and task.get("sourceIds")
    ]
    for task in tasks:
        if task.get("sourceIds") or task.get("function") not in {
            "wz_connector_telegram",
            "ta_wa_inbound_tick",
        }:
            continue
        channel = "telegram" if task["function"] == "wz_connector_telegram" else "whatsapp"
        task_ts = _parse_ts(task.get("completedAt") or task.get("startedAt"))
        if not task_ts:
            continue
        matches: list[tuple[float, dict[str, Any]]] = []
        for scheduler in scheduler_tasks:
            if scheduler.get("channel") and scheduler.get("channel") != channel:
                continue
            scheduler_ts = _parse_ts(
                scheduler.get("completedAt") or scheduler.get("startedAt")
            )
            if not scheduler_ts:
                continue
            distance = abs((scheduler_ts - task_ts).total_seconds())
            if distance <= 90:
                matches.append((distance, scheduler))
        if matches:
            _, scheduler = min(matches, key=lambda item: item[0])
            task["sourceIds"] = list(scheduler["sourceIds"])
            task["manageLabel"] = "Открыть расписание"


def build_activity(
    events: Iterable[dict[str, Any]], listener_info: dict[str, Any] | None = None
) -> dict[str, Any]:
    tasks: dict[str, dict[str, Any]] = {}
    pending: dict[int, list[str]] = defaultdict(list)
    listener_starts = 0

    for event in events:
        event_type = event.get("type")
        task_id = event.get("taskId")
        pid = int(event.get("pid") or 0)
        ppid = int(event.get("ppid") or 0)

        if event_type == "listener_started":
            listener_starts += 1
            continue

        if event_type == "received" and task_id:
            task = tasks.setdefault(
                task_id,
                {
                    "id": task_id,
                    "status": "running",
                    "startedAt": event.get("ts"),
                    "sourcePid": pid,
                    "summary": {},
                },
            )
            task["status"] = "running"
            if task_id not in pending[pid]:
                pending[pid].append(task_id)
            continue

        if event_type == "identified" and event.get("function"):
            source_pid = ppid if pending.get(ppid) else pid
            candidates = pending.get(source_pid, [])
            for candidate_id in candidates:
                candidate = tasks.get(candidate_id)
                if candidate and not candidate.get("function"):
                    candidate["function"] = event["function"]
                    break
            continue

        if event_type == "result" and task_id:
            task = tasks.setdefault(
                task_id,
                {
                    "id": task_id,
                    "status": "running",
                    "startedAt": event.get("ts"),
                    "sourcePid": pid,
                    "summary": {},
                },
            )
            task["summary"] = event.get("summary") or {}
            continue

        if event_type in {"completed", "failed"} and task_id:
            task = tasks.setdefault(
                task_id,
                {
                    "id": task_id,
                    "startedAt": event.get("ts"),
                    "sourcePid": pid,
                    "summary": {},
                },
            )
            task["status"] = "failed" if event_type == "failed" else "completed"
            task["completedAt"] = event.get("ts")
            source_pid = int(task.get("sourcePid") or pid)
            if task_id in pending.get(source_pid, []):
                pending[source_pid].remove(task_id)

    listener_info = listener_info or {"count": 0, "orphaned": 0, "processes": []}
    current_pids = {
        int(process.get("pid") or 0) for process in listener_info.get("processes", [])
    }
    if current_pids:
        now = datetime.now(timezone.utc).isoformat()
        for task in tasks.values():
            source_pid = int(task.get("sourcePid") or 0)
            if task.get("status") == "running" and source_pid not in current_pids:
                task["status"] = "interrupted"
                task["completedAt"] = now

    public_tasks = [_to_public(task) for task in tasks.values()]
    _attach_scheduler_sources(public_tasks)
    public_tasks.sort(key=lambda task: task.get("startedAt") or "", reverse=True)
    active = [task for task in public_tasks if task["status"] == "running"]
    history = [task for task in public_tasks if task["status"] != "running"][:40]
    if listener_info.get("orphaned", 0):
        headline = "Найдены лишние процессы Extella"
        health = "warning"
    elif active:
        headline = active[0]["title"]
        health = "busy"
    else:
        headline = "Система спокойна"
        health = "ok"

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "health": health,
        "headline": headline,
        "active": active,
        "history": history,
        "counts": {
            "active": len(active),
            "completed": sum(task["status"] == "completed" for task in public_tasks),
            "failed": sum(task["status"] == "failed" for task in public_tasks),
            "interrupted": sum(task["status"] == "interrupted" for task in public_tasks),
            "listenerStarts": listener_starts,
        },
        "listeners": listener_info,
    }
