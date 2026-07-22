# expert: hf_space_install
# description: Регистрирует доступный Hugging Face Space как стороннюю непроверенную удалённую карточку. Не создаёт ложный localhost, статический ready или неподтверждённый процесс.

def hf_space_install(space="", plugin_id="", display_name="", port="", root_path="", registry_path=""):
    import json, os, re, urllib.error, urllib.request
    from pathlib import Path

    del port, root_path

    def response(status, message, **values):
        values.update({"status":status, "message":message})
        if plugin_id:
            values.setdefault("plugin_id", plugin_id)
        return json.dumps(values, ensure_ascii=False)

    space = str(space or "").strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}", space):
        return response("error", "space должен иметь безопасный формат owner/name", error_class="invalid_space")
    owner, name = space.split("/", 1)
    plugin_id = plugin_id or ("hf_" + re.sub(r"[^a-z0-9]+", "_", space.lower()).strip("_"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,79}", str(plugin_id)):
        return response("error", "некорректный plugin_id", error_class="invalid_plugin_id")
    display_name = str(display_name or name)[:120]
    host = "https://%s-%s.hf.space/" % (
        owner.lower().replace("_", "-"), name.lower().replace("_", "-").replace(".", "-")
    )

    try:
        request = urllib.request.Request(
            host, headers={"User-Agent":"Extella-Client/2 third-party-check", "Accept":"text/html"}
        )
        with urllib.request.urlopen(request, timeout=30) as opened:
            status_code = int(opened.status)
            opened.read(1024)
    except urllib.error.HTTPError as error:
        status_code = int(error.code)
    except (urllib.error.URLError, OSError, ValueError):
        return response("error", "Space недоступен; карточка не установлена",
                        error_class="third_party_unreachable")
    if not 200 <= status_code < 400:
        return response("error", "Space не подтвердил доступность; HTTP " + str(status_code),
                        error_class="third_party_unreachable")

    try:
        from extella_expert_bridge import locations
        native = locations()
    except Exception:
        return response("error", "Системный runtime Extella не установлен. Запустите Repair Extella Client.",
                        error_class="client_runtime_missing")
    registry_root = Path(native["plugin_registry"]).resolve()
    if registry_path:
        destination = Path(registry_path).expanduser().resolve()
        try:
            destination.relative_to(registry_root)
        except ValueError:
            return response("error", "registry_path должен находиться в реестре Extella",
                            error_class="path_outside_extella")
    else:
        destination = registry_root / (plugin_id + ".json")
    registry_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id":plugin_id, "name":display_name, "type":"huggingface", "mode":"remote",
        "classification":"third_party_unverified", "installed":True,
        "hf":{"id":space, "kind":"space", "hosted":True},
        "source":{"type":"huggingface_space", "url":"https://huggingface.co/spaces/" + space},
        "ui":{"type":"iframe", "url":host, "openInBrowser":True, "expectsHealth":False},
        "verification":{"status":"reachable", "httpStatus":status_code},
        "experts":[],
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return response("success", "Space добавлен как сторонняя удалённая карточка",
                    mode="remote", classification="third_party_unverified", reachable=True)
