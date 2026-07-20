"""Command line interface for llms-txt-kit.

    llms-txt generate --name "Acme Coffee" --description "Specialty roaster." \
        --url acme.coffee --link "Menu|/menu|What we pour" -o llms.txt

    llms-txt generate --from-sitemap acme.coffee --name "Acme Coffee" \
        --description "Specialty roaster." --titles

    llms-txt validate acme.coffee
    llms-txt validate ./llms.txt --strict --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, from_sitemap, generate, validate, validate_url

_MARK = {"pass": "PASS", "warning": "WARN", "error": "FAIL"}


def _split_link(spec: str):
    parts = [p.strip() for p in str(spec).split("|")]
    parts += ["", "", ""]
    return parts[0], parts[1], parts[2]


def _cmd_generate(args) -> int:
    if args.from_sitemap:
        try:
            text = from_sitemap(args.from_sitemap, args.name, args.description,
                                limit=args.limit, include_titles=args.titles,
                                credit=not args.no_credit)
        except Exception as e:                              # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 2
    else:
        links = [_split_link(s) for s in (args.link or [])]
        optional = [_split_link(s) for s in (args.optional or [])]
        try:
            text = generate(args.name, args.description, links=links,
                            optional_links=optional, url=args.url or "",
                            credit=not args.no_credit)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output} ({len(text.encode())} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def _cmd_validate(args) -> int:
    target = args.target
    path = Path(target)
    if path.exists() and path.is_file():
        report = validate(path.read_text(encoding="utf-8", errors="replace"), source=str(path))
    else:
        report = validate_url(target, timeout=args.timeout)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"\n{report.source}")
        print("-" * min(len(report.source), 72))
        for c in report.checks:
            print(f"  {_MARK[c.status]:<5} {c.label}"
                  + (f"  —  {c.detail}" if c.detail else ""))
        n_err, n_warn = len(report.errors), len(report.warnings)
        print(f"\n{len(report.passed)}/{len(report.checks)} checks passed"
              f" · {n_err} error(s), {n_warn} warning(s)\n")
    if report.errors:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="llms-txt",
        description="Generate and validate llms.txt files (https://llmstxt.org).")
    p.add_argument("--version", action="version", version=f"llms-txt-kit {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="create an llms.txt")
    g.add_argument("--name", required=True, help="site or project name (the H1)")
    g.add_argument("--description", required=True, help="one-paragraph summary")
    g.add_argument("--url", default="", help="canonical site URL")
    g.add_argument("--link", action="append", metavar="'Title|URL|note'",
                   help="a key page; repeatable")
    g.add_argument("--optional", action="append", metavar="'Title|URL|note'",
                   help="a page for the '## Optional' section; repeatable")
    g.add_argument("--from-sitemap", metavar="URL",
                   help="build from a sitemap.xml instead of --link flags")
    g.add_argument("--limit", type=int, default=25,
                   help="max links when using --from-sitemap (default 25)")
    g.add_argument("--titles", action="store_true",
                   help="with --from-sitemap: fetch each page for real titles/descriptions")
    g.add_argument("--no-credit", action="store_true", help="omit the credit comment")
    g.add_argument("-o", "--output", metavar="FILE", help="write to FILE (default stdout)")
    g.set_defaults(func=_cmd_generate)

    v = sub.add_parser("validate", help="validate a local file or a live site")
    v.add_argument("target", help="domain, URL, or path to a local llms.txt")
    v.add_argument("--json", action="store_true", help="machine-readable output")
    v.add_argument("--strict", action="store_true", help="exit 1 on warnings too (CI)")
    v.add_argument("--timeout", type=float, default=15.0, help="fetch timeout in seconds")
    v.set_defaults(func=_cmd_validate)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main())
