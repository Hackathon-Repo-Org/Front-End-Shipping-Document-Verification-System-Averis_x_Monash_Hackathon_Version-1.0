"""M03b — load `.env`, if there is one. Phase 12.

    A REAL ENVIRONMENT VARIABLE ALWAYS WINS.

That is the whole design, and it is not a preference. Azure App Settings and
Container Apps secrets arrive as real environment variables. If a `.env` file were
allowed to override them, a stray file baked into an image — a developer's copy, a
`COPY . .` in a Dockerfile — would silently point the deployed service at the wrong
database or the wrong API key, and every symptom would point somewhere else.

So: `.env` fills GAPS. It never overwrites.

stdlib only. `python-dotenv` is a fine library, but this is thirty lines and adding a
dependency to the base install for it would mean the offline, air-gapped tier grows a
package it does not need.

Not supported, deliberately: variable interpolation (`${HOME}/x`), multi-line values,
and `export` semantics beyond stripping the keyword. Each is a small feature that
turns a config file into a scripting language; a key and a connection string need
none of them.
"""
from __future__ import annotations

import os
from pathlib import Path

FILENAME = ".env"


def _strip_quotes(value: str) -> str:
    """Remove ONE matched pair of surrounding quotes.

    People paste keys with quotes because shells need them. Inside a .env the quotes
    are not syntax, and a key read as `"sk-abc"` fails authentication with a message
    that does not mention quoting.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(text: str) -> dict[str, str]:
    """`KEY=value` per line. `#` comments, blank lines and `export ` are tolerated."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue                      # not an assignment; ignore rather than fail
        key = key.strip()
        if not key:
            continue
        # An inline comment is only a comment when it follows whitespace — a `#`
        # can legitimately appear inside a password.
        value = value.strip()
        out[key] = _strip_quotes(value)
    return out


def load(path: Path | str | None = None, *, override: bool = False) -> list[str]:
    """Fill missing environment variables from `.env`. Returns the NAMES it set.

    Names only, never values: this return value is printed, and printing the values
    is how a key reaches a terminal recording or a CI log.

    `override=False` is the contract. The parameter exists for tests; production
    code must never pass True.
    """
    p = Path(path) if path is not None else Path.cwd() / FILENAME
    if not p.is_file():
        return []
    try:
        pairs = parse(p.read_text(encoding="utf-8"))
    except OSError:
        return []

    applied: list[str] = []
    for key, value in pairs.items():
        if not override and os.environ.get(key):
            continue                      # a real environment variable wins
        os.environ[key] = value
        applied.append(key)
    return applied
