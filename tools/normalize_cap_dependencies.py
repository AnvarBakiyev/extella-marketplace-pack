#!/usr/bin/env python3
"""Normalize every cap_* expert onto the shared Extella dependency bridge.

Run with ``--write`` after adding a capability. The default check mode is used
by the release gate so a capability cannot quietly reintroduce private PATH
probing or its own package-manager implementation.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXPERTS = ROOT / "experts"

SIMPLE_RESOLVERS: dict[str, tuple[str, str]] = {
    "cap_calibre_resolver.py": ("calibre", "calibre"),
    "cap_cwebp_resolver.py": ("cwebp", "cwebp"),
    "cap_exiftool_resolver.py": ("exiftool", "exiftool"),
    "cap_ffmpeg_resolver.py": ("ffmpeg", "ffmpeg"),
    "cap_flac_resolver.py": ("flac", "flac"),
    "cap_ghostscript_resolver.py": ("ghostscript", "ghostscript"),
    "cap_gifsicle_resolver.py": ("gifsicle", "gifsicle"),
    "cap_graphviz_resolver.py": ("graphviz", "graphviz"),
    "cap_imagemagick_resolver.py": ("imagemagick", "imagemagick"),
    "cap_img2pdf_resolver.py": ("img2pdf", "img2pdf"),
    "cap_libreoffice_resolver.py": ("libreoffice", "libreoffice"),
    "cap_oxipng_resolver.py": ("oxipng", "oxipng"),
    "cap_pandoc_resolver.py": ("pandoc", "pandoc"),
    "cap_pdftotext_resolver.py": ("pdftotext", "pdftotext"),
    "cap_pngquant_resolver.py": ("pngquant", "pngquant"),
    "cap_qpdf_resolver.py": ("qpdf", "qpdf"),
    "cap_rsvg_resolver.py": ("rsvg", "rsvg"),
}

OPERATION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("cap_audio_effect", "audacity_cli"),
    ("cap_calibre_", "calibre"),
    ("cap_cwebp_", "cwebp"),
    ("cap_exiftool_", "exiftool"),
    ("cap_ffmpeg_", "ffmpeg"),
    ("cap_flac_", "flac"),
    ("cap_ghostscript_", "ghostscript"),
    ("cap_gifsicle_", "gifsicle"),
    ("cap_graphviz_", "graphviz"),
    ("cap_imagemagick_", "imagemagick"),
    ("cap_img2pdf_", "img2pdf"),
    ("cap_libreoffice_", "libreoffice"),
    ("cap_ocr_", "ocrmypdf"),
    ("cap_oxipng_", "oxipng"),
    ("cap_pandoc_", "pandoc"),
    ("cap_pdftotext_", "pdftotext"),
    ("cap_pngquant_", "pngquant"),
    ("cap_qpdf_", "qpdf"),
    ("cap_rsvg_", "rsvg"),
)


def _headers(path: Path) -> tuple[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    expert = next((line for line in lines[:12] if line.startswith("# expert:")), f"# expert: {path.stem}")
    description = next(
        (line for line in lines[:12] if line.startswith("# description:")),
        f"# description: {path.stem}",
    )
    return expert, description


def _simple_resolver(path: Path, tool: str, marker: str) -> str:
    expert, description = _headers(path)
    function = path.stem
    return f'''{expert}
{description}

def {function}(confirm_install="no") -> str:
    import json, os
    try:
        from extella_expert_bridge import ensure
    except Exception:
        return json.dumps({{"status":"failed","error_class":"client_runtime_missing","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}}, ensure_ascii=False)
    repair = bool(confirm_install) and not str(confirm_install).startswith("{{{{") and str(confirm_install).lower() == "yes"
    result = ensure("{tool}", repair=repair)
    if result.get("ready") and result.get("path"):
        directory = os.path.expanduser("~/.extella_cli")
        os.makedirs(directory, exist_ok=True)
        marker = os.path.join(directory, "{marker}")
        temporary = marker + ".tmp"
        open(temporary, "w", encoding="utf-8").write(result["path"])
        os.replace(temporary, marker)
        result["bin_path"] = result["path"]
        result["source"] = "extella_runtime"
        result["status"] = "installed" if result.get("changed") else "already"
    elif not repair and result.get("status") == "action_required":
        result["status"] = "missing"
    return json.dumps(result, ensure_ascii=False)
'''


def _composite_resolver(path: Path, dependencies: tuple[str, ...], primary: str, marker: str) -> str:
    expert, description = _headers(path)
    function = path.stem
    dependency_literal = repr(dependencies)
    return f'''{expert}
{description}

def {function}(confirm_install="no") -> str:
    import json, os
    try:
        from extella_expert_bridge import ensure
    except Exception:
        return json.dumps({{"status":"failed","error_class":"client_runtime_missing","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}}, ensure_ascii=False)
    repair = bool(confirm_install) and not str(confirm_install).startswith("{{{{") and str(confirm_install).lower() == "yes"
    dependencies = {dependency_literal}
    results = {{name: ensure(name, repair=repair) for name in dependencies}}
    ready = all(result.get("ready") and result.get("path") for result in results.values())
    if ready:
        path = results["{primary}"]["path"]
        directory = os.path.expanduser("~/.extella_cli")
        os.makedirs(directory, exist_ok=True)
        marker = os.path.join(directory, "{marker}")
        temporary = marker + ".tmp"
        open(temporary, "w", encoding="utf-8").write(path)
        os.replace(temporary, marker)
        return json.dumps({{
            "status": "installed" if any(item.get("changed") for item in results.values()) else "already",
            "bin_path": path,
            "source": "extella_runtime",
            "dependencies": results,
        }}, ensure_ascii=False)
    missing = [name for name, result in results.items() if not result.get("ready")]
    return json.dumps({{
        "status": "missing" if not repair else "action_required",
        "error_class": "dependency_missing",
        "message": "Не готовы зависимости: " + ", ".join(missing),
        "dependencies": results,
    }}, ensure_ascii=False)
'''


def _operation_tool(path: Path) -> str | None:
    for prefix, tool in OPERATION_PREFIXES:
        if path.stem.startswith(prefix):
            return tool
    return None


def _replace_nested_resolver(source: str, tool: str) -> str:
    tree = ast.parse(source)
    candidates: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in {"binpath", "ca_path"}:
            continue
        candidates.append(node)
    if len(candidates) != 1:
        raise ValueError(f"expected one nested dependency resolver, found {len(candidates)}")
    node = candidates[0]
    lines = source.splitlines(keepends=True)
    indent = re.match(r"\s*", lines[node.lineno - 1]).group(0)
    replacement = (
        f"{indent}def {node.name}():\n"
        f"{indent}    try:\n"
        f"{indent}        from extella_expert_bridge import path_or_error\n"
        f"{indent}        path, _state = path_or_error(\"{tool}\", repair=False)\n"
        f"{indent}        return path\n"
        f"{indent}    except Exception:\n"
        f"{indent}        return None\n"
    )
    lines[node.lineno - 1 : node.end_lineno] = [replacement]
    normalized = "".join(lines)
    normalized = re.sub(
        r'^\s*([A-Za-z_][A-Za-z0-9_]*)\["PATH"\]\s*=\s*[\'\"]/opt/homebrew/bin[\'\"]\s*\+\s*os\.pathsep\s*\+\s*\1\.get\("PATH",\s*""\)\s*\n',
        "",
        normalized,
        flags=re.MULTILINE,
    )
    normalized = normalized.replace(
        '    env=dict(os.environ); env["PATH"]="/opt/homebrew/bin"+os.pathsep+env.get("PATH","")\n',
        '    env=dict(os.environ)\n',
    )
    return normalized


def _localmodel(source: str) -> str:
    old = '    ol = next((p for p in ["/usr/local/bin/ollama","/opt/homebrew/bin/ollama","/Applications/Ollama.app/Contents/Resources/ollama"] if os.path.exists(p)), None)\n'
    replacement = (
        "    try:\n"
        "        from extella_expert_bridge import path_or_error\n"
        "        ol, runtime = path_or_error(\"ollama\", repair=True)\n"
        "    except Exception:\n"
        "        ol, runtime = None, {\"message\": \"Системный runtime Extella не установлен. Запустите Repair Extella Client.\"}\n"
    )
    if old in source:
        source = source.replace(old, replacement)
    source = source.replace(
        '    if not ol: return json.dumps({"status":"error","message":"Ollama не установлен — поставьте Ollama.app с ollama.com"}, ensure_ascii=False)\n',
        '    if not ol: return json.dumps({"status":"error","message":runtime.get("message") or "Ollama недоступен"}, ensure_ascii=False)\n',
    )
    return source


def expected(path: Path) -> str:
    if path.name in SIMPLE_RESOLVERS:
        return _simple_resolver(path, *SIMPLE_RESOLVERS[path.name])
    if path.name == "cap_audio_resolver.py":
        return _composite_resolver(path, ("audacity_cli", "sox"), "audacity_cli", "audio")
    if path.name == "cap_ocr_resolver.py":
        return _composite_resolver(path, ("ocrmypdf", "tesseract"), "ocrmypdf", "ocr")
    source = path.read_text(encoding="utf-8")
    if path.name == "cap_localmodel_install.py":
        return _localmodel(source)
    tool = _operation_tool(path)
    if tool and path.name not in {"cap_local_ask.py"}:
        return _replace_nested_resolver(source, tool)
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    changed: list[str] = []
    for path in sorted(EXPERTS.glob("cap_*.py")):
        rendered = expected(path)
        current = path.read_text(encoding="utf-8")
        if current == rendered:
            continue
        changed.append(path.name)
        if args.write:
            path.write_text(rendered, encoding="utf-8")
    if changed and not args.write:
        print("cap dependency contracts require normalization: " + ", ".join(changed))
        return 1
    if args.write:
        print(f"normalized {len(changed)} cap dependency contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
