#!/usr/bin/env python3
"""cli.py - the plugin's entry points.

    python -m dreaming.cli sleep      # PreCompact hook, hook JSON on stdin; always exit 0
    python -m dreaming.cli reseed     # SessionStart(compact) hook; prints additionalContext JSON
    python -m dreaming.cli notice     # SessionStart(startup|resume) hook; one line if dreams await
    python -m dreaming.cli dream --transcript P [--agent A] [--engine E] [--dry-run]
    python -m dreaming.cli list [--agent A]
    python -m dreaming.cli config     # the effective config and where each layer came from

Run from the plugin directory (the one holding the `dreaming` package), or with it on sys.path.
"""
import argparse
import json
import os
import sys

from . import config as _config, engines as se, identity, sleep as sl


def _read_hook_json(args):
    if args.hook_json:
        return json.loads(args.hook_json)
    try:
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    except Exception:
        raw = ""
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load(args, hook):
    cwd = args.project or hook.get("cwd") or os.getcwd()
    env = dict(os.environ)
    if getattr(args, "agent", None):
        env["DREAMING_AGENT"] = args.agent
    cfg = _config.load(project_dir=cwd, env=env, home=args.home)
    return cfg, cwd, env


def _pick_engine(cfg, name):
    if name == "mechanical":
        return None, "mechanical"
    if name in ("openai_compatible", "claude"):
        return se.build_engine(dict(cfg, engines=[name, "mechanical"]))
    return se.build_engine(cfg)


def _run(cfg, args, transcript, session_id, out_root, agent, index_text, engine, engine_name):
    return sl.run_sleep(transcript, agent=agent, session_id=session_id, out_root=out_root,
                        engine=engine, engine_name=engine_name,
                        include_thinking=bool(getattr(args, "include_thinking", False) or cfg.get("include_thinking")),
                        budget_seconds=int(getattr(args, "budget", None) or cfg.get("budget_seconds") or 3000),
                        index_text=index_text, chunk_chars=int(cfg.get("chunk_chars") or 60000),
                        cap_chars=int(cfg.get("cap_chars") or 400000),
                        result_head=int(cfg.get("result_head") or 400))


def cmd_sleep(args):
    """PreCompact entry. Prints one summary line; ALWAYS returns 0."""
    try:
        hook = _read_hook_json(args)
        cfg, cwd, env = _load(args, hook)
        if not cfg.get("enabled", True):
            return 0
        transcript = args.transcript or hook.get("transcript_path")
        session_id = args.session or hook.get("session_id") or ""
        res = identity.resolve(cfg, cwd, transcript=transcript, env=env, hook=hook)
        if res.scratch:
            print("dreaming: NOT writing to a store (%s)" % res.reason)
        if not transcript or not os.path.isfile(str(transcript)):
            raise FileNotFoundError("transcript not found: %r" % transcript)
        engine, engine_name = _pick_engine(cfg, args.engine)
        index_text = "" if res.scratch else identity.index_text(res.store, cfg)
        out = _run(cfg, args, transcript, session_id, res.store, res.agent, index_text, engine, engine_name)
        print("dreaming: %s | engine %s | lessons %d | tensions %d%s" % (
            out["folder"], engine_name, out["lessons"], out["tensions"],
            (" | degraded: " + "; ".join(out["degraded"])) if out["degraded"] else ""))
    except Exception as exc:
        print("dreaming: sleep failed (compaction proceeds): %s" % exc)
    return 0


def _hook_context(text):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})


def cmd_reseed(args):
    """SessionStart(compact) entry. Prints the brief as additionalContext; ALWAYS returns 0."""
    try:
        hook = _read_hook_json(args)
        cfg, cwd, env = _load(args, hook)
        if not cfg.get("enabled", True):
            return 0
        session_id = args.session or hook.get("session_id") or ""
        res = identity.resolve(cfg, cwd, transcript=hook.get("transcript_path"), env=env, hook=hook)
        roots = [] if res.scratch else [res.store]
        roots.append(identity.scratch_root(hook, cfg))
        folder = next((f for f in (sl.newest_dream_for(r, session_id) for r in roots) if f), None)
        if not folder:
            return 0
        with open(os.path.join(folder, "brief.md"), "r", encoding="utf-8", errors="replace") as fh:
            brief = fh.read()
        mine = next((d for d in sl.dreams_awaiting(os.path.dirname(os.path.dirname(folder)))
                     if os.path.normcase(d["path"]) == os.path.normcase(folder)), None)
        staged = (" - %d lesson(s), %d tension(s) staged" % (mine["lessons"], mine["tensions"])) if mine else ""
        tail = ("\n\n(dreaming re-seed: this brief was written by the sleep step before compaction. "
                "Dream folder: %s%s. Promote or delete it at your next wake - see the dreaming-promote skill.)"
                % (folder, staged))
        print(_hook_context(brief + tail))
    except Exception as exc:
        print("dreaming: reseed skipped: %s" % exc)
    return 0


def cmd_notice(args):
    """SessionStart(startup|resume) entry. One line if dreams await; ALWAYS returns 0."""
    try:
        hook = _read_hook_json(args)
        cfg, cwd, env = _load(args, hook)
        if not cfg.get("enabled", True):
            return 0
        res = identity.resolve(cfg, cwd, transcript=hook.get("transcript_path"), env=env, hook=hook)
        if res.scratch:
            return 0
        dreams = sl.dreams_awaiting(res.store, stale_days=int(cfg.get("stale_days") or 14))
        if not dreams:
            return 0
        lines = ["dreaming: %d dream(s) awaiting promotion in %s (agent %s). Read them in your first "
                 "coherence pass and promote or delete each folder - the dreaming-promote skill is the "
                 "procedure." % (len(dreams), res.store, res.agent)]
        for d in dreams:
            lines.append("  %s - %d lesson(s), %d tension(s)%s" % (
                d["name"], d["lessons"], d["tensions"], "  STALE" if d["stale"] else ""))
        print(_hook_context("\n".join(lines)))
    except Exception as exc:
        print("dreaming: notice skipped: %s" % exc)
    return 0


def cmd_dream(args):
    session_id = args.session or os.path.basename(args.transcript).split(".")[0]
    hook = {"transcript_path": args.transcript, "session_id": session_id}
    cfg, cwd, env = _load(args, hook)
    res = identity.resolve(cfg, cwd, transcript=args.transcript, env=env, hook=hook)
    print("identity:", res.reason)
    to_scratch = bool(args.dry_run or res.scratch)
    out_root = identity.scratch_root(hook, cfg) if to_scratch else res.store
    if args.dry_run:
        print("dreaming into scratch:", out_root)
    engine, engine_name = _pick_engine(cfg, args.engine)
    print("engine:", engine_name)
    index_text = "" if to_scratch else identity.index_text(res.store, cfg)
    out = _run(cfg, args, args.transcript, session_id, out_root, res.agent, index_text, engine, engine_name)
    print(json.dumps({k: v for k, v in out.items() if k != "stages"}, indent=1))
    print("stages:", json.dumps(out["stages"]))
    return 0


def cmd_list(args):
    cfg, cwd, env = _load(args, {})
    res = identity.resolve(cfg, cwd, transcript=None, env=env)
    if res.scratch:
        print("no store:", res.reason)
        return 1
    dreams = sl.dreams_awaiting(res.store, stale_days=int(cfg.get("stale_days") or 14))
    if not dreams:
        print("no dreams awaiting promotion for %s in %s" % (res.agent, res.store))
        return 0
    for d in dreams:
        print("%s  -  %d lesson(s), %d tension(s), %.1f days%s" % (
            d["name"], d["lessons"], d["tensions"], d["age_days"], "  STALE" if d["stale"] else ""))
    return 0


def cmd_config(args):
    cfg, cwd, env = _load(args, {})
    print(json.dumps(cfg, indent=1, default=str))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dreaming", description="Sleep at compaction.")
    parser.add_argument("--project", help="project dir (default: hook cwd, else the current dir)")
    parser.add_argument("--home", help="home dir for ~/.dreaming/config.json (tests)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--agent")
        p.add_argument("--engine", default="auto", choices=("auto", "openai_compatible", "claude", "mechanical"))
        p.add_argument("--include-thinking", action="store_true")
        p.add_argument("--budget", type=int)
        p.add_argument("--session")
        p.add_argument("--transcript")
        p.add_argument("--hook-json")

    for name in ("sleep", "reseed", "notice"):
        common(sub.add_parser(name))
    d = sub.add_parser("dream")
    common(d)
    d.add_argument("--dry-run", action="store_true")
    l = sub.add_parser("list")
    l.add_argument("--agent")
    sub.add_parser("config")
    args = parser.parse_args(argv)
    if args.cmd == "dream" and not args.transcript:
        parser.error("dream needs --transcript")
    return {"sleep": cmd_sleep, "reseed": cmd_reseed, "notice": cmd_notice, "dream": cmd_dream,
            "list": cmd_list, "config": cmd_config}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
