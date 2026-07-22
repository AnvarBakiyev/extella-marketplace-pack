# expert: wz_self_update
# description: Проверяет локальную версию Extella и объясняет безопасный путь обновления. Никогда не скачивает raw main и не меняет клиент без проверенного release bundle.
def wz_self_update(what="all"):
    import json
    from pathlib import Path

    del what
    try:
        from extella_expert_bridge import locations
        data_root = Path(locations()["data_root"])
    except Exception:
        return json.dumps({"status":"error", "errorClass":"client_runtime_missing",
                           "message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."},
                          ensure_ascii=False)
    state_file = data_root / "state" / "client" / "install-state.json"
    version = "unknown"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        version = str(state.get("releaseVersion") or version)
    except (OSError, ValueError):
        pass
    return json.dumps(
        {
            "status": "action_required",
            "errorClass": "verified_bundle_required",
            "installedVersion": version,
            "message": (
                "Обновление Extella выполняется только версионированным установщиком, "
                "который проверяет размер и SHA-256 release bundle. Откройте карточку "
                "Extella Client в Activity Center и выберите Repair/Update."
            ),
        },
        ensure_ascii=False,
    )
