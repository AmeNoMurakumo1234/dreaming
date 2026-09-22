#!/usr/bin/env python3
"""SessionStart(compact) hook: re-seed the fresh context from the newest brief. Never exits non-zero."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from dreaming import cli
    cli.main(["reseed"])
except BaseException as exc:  # noqa: BLE001 - a hook must not die
    print("dreaming: reseed skipped: %s" % exc)
sys.exit(0)
