#!/usr/bin/env python3
"""PreToolUse hook for Edit / Write / MultiEdit / NotebookEdit.

Two guards:
  1. Spec protection. The knowledge_base/ and system_flow/ folders are read-only
     source material and are ALWAYS blocked. CLAUDE.md, .claude/skills/**,
     .claude/settings.json and .claude/hooks/** are the project 'spec' and are
     blocked UNLESS the env var CHATBOT_EDIT_SPEC=1 is set (explicit spec work).
  2. Secret scan. Blocks writing content that looks like a hardcoded credential
     (AWS keys, private keys, OpenAI/Anthropic keys, obvious api_key = "...").
     Secrets belong in env / Pydantic Settings and encrypted at rest.

Fails OPEN on unexpected errors.
"""
import json
import os
import re
import sys

ALWAYS_PROTECTED = ("knowledge_base/", "system_flow/")
SPEC_PROTECTED = ("claude.md", ".claude/skills/", ".claude/settings.json", ".claude/hooks/")

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "OpenAI-style API key"),
    (re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\n]{12,}['\"]"),
     "hardcoded credential"),
]
# files where example/placeholder secrets are acceptable
SECRET_SCAN_EXEMPT = (".env.example", "secrets.md", "skill.md")


def deny(reason: str) -> None:
    sys.stderr.write("BLOCKED by guardrails: " + reason + "\n")
    sys.exit(2)


def norm(path: str) -> str:
    # lowercase + forward slashes; strip only a leading "./" (never the dot
    # in ".claude" — doing so would defeat the .claude/** spec guards).
    p = path.replace("\\", "/").lower()
    while p.startswith("./"):
        p = p[2:]
    return p


def gather_content(tool_input: dict) -> str:
    parts = []
    if isinstance(tool_input.get("content"), str):
        parts.append(tool_input["content"])
    if isinstance(tool_input.get("new_string"), str):
        parts.append(tool_input["new_string"])
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                parts.append(e["new_string"])
    return "\n".join(parts)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception as exc:
        sys.stderr.write(f"[guardrails] could not parse hook input: {exc}\n")
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(path, str) or not path:
        sys.exit(0)
    p = norm(path)

    try:
        # 1. spec protection
        if any(seg in p for seg in ALWAYS_PROTECTED):
            deny(
                f"'{path}' is read-only source material (knowledge_base/ or system_flow/). "
                "Build FROM the spec; never modify it."
            )
        _sentinel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".allow_spec_edit")
        _spec_ok = os.environ.get("CHATBOT_EDIT_SPEC") == "1" or os.path.exists(_sentinel)
        if not _spec_ok:
            base = p.rsplit("/", 1)[-1]
            if base == "claude.md" or any(seg in p for seg in SPEC_PROTECTED[1:]) or p.endswith("claude.md"):
                deny(
                    f"'{path}' is project spec (CLAUDE.md / skills / settings / hooks). "
                    "Agents build from the spec, not rewrite it. If this edit is "
                    "intentional spec work, set CHATBOT_EDIT_SPEC=1 for this session."
                )

        # 2. secret scan
        base = p.rsplit("/", 1)[-1]
        if base not in SECRET_SCAN_EXEMPT:
            content = gather_content(tool_input)
            for rx, label in SECRET_PATTERNS:
                if rx.search(content):
                    deny(
                        f"Possible hardcoded {label} in '{path}'. Secrets must come from "
                        "env / Pydantic Settings and be encrypted at rest (see "
                        "platform-foundations SecretBox). Use a placeholder in .env.example."
                    )
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"[guardrails] internal error, allowing: {exc}\n")
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
