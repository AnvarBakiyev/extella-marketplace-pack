# expert: catalog_tool_manage
# description: Устанавливает, проверяет и удаляет поддерживаемые локальные инструменты каталога без зависимости от Конструктора.
# params: action, tool

def catalog_tool_manage(action="status", tool="") -> str:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    catalog = {
        "ghostscript": ("ghostscript",),
        "pandoc": ("pandoc",),
        "ocr": ("ocrmypdf", "tesseract"),
        "libreoffice": ("libreoffice",),
        "qpdf": ("qpdf",),
        "imagemagick": ("imagemagick",),
        "ffmpeg": ("ffmpeg",),
    }
    packages = {
        "ghostscript": {"brew": ("ghostscript", False), "winget": "ArtifexSoftware.GhostScript"},
        "pandoc": {"brew": ("pandoc", False), "winget": "JohnMacFarlane.Pandoc"},
        "ocrmypdf": {"brew": ("ocrmypdf", False)},
        "tesseract": {"brew": ("tesseract", False), "winget": "UB-Mannheim.TesseractOCR"},
        "libreoffice": {"brew": ("libreoffice", True)},
        "qpdf": {"brew": ("qpdf", False)},
        "imagemagick": {"brew": ("imagemagick", False), "winget": "ImageMagick.ImageMagick"},
        "ffmpeg": {"brew": ("ffmpeg", False), "winget": "Gyan.FFmpeg"},
    }

    def reply(status, **values):
        values["status"] = status
        values["tool"] = tool
        return json.dumps(values, ensure_ascii=False)

    action = str(action or "status").strip().lower()
    tool = str(tool or "").strip().lower()
    if action not in {"status", "install", "uninstall"}:
        return reply("error", error_class="invalid_action", message="Неизвестное действие каталога.")
    if tool not in catalog:
        return reply("error", error_class="unsupported_tool", message="Инструмент не входит в поддерживаемый каталог Extella.")

    try:
        from extella_expert_bridge import ensure, locations, path_or_error
    except Exception:
        return reply(
            "error",
            error_class="client_runtime_missing",
            message="Системный runtime Extella не установлен. Запустите Repair Extella Client.",
        )

    state_path = Path(locations()["state_root"]) / "catalog-tools.json"

    def load_state():
        try:
            value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {"schemaVersion": 1, "tools": {}}
        if not isinstance(value, dict) or not isinstance(value.get("tools"), dict):
            return {"schemaVersion": 1, "tools": {}}
        return value

    def save_state(value):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_name(".%s.%s.tmp" % (state_path.name, os.getpid()))
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, state_path)

    state = load_state()
    previous = state["tools"].get(tool) if isinstance(state["tools"].get(tool), dict) else {}
    dependencies = catalog[tool]

    if action in {"status", "install"}:
        results = {}
        for dependency in dependencies:
            results[dependency] = ensure(dependency, repair=(action == "install"))
        managed = set(str(name) for name in previous.get("managedDependencies") or [])
        managed.update(name for name, item in results.items() if item.get("changed"))
        if action == "install" and managed:
            # Если составная установка (например OCR) успела поставить первую
            # зависимость и упала на второй, всё равно запоминаем владение.
            # Повтор продолжит установку, а удаление не оставит сиротский пакет.
            state["tools"][tool] = {
                "dependencies": list(dependencies),
                "managedDependencies": sorted(managed),
            }
            save_state(state)
        ready = all(item.get("ready") and item.get("path") for item in results.values())
        if not ready:
            missing = [name for name, item in results.items() if not item.get("ready")]
            return reply(
                "missing" if action == "status" else "error",
                error_class="dependency_missing",
                message="Не готовы зависимости: " + ", ".join(missing),
                dependencies=results,
            )
        if action == "install":
            state["tools"][tool] = {
                "dependencies": list(dependencies),
                "managedDependencies": sorted(managed),
            }
            save_state(state)
        return reply(
            "installed" if any(item.get("changed") for item in results.values()) else "already",
            ready=True,
            managed=bool(managed),
            managed_dependencies=sorted(managed),
            dependencies=results,
            message="Инструмент готов к работе.",
        )

    managed = [str(name) for name in previous.get("managedDependencies") or [] if name in dependencies]
    if not managed:
        state["tools"].pop(tool, None)
        save_state(state)
        return reply(
            "success",
            device_removed=True,
            removed=False,
            preserved_external=True,
            message="Extella убрала ярлык, но сохранила программу: она была установлена не Extella.",
        )

    failures = []
    removed = []
    for dependency in managed:
        package = packages.get(dependency) or {}
        if sys.platform.startswith("win"):
            package_id = package.get("winget")
            manager, manager_state = path_or_error("winget", repair=False)
            argv = [
                manager,
                "uninstall",
                "--id",
                package_id,
                "--exact",
                "--scope",
                "user",
                "--disable-interactivity",
            ] if manager and package_id else []
        else:
            formula = package.get("brew")
            manager, manager_state = path_or_error("brew", repair=False)
            argv = [manager, "uninstall"] + (["--cask"] if formula and formula[1] else []) + [formula[0]] if manager and formula else []
        if not argv:
            failures.append(dependency + ": нет поддерживаемого способа удаления")
            continue
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False, shell=False)
        except (OSError, subprocess.SubprocessError) as error:
            failures.append(dependency + ": " + type(error).__name__)
            continue
        output = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
        absent = any(marker in output for marker in ("no such keg", "not installed", "no installed package found"))
        if result.returncode == 0 or absent:
            removed.append(dependency)
        else:
            failures.append(dependency + ": пакетный менеджер вернул ошибку")

    if failures:
        return reply(
            "error",
            error_class="uninstall_failed",
            device_removed=False,
            removed_dependencies=removed,
            message="; ".join(failures)[:300],
        )
    state["tools"].pop(tool, None)
    save_state(state)
    return reply(
        "success",
        device_removed=True,
        removed=True,
        removed_dependencies=removed,
        message="Программа, установленная Extella, удалена с устройства.",
    )
