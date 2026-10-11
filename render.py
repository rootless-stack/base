#!/usr/bin/env python3
"""Render a stack's config tree.

    render.py SRC DST VARS.toml SECRETS_DIR

Copies SRC to DST.  Files ending in .j2 are rendered with Jinja2 (and lose
the suffix); everything else is copied as is, mode included.  Templates
see the variables from VARS.toml, `secret.<name>` for every file in
SECRETS_DIR, and the filter `user | subuid(n)`: the host uid that
container uid n of that rootless user maps to (/etc/subuid).

Needs Python 3.11+ and Jinja2 (python3-jinja2 on Debian, Ubuntu, Fedora).
"""

import shutil
import sys
import tomllib
from pathlib import Path

import jinja2


def subuid(user: str, uid: int) -> int:
    """Host uid of container uid `uid` (> 0) in `user`'s default rootless mapping."""
    for line in Path("/etc/subuid").read_text().splitlines():
        name, start, count = line.split(":")
        if name == user and 0 < uid <= int(count):
            return int(start) + uid - 1
    raise ValueError(f"no /etc/subuid range of {user} covers uid {uid}")


def main(src: Path, dst: Path, vars_file: Path, secrets_dir: Path) -> None:
    context = tomllib.loads(vars_file.read_text())
    context["secret"] = {f.name: f.read_text().rstrip("\n") for f in secrets_dir.iterdir() if f.is_file()}
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(src),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,  # as Ansible's template module
    )
    env.filters["subuid"] = subuid
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copymode(src, dst)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if path.is_dir():
            # The source's mode, not the umask: containers read some of these
            # as other uids (dovecot's vmail reads its Sieve scripts).
            (dst / rel).mkdir(parents=True, exist_ok=True)
            shutil.copymode(path, dst / rel)
        elif path.suffix == ".j2":
            out = dst / rel.with_suffix("")
            out.write_text(env.get_template(rel.as_posix()).render(context))
            shutil.copymode(path, out)
        else:
            shutil.copy2(path, dst / rel)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*map(Path, sys.argv[1:]))
