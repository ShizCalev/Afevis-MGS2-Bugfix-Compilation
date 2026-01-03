from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> None:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    else:
        root = Path.cwd()

    if not root.exists() or not root.is_dir():
        print(f"[ERROR] Directory does not exist: {root}")
        sys.exit(1)

    now = time.time()
    count = 0

    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".ctxr"):
                file_path = Path(dirpath) / name
                try:
                    os.utime(file_path, (now, now))
                    count += 1
                except Exception as exc:
                    print(f"[WARN] Failed to update: {file_path} :: {exc}")

    print(f"[DONE] Updated modified time on {count} .ctxr files under: {root}")


if __name__ == "__main__":
    main()
