"""One structured dependency resolver for installers, plugins, and Doctor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Iterable, Mapping, Sequence

from .platforms import PlatformInfo, detect_platform


@dataclass(frozen=True)
class ToolSpec:
    name: str
    executables_macos: tuple[str, ...]
    executables_windows: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)
    brew_formula: str | None = None
    brew_cask: bool = False
    winget_id: str | None = None
    minimum_version: tuple[int, ...] | None = None


TOOL_SPECS: dict[str, ToolSpec] = {
    "python": ToolSpec(
        "python", ("python3", "python"), ("python.exe", "python3.exe"),
        brew_formula="python@3.12", winget_id="Python.Python.3.12",
        minimum_version=(3, 12)
    ),
    "node": ToolSpec(
        "node", ("node",), ("node.exe",), brew_formula="node",
        winget_id="OpenJS.NodeJS.LTS", minimum_version=(18, 0)
    ),
    "npm": ToolSpec(
        "npm", ("npm",), ("npm.cmd", "npm.exe"), brew_formula="node",
        winget_id="OpenJS.NodeJS.LTS", minimum_version=(9, 0)
    ),
    "npx": ToolSpec(
        "npx", ("npx",), ("npx.cmd", "npx.exe"), brew_formula="node",
        winget_id="OpenJS.NodeJS.LTS", minimum_version=(9, 0)
    ),
    "uv": ToolSpec(
        "uv", ("uv",), ("uv.exe",), brew_formula="uv", winget_id="astral-sh.uv",
        minimum_version=(0, 5)
    ),
    "uvx": ToolSpec(
        "uvx", ("uvx",), ("uvx.exe",), brew_formula="uv", winget_id="astral-sh.uv",
        minimum_version=(0, 5)
    ),
    "git": ToolSpec(
        "git", ("git",), ("git.exe",), brew_formula="git", winget_id="Git.Git",
        minimum_version=(2, 30)
    ),
    "gh": ToolSpec(
        "gh", ("gh",), ("gh.exe",), brew_formula="gh", winget_id="GitHub.cli",
        minimum_version=(2, 0)
    ),
    "ffmpeg": ToolSpec(
        "ffmpeg", ("ffmpeg",), ("ffmpeg.exe",), brew_formula="ffmpeg",
        winget_id="Gyan.FFmpeg"
    ),
    "ghostscript": ToolSpec(
        "ghostscript", ("gs",), ("gswin64c.exe", "gswin32c.exe"),
        brew_formula="ghostscript", winget_id="ArtifexSoftware.GhostScript"
    ),
    "imagemagick": ToolSpec(
        "imagemagick", ("magick", "convert"), ("magick.exe",),
        brew_formula="imagemagick", winget_id="ImageMagick.ImageMagick"
    ),
    "pandoc": ToolSpec(
        "pandoc", ("pandoc",), ("pandoc.exe",), brew_formula="pandoc",
        winget_id="JohnMacFarlane.Pandoc"
    ),
    "ollama": ToolSpec(
        "ollama", ("ollama",), ("ollama.exe",), brew_formula="ollama",
        winget_id="Ollama.Ollama"
    ),
    "sox": ToolSpec(
        "sox", ("sox",), ("sox.exe",), brew_formula="sox"
    ),
    "audacity_cli": ToolSpec(
        "audacity_cli", ("cli-anything-audacity",), ("cli-anything-audacity.exe",),
        version_args=("--help",)
    ),
    "calibre": ToolSpec(
        "calibre", ("ebook-convert",), ("ebook-convert.exe",),
        brew_formula="calibre", brew_cask=True
    ),
    "cwebp": ToolSpec(
        "cwebp", ("cwebp",), ("cwebp.exe",), version_args=("-version",),
        brew_formula="webp"
    ),
    "exiftool": ToolSpec(
        "exiftool", ("exiftool",), ("exiftool.exe",), version_args=("-ver",),
        brew_formula="exiftool"
    ),
    "flac": ToolSpec(
        "flac", ("flac",), ("flac.exe",), brew_formula="flac"
    ),
    "gifsicle": ToolSpec(
        "gifsicle", ("gifsicle",), ("gifsicle.exe",), brew_formula="gifsicle"
    ),
    "graphviz": ToolSpec(
        "graphviz", ("dot",), ("dot.exe",), version_args=("-V",),
        brew_formula="graphviz"
    ),
    "img2pdf": ToolSpec(
        "img2pdf", ("img2pdf",), ("img2pdf.exe",)
    ),
    "libreoffice": ToolSpec(
        "libreoffice", ("soffice",), ("soffice.exe",),
        brew_formula="libreoffice", brew_cask=True
    ),
    "ocrmypdf": ToolSpec(
        "ocrmypdf", ("ocrmypdf",), ("ocrmypdf.exe",), brew_formula="ocrmypdf"
    ),
    "tesseract": ToolSpec(
        "tesseract", ("tesseract",), ("tesseract.exe",), brew_formula="tesseract",
        winget_id="UB-Mannheim.TesseractOCR"
    ),
    "oxipng": ToolSpec(
        "oxipng", ("oxipng",), ("oxipng.exe",), brew_formula="oxipng"
    ),
    "pdftotext": ToolSpec(
        "pdftotext", ("pdftotext",), ("pdftotext.exe",), version_args=("-v",),
        brew_formula="poppler", winget_id="oschwartz10612.Poppler"
    ),
    "pdftoppm": ToolSpec(
        "pdftoppm", ("pdftoppm",), ("pdftoppm.exe",), version_args=("-v",),
        brew_formula="poppler", winget_id="oschwartz10612.Poppler"
    ),
    "pngquant": ToolSpec(
        "pngquant", ("pngquant",), ("pngquant.exe",), brew_formula="pngquant"
    ),
    "qpdf": ToolSpec(
        "qpdf", ("qpdf",), ("qpdf.exe",), brew_formula="qpdf"
    ),
    "rsvg": ToolSpec(
        "rsvg", ("rsvg-convert",), ("rsvg-convert.exe",), brew_formula="librsvg"
    ),
    "conda": ToolSpec(
        "conda", ("conda",), ("conda.exe", "conda.bat"),
        brew_formula="miniconda", brew_cask=True, winget_id="Anaconda.Miniconda3"
    ),
    "pnpm": ToolSpec(
        "pnpm", ("pnpm",), ("pnpm.cmd", "pnpm.exe"), brew_formula="pnpm",
        winget_id="pnpm.pnpm"
    ),
    "yarn": ToolSpec(
        "yarn", ("yarn",), ("yarn.cmd", "yarn.exe"), brew_formula="yarn",
        winget_id="Yarn.Yarn"
    ),
    "brew": ToolSpec("brew", ("brew",), (), version_args=("--version",)),
    "winget": ToolSpec("winget", (), ("winget.exe",), version_args=("--version",)),
}


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class EnsureResult:
    tool: str
    status: str
    path: str | None = None
    version: str | None = None
    error_class: str | None = None
    message: str | None = None
    changed: bool = False
    platform: str | None = None

    @property
    def ready(self) -> bool:
        return self.status in {"ready", "installed"}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready"] = self.ready
        return payload


Executor = Callable[[Sequence[str], int], CommandOutcome]
Which = Callable[[str, str], str | None]


def _default_executor(argv: Sequence[str], timeout: int) -> CommandOutcome:
    try:
        process = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandOutcome(127, "", str(exc))
    return CommandOutcome(process.returncode, process.stdout or "", process.stderr or "")


def _default_which(executable: str, search_path: str) -> str | None:
    return shutil.which(executable, path=search_path)


def _search_path(platform_info: PlatformInfo, env: Mapping[str, str]) -> str:
    entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if platform_info.key == "macos-arm64":
        entries.extend(("/opt/homebrew/bin", "/opt/homebrew/sbin"))
    if platform_info.key == "macos-x86_64":
        entries.extend(("/usr/local/bin", "/usr/local/sbin"))
    if platform_info.system == "Darwin":
        entries.extend(
            (
                str(home / ".local" / "bin"),
                str(home / ".cargo" / "bin"),
                str(home / "miniconda3" / "bin"),
                "/Applications/calibre.app/Contents/MacOS",
                "/Applications/LibreOffice.app/Contents/MacOS",
                "/Applications/Ollama.app/Contents/Resources",
                "/usr/bin",
                "/bin",
            )
        )
    if platform_info.system == "Windows":
        local_app_data = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        program_files = Path(env.get("ProgramFiles") or "C:/Program Files")
        entries.extend(
            (
                str(local_app_data / "Microsoft" / "WinGet" / "Links"),
                str(local_app_data / "Programs" / "Python" / "Python312"),
                str(local_app_data / "Programs" / "Python" / "Python312" / "Scripts"),
                str(local_app_data / "Programs" / "Ollama"),
                str(local_app_data / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64"),
                str(program_files / "Calibre2"),
                str(program_files / "LibreOffice" / "program"),
                str(program_files / "Tesseract-OCR"),
                str(program_files / "nodejs"),
                str(program_files / "Git" / "cmd"),
            )
        )
    return os.pathsep.join(dict.fromkeys(entries))


def _executables(spec: ToolSpec, platform_info: PlatformInfo) -> tuple[str, ...]:
    if platform_info.system == "Darwin":
        return spec.executables_macos
    if platform_info.system == "Windows":
        return spec.executables_windows
    return ()


def _version_line(outcome: CommandOutcome) -> str | None:
    output = (outcome.stdout or outcome.stderr).strip()
    if not output:
        return None
    return output.splitlines()[0][:300]


def _parsed_version(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups(default="0"))


def _meets_minimum(value: str | None, minimum: tuple[int, ...] | None) -> bool:
    if minimum is None:
        return True
    parsed = _parsed_version(value)
    if parsed is None:
        return False
    width = max(len(parsed), len(minimum))
    padded_value = parsed + (0,) * (width - len(parsed))
    padded_minimum = minimum + (0,) * (width - len(minimum))
    return padded_value >= padded_minimum


def resolve_tool(
    name: str,
    *,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    executor: Executor = _default_executor,
    which: Which = _default_which,
    timeout: int = 20,
) -> EnsureResult:
    platform_info = platform_info or detect_platform()
    if not platform_info.supported:
        return EnsureResult(
            name,
            "unsupported",
            error_class="unsupported_platform",
            message=platform_info.reason,
        )
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return EnsureResult(
            name,
            "failed",
            error_class="unknown_tool",
            message=f"No dependency contract exists for {name}",
            platform=platform_info.key,
        )
    environment = dict(os.environ if env is None else env)
    search_path = _search_path(platform_info, environment)
    broken: tuple[str, CommandOutcome] | None = None
    for executable in _executables(spec, platform_info):
        path = which(executable, search_path)
        if not path:
            continue
        outcome = executor((path, *spec.version_args), timeout)
        if outcome.returncode == 0:
            version = _version_line(outcome)
            if not _meets_minimum(version, spec.minimum_version):
                minimum = ".".join(str(part) for part in spec.minimum_version or ())
                return EnsureResult(
                    name,
                    "failed",
                    path=str(Path(path)),
                    version=version,
                    error_class="incompatible_version",
                    message=f"{name} {minimum} or newer is required",
                    platform=platform_info.key,
                )
            return EnsureResult(
                name,
                "ready",
                path=str(Path(path)),
                version=version,
                platform=platform_info.key,
            )
        broken = (path, outcome)
    if broken:
        path, outcome = broken
        detail = _version_line(outcome) or "version probe failed"
        return EnsureResult(
            name,
            "failed",
            path=str(Path(path)),
            error_class="corrupted_runtime",
            message=detail,
            platform=platform_info.key,
        )
    return EnsureResult(
        name,
        "action_required",
        error_class="tool_missing",
        message=f"{name} is not installed or is not discoverable",
        platform=platform_info.key,
    )


def _install_command(
    spec: ToolSpec,
    manager_path: str,
    platform_info: PlatformInfo,
    *,
    repair: bool,
) -> tuple[str, ...] | None:
    if platform_info.system == "Darwin" and spec.brew_formula:
        verb = "reinstall" if repair else "install"
        cask = ("--cask",) if spec.brew_cask else ()
        return (manager_path, verb, *cask, spec.brew_formula)
    if platform_info.system == "Windows" and spec.winget_id:
        command = [
            manager_path,
            "install",
            "--id",
            spec.winget_id,
            "--exact",
            "--scope",
            "user",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ]
        if repair:
            command.append("--force")
        return tuple(command)
    return None


def ensure_tool(
    name: str,
    *,
    allow_install: bool = False,
    platform_info: PlatformInfo | None = None,
    env: Mapping[str, str] | None = None,
    executor: Executor = _default_executor,
    which: Which = _default_which,
    timeout: int = 300,
) -> EnsureResult:
    """Resolve, verify, optionally install/repair, then verify a dependency."""

    platform_info = platform_info or detect_platform()
    current = resolve_tool(
        name,
        platform_info=platform_info,
        env=env,
        executor=executor,
        which=which,
    )
    if current.ready or not allow_install or current.status == "unsupported":
        return current
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return current
    if name in {"brew", "winget"}:
        return EnsureResult(
            name,
            "action_required",
            error_class="package_manager_missing",
            message="Install the supported OS package manager, then run repair again",
            platform=platform_info.key,
        )
    manager_name = "brew" if platform_info.system == "Darwin" else "winget"
    manager = resolve_tool(
        manager_name,
        platform_info=platform_info,
        env=env,
        executor=executor,
        which=which,
    )
    if not manager.ready or not manager.path:
        return EnsureResult(
            name,
            "action_required",
            error_class="package_manager_missing",
            message=f"{manager_name} is required to install or repair {name}",
            platform=platform_info.key,
        )
    command = _install_command(
        spec,
        manager.path,
        platform_info,
        repair=current.error_class in {"corrupted_runtime", "incompatible_version"},
    )
    if command is None:
        return EnsureResult(
            name,
            "action_required",
            error_class="automatic_install_unavailable",
            message=f"Automatic installation is not defined for {name}",
            platform=platform_info.key,
        )
    outcome = executor(command, timeout)
    if outcome.returncode != 0:
        detail = _version_line(outcome) or "package manager returned an error"
        return EnsureResult(
            name,
            "failed",
            error_class="install_failed",
            message=detail,
            platform=platform_info.key,
        )
    verified = resolve_tool(
        name,
        platform_info=platform_info,
        env=env,
        executor=executor,
        which=which,
    )
    if not verified.ready:
        return EnsureResult(
            name,
            "failed",
            path=verified.path,
            error_class="post_install_verification_failed",
            message=verified.message,
            changed=True,
            platform=platform_info.key,
        )
    return EnsureResult(
        name,
        "installed",
        path=verified.path,
        version=verified.version,
        changed=True,
        platform=platform_info.key,
    )


def ensure_many(
    names: Iterable[str],
    **kwargs: Any,
) -> list[EnsureResult]:
    return [ensure_tool(name, **kwargs) for name in names]
