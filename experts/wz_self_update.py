# expert: wz_self_update
# description: Проверяет локальную версию Extella и объясняет безопасный путь обновления. Никогда не скачивает raw main и не меняет клиент без проверенного release bundle.
def wz_self_update(what="all"):
    import json
    import os
    from pathlib import Path

    del what
    data_root = Path(
        os.environ.get("EXTELLA_DATA_ROOT")
        or (Path.home() / "Library" / "Application Support" / "Extella")
    )
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
