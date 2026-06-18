#!/usr/bin/env python3
"""PreToolUse hook for Bash/PowerShell.

Blocks (exit 2 => fed back to Claude as an error):
  - The entire git WRITE path: add / commit / push and all history/state-mutating
    subcommands. All version control is the USER's job. Read-only git is allowed.
  - Destructive filesystem ops: recursive force deletes (rm -rf, Remove-Item -Recurse -Force).

Fails OPEN on unexpected errors (a broken guardrail must not brick the agent),
but prints a notice to stderr so the failure is visible.
"""
import json
import re
import sys

# git subcommands that only READ — everything else under `git` is blocked.
GIT_READONLY = {
    "status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files",
    "blame", "config", "describe", "shortlog", "reflog", "tag", "cat-file",
    "rev-list", "name-rev", "whatchanged", "grep", "help", "version", "fetch",
}
# Of those, a few are read-only ONLY without mutating flags.
GIT_READONLY_NO_WRITE_FLAGS = {
    "branch": ("-d", "-D", "--delete", "-m", "-M", "--move", "--force"),
    "tag": ("-d", "--delete", "-f", "--force"),
    "config": (),  # `git config` without args reads; with a value it writes. Keep simple: allow gets only.
    "remote": ("add", "remove", "rm", "set-url", "rename"),
    "fetch": (),
}

GIT_RE = re.compile(r"(?:^|[\s;&|(])git\s+(?:-[-\w=]+\s+)*([a-z][\w-]*)", re.IGNORECASE)
RM_RF_RE = re.compile(r"(?:^|[\s;&|(])rm\s+(?:-[-\w]*\s+)*-{0,2}[a-z-]*\b", re.IGNORECASE)
RM_RECURSIVE_FORCE = re.compile(r"(?:^|[\s;&|(])rm\s+(?=[^\n;|&]*\br)(?=[^\n;|&]*\bf)-[a-z]+", re.IGNORECASE)
PS_REMOVE_RECURSE_FORCE = re.compile(
    r"Remove-Item\b(?=[^\n;|]*-Recurse)(?=[^\n;|]*-Force)", re.IGNORECASE
)


def deny(reason: str) -> None:
    sys.stderr.write("BLOCKED by guardrails: " + reason + "\n")
    sys.exit(2)


def check_git(cmd: str) -> None:
    for m in GIT_RE.finditer(cmd):
        sub = m.group(1).lower()
        if sub not in GIT_READONLY:
            deny(
                f"'git {sub}' is not permitted. All version control (add/commit/push/"
                "branch/merge/reset/etc.) is the user's responsibility. Only read-only "
                "git (status, log, diff, show, ...) is allowed. Ask the user to run git "
                "commands themselves (e.g. with the `!` prefix)."
            )
        # read-only command but used with a mutating flag?
        bad_flags = GIT_READONLY_NO_WRITE_FLAGS.get(sub)
        if bad_flags:
            tail = cmd[m.end():]
            tail_head = tail.split(";")[0].split("&&")[0].split("|")[0]
            for flag in bad_flags:
                if re.search(r"(?:^|\s)" + re.escape(flag) + r"(?:$|[\s=])", tail_head):
                    deny(
                        f"'git {sub} {flag}' mutates the repo and is not permitted. "
                        "Leave version control to the user."
                    )


def check_destructive_fs(cmd: str) -> None:
    if RM_RECURSIVE_FORCE.search(cmd) or re.search(r"\brm\s+-rf\b|\brm\s+-fr\b", cmd, re.IGNORECASE):
        deny(
            "Recursive force delete (rm -rf) is not permitted. Remove specific paths "
            "explicitly, or ask the user to confirm the deletion."
        )
    if PS_REMOVE_RECURSE_FORCE.search(cmd):
        deny(
            "Remove-Item -Recurse -Force is not permitted. Delete specific items "
            "explicitly, or ask the user to confirm."
        )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception as exc:  # fail open
        sys.stderr.write(f"[guardrails] could not parse hook input: {exc}\n")
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)
    try:
        check_git(cmd)
        check_destructive_fs(cmd)
    except SystemExit:
        raise
    except Exception as exc:  # fail open on internal error
        sys.stderr.write(f"[guardrails] internal error, allowing: {exc}\n")
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
