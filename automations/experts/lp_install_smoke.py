# expert: lp_install_smoke
def lp_install_smoke() -> str:
    """Credential-free smoke test for a freshly installed contract pack."""
    import json
    import os
    import tempfile

    path = ""
    try:
        descriptor, path = tempfile.mkstemp(prefix="extella-lp-smoke-", suffix=".tmp")
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(b"ok")
        with open(path, "rb") as temporary_file:
            ready = temporary_file.read() == b"ok"
        return json.dumps(
            {"ok": ready, "check": "local_round_trip", "pack": "contract_agent"},
            ensure_ascii=False,
        )
    except Exception as error:
        return json.dumps(
            {"ok": False, "check": "local_round_trip", "error": type(error).__name__},
            ensure_ascii=False,
        )
    finally:
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
