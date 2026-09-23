#!/usr/bin/env python3
"""SessionEnd hook: decide fast, hand the sleep to a detached child, exit 0. Claude Code caps this
hook at 60 s, so the sleep itself never runs here."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from dreaming import cli
    cli.main(["sessionend"])
except BaseException as exc:  # noqa: BLE001 - a hook must not die
    print("dreaming: exit sleep failed: %s" % exc)
sys.exit(0)
