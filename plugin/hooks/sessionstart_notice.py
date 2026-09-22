#!/usr/bin/env python3
"""SessionStart(startup|resume) hook: one line if dreams await promotion. Never exits non-zero."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from dreaming import cli
    cli.main(["notice"])
except BaseException as exc:  # noqa: BLE001 - a hook must not die
    print("dreaming: notice skipped: %s" % exc, file=sys.stderr)
sys.exit(0)
