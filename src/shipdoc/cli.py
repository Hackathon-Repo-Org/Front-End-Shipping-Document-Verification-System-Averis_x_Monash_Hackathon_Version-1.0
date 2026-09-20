"""M16 — argv only. Imports `pipeline`, `doctor` and `inspect`, nothing else."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shipdoc",
        description="Batch verification of shipping instructions against draft bills "
                    "of lading.",
        epilog="Start with:  python -m shipdoc doctor")
    p.add_argument("command", nargs="?", default="run",
                   choices=["run", "doctor", "inspect", "labels", "db"],
                   help="run (default) · doctor (health check) · inspect (one email) "
                        "· labels (approve proposed label mappings) · db (seed | counts | check)")
    p.add_argument("email_id", nargs="?", default=None,
                   help="for `inspect`: the email to show, e.g. email_013; "
                        "for `labels`: list, approve or reject")
    p.add_argument("label", nargs="?", default=None,
                   help="for `labels approve|reject`: the label, e.g. \"Containers:\"")
    p.add_argument("--by", default=None,
                   help="for `labels`: who is approving (defaults to the OS user)")
    p.add_argument("--note", default="",
                   help="for `labels`: why, recorded alongside the decision")
    p.add_argument("--source", default="dataset",
                   help="dataset directory, or an http(s):// server URL")
    p.add_argument("--config", default="config", help="directory holding the YAML config")
    p.add_argument("--out", default="output", help="directory for run artifacts")
    p.add_argument("--submit", action="store_true",
                   help="POST the submission to the scoreboard")
    p.add_argument("--server-url", default=None,
                   help="scoreboard URL; required with --submit when --source is local")
    p.add_argument("--no-llm", action="store_true",
                   help="skip the model entirely and use rules-only classification")
    p.add_argument("--quiet", action="store_true", help="suppress the capability banner")
    p.add_argument("--fast", action="store_true",
                   help="for `doctor`: skip the test-suite check")
    return p


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("shipdoc")
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    # Phase 12. Fill gaps from .env if one exists. A REAL environment variable
    # always wins — Azure injects App Settings as real env vars, and a stray .env
    # baked into an image must never shadow them.
    from shipdoc.infra.dotenv import load as load_dotenv
    load_dotenv()

    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        from shipdoc import doctor
        return doctor.run(Path.cwd(), fast=args.fast)

    if args.command == "db":
        from shipdoc import db_cli
        return db_cli.run(args.email_id or "check", source=args.source)

    if args.command == "labels":
        from shipdoc import labels_cli
        return labels_cli.run(args.email_id or "list", args.label,
                              out_dir=args.out, config_dir=args.config,
                              who=args.by, note=args.note)

    if args.command == "inspect":
        from shipdoc import inspect as inspect_mod
        if not args.email_id:
            print("shipdoc: inspect needs an email_id, e.g. "
                  "python -m shipdoc inspect email_013", file=sys.stderr)
            return 2
        return inspect_mod.run(args.email_id, source=args.source,
                               config_dir=args.config, no_llm=args.no_llm)

    from shipdoc import pipeline

    if not args.quiet:
        try:
            from shipdoc.config import load_config
            from shipdoc.infra import capabilities as caps
            cfg = load_config(Path(args.config))
            print(caps.banner(caps.probe(cfg, Path.cwd()), _version()), file=sys.stderr)
            print(file=sys.stderr)
        except Exception:
            pass          # a banner must never be the reason a run fails

    try:
        summary = pipeline.main_run(
            source=args.source, config_dir=args.config, out_dir=args.out,
            submit=args.submit, server_url=args.server_url, no_llm=args.no_llm,
        )
    except Exception as e:
        # A clean failure is a readable message and a non-zero exit, not a stack trace.
        print(f"shipdoc: {e}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
