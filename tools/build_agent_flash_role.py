#!/usr/bin/env python3
"""Build the compact, deterministic role payload used by agent_flash_role."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import re
import sys
import textwrap
import zlib
from pathlib import Path
from typing import Mapping


ROLE_ORDER = (
    "sdr",
    "account",
    "smm",
    "copywriter",
    "support",
    "faq",
    "bookkeeper",
    "finanalyst",
    "recruiter",
    "onboarding",
    "assistant",
    "docs",
    "pm",
    "analyst",
)
BLOCK_PATTERN = re.compile(
    r"(?ms)^    # BEGIN GENERATED ROLE PAYLOAD\n.*?^    # END GENERATED ROLE PAYLOAD\n"
)
PAYLOAD_CHUNK = re.compile(r'^        ("[A-Za-z0-9+/=]+")$', re.MULTILINE)
ROLE_NAME = re.compile(r"(?m)^# agent: (.+)$")
ROLE_ID = re.compile(r"(?m)^# role_id: ([a-z0-9_-]+)$")
INSTRUCTION_MARKER = "## Системная инструкция"


def load_roles(root: Path) -> dict[str, dict[str, str]]:
    roles: dict[str, dict[str, str]] = {}
    for expected_id in ROLE_ORDER:
        path = root / "agents" / f"{expected_id}.md"
        text = path.read_text(encoding="utf-8")
        name_match = ROLE_NAME.search(text)
        id_match = ROLE_ID.search(text)
        if name_match is None or id_match is None or INSTRUCTION_MARKER not in text:
            raise ValueError(f"invalid role source: {path}")
        role_id = id_match.group(1)
        if role_id != expected_id:
            raise ValueError(f"role id mismatch in {path}: {role_id}")
        instruction = text.split(INSTRUCTION_MARKER, 1)[1].strip()
        if not instruction:
            raise ValueError(f"empty role instruction: {path}")
        roles[role_id] = {"name": name_match.group(1).strip(), "instruction": instruction}
    return roles


def canonical_payload(roles: Mapping[str, Mapping[str, str]]) -> bytes:
    ordered = {role_id: dict(roles[role_id]) for role_id in ROLE_ORDER}
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def render_payload_block(roles: Mapping[str, Mapping[str, str]]) -> str:
    raw = canonical_payload(roles)
    encoded = base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")
    chunks = textwrap.wrap(encoded, width=100)
    quoted = "\n".join(f'        "{chunk}"' for chunk in chunks)
    digest = hashlib.sha256(raw).hexdigest()
    return (
        "    # BEGIN GENERATED ROLE PAYLOAD\n"
        f"    # roles-sha256: {digest}\n"
        "    ROLE_PAYLOAD = (\n"
        f"{quoted}\n"
        "    )\n"
        "    # END GENERATED ROLE PAYLOAD\n"
    )


def render_expert_source(source: str, roles: Mapping[str, Mapping[str, str]]) -> str:
    replacement = render_payload_block(roles)
    rendered, count = BLOCK_PATTERN.subn(replacement, source)
    if count != 1:
        raise ValueError("agent_flash_role must contain exactly one generated payload block")
    return rendered


def extract_roles(source: str) -> dict[str, dict[str, str]]:
    match = BLOCK_PATTERN.search(source)
    if match is None:
        raise ValueError("generated role payload block was not found")
    chunks = [ast.literal_eval(value) for value in PAYLOAD_CHUNK.findall(match.group(0))]
    if not chunks:
        raise ValueError("generated role payload is empty")
    raw = zlib.decompress(base64.b64decode("".join(chunks)))
    digest_match = re.search(r"roles-sha256: ([0-9a-f]{64})", match.group(0))
    if digest_match is None or hashlib.sha256(raw).hexdigest() != digest_match.group(1):
        raise ValueError("generated role payload digest mismatch")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("generated role payload must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    expert_path = root / "experts" / "agent_flash_role.py"
    source = expert_path.read_text(encoding="utf-8")
    rendered = render_expert_source(source, load_roles(root))
    if args.check:
        if rendered != source:
            print(f"stale generated expert: {expert_path}", file=sys.stderr)
            return 1
        print(f"verified generated expert: {expert_path}")
        return 0
    expert_path.write_text(rendered, encoding="utf-8")
    print(f"updated generated expert: {expert_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
