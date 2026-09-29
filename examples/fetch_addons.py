"""Download the pinned test framework addons into the example projects.

GUT and gdUnit4 are MIT-licensed third-party projects; their addons are not
committed here. Each addon folder keeps its own LICENSE file. Needs `git`.

    python examples/fetch_addons.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (example dir, repo URL, tag, addon path inside the repo)
ADDONS = [
    ("gut", "https://github.com/bitwes/Gut", "v9.6.1", "addons/gut"),
    ("gdunit4", "https://github.com/godot-gdunit-labs/gdUnit4", "v6.2.1", "addons/gdUnit4"),
]


def git(*args: str, cwd: Path | None = None) -> None:
    # core.longpaths: gdUnit4 has paths past the Windows 260-character limit.
    subprocess.run(["git", "-c", "core.longpaths=true", *args], cwd=cwd, check=True)


def main() -> int:
    for example, url, tag, addon in ADDONS:
        dest = HERE / example / addon
        if dest.is_dir():
            print(f"{example}: {addon} already present, skipped")
            continue
        with tempfile.TemporaryDirectory(prefix="gobreak-addon-") as tmp:
            clone = Path(tmp) / "repo"
            print(f"{example}: fetching {url} {tag}")
            git("clone", "--quiet", "--depth", "1", "--branch", tag,
                "--filter=blob:none", "--sparse", url, str(clone))
            git("sparse-checkout", "set", addon, cwd=clone)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(clone / addon, dest)
        print(f"{example}: {addon} -> {dest}")
    print("next: run `godot --headless --path examples/<name> --import` once per example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
