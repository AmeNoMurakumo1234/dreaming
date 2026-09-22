#!/usr/bin/env python3
"""PreCompact hook: sleep. Never exits non-zero - compaction must proceed whatever happens here."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from dreaming import cli
    cli.main(["sleep"])
except BaseException as exc:  # noqa: BLE001 - a hook must not die
    print("dreaming: sleep failed (compaction proceeds): %s" % exc)
sys.exit(0)
