#!/usr/bin/env python3
"""Stop hook: remind the agent to verify before claiming completion.

Fires once per stop sequence (guarded by stop_hook_active to avoid loops).
Exit 2 returns the message to Claude and asks it to confirm verification; on the
next stop attempt stop_hook_active is true and we allow the stop.

This is a REMINDER, not an auto-runner. Per-service skills list the exact
lint/typecheck/test commands; automated execution is deferred until the repo and
toolchains exist.
"""
import json
import sys

REMINDER = (
    "Before stopping, confirm the guardrails were honored:\n"
    "  1. VERIFY: for any code you changed, did you run the service's lint + "
    "typecheck + tests and see them pass (paste real output)? Backend logic is "
    "test-first (TDD) and must include multi-tenant isolation + RBAC tests.\n"
    "  2. SCOPE: did you stay within the service folder + services/common contracts, "
    "and avoid editing the spec (knowledge_base/, system_flow/, CLAUDE.md, skills)?\n"
    "  3. GIT: you must NOT have run git add/commit/push — version control is the user's.\n"
    "If no code changed (e.g. planning/Q&A only), it is fine to stop now. Otherwise "
    "address the above, then stop."
)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("stop_hook_active"):
        sys.exit(0)  # already reminded once this sequence; let it stop
    sys.stderr.write(REMINDER + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
