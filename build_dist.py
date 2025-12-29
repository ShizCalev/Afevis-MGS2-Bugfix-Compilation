#!/usr/bin/env python3
import os
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Set, Tuple


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    input("Press Enter to exit...")
    sys.exit(1)


def find_git_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        fail("git is not installed or not in PATH.")
    except subprocess.CalledProcessError as e:
        print(e.stderr.strip(), file=sys.stderr)
        fail("You are not inside a git repository.")

    root = Path(result.stdout.strip())
    if not root.exists():
        fail(f"git root reported as {root}, but it does not exist.")
    return root


def collect_tree(root: Path) -> Tuple[Set[Path], Set[Path]]:
    files: Set[Path] = set()
    dirs: Set[Path] = {Path(".")}

    for dirpath, _, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        rel_dir = dirpath_p.relative_to(root)
        dirs.add(rel_dir)

        for name in filenames:
            rel_file = rel_dir / name if rel_dir != Path(".") else Path(name)
            files.add(rel_file)

    return files, dirs


def ensure_dirs(dest_root: Path, rel_dirs: Set[Path]) -> None:
    for rel_dir in rel_dirs:
        if rel_dir == Path("."):
            continue
        (dest_root / rel_dir).mkdir(parents=True, exist_ok=True)


def remove_extraneous(
    dest_root: Path,
    dest_files: Set[Path],
    dest_dirs: Set[Path],
    src_files: Set[Path],
    src_dirs: Set[Path],
) -> None:
    extra_files = dest_files - src_files
    for rel_file in extra_files:
        path = dest_root / rel_file
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            pass

    extra_dirs = list(dest_dirs - src_dirs)
    extra_dirs.sort(key=lambda p: len(p.parts), reverse=True)
    for rel_dir in extra_dirs:
        if rel_dir == Path("."):
            continue
        path = dest_root / rel_dir
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass


def sync_copy(src_root: Path, dest_root: Path) -> None:
    src_files, src_dirs = collect_tree(src_root)
    if dest_root.exists():
        dest_files, dest_dirs = collect_tree(dest_root)
    else:
        dest_files, dest_dirs = set(), {Path(".")}
        dest_root.mkdir(parents=True, exist_ok=True)

    ensure_dirs(dest_root, src_dirs)

    for rel_file in src_files:
        src = src_root / rel_file
        dest = dest_root / rel_file

        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()

        shutil.copy2(src, dest)

    remove_extraneous(dest_root, dest_files, dest_dirs, src_files, src_dirs)


def is_correct_symlink(dest: Path, src: Path) -> bool:
    if not dest.is_symlink():
        return False
    try:
        target = os.readlink(dest)
    except OSError:
        return False
    return Path(target) == src


def sync_symlink(src_root: Path, dest_root: Path) -> None:
    src_files, src_dirs = collect_tree(src_root)
    if dest_root.exists():
        dest_files, dest_dirs = collect_tree(dest_root)
    else:
        dest_files, dest_dirs = set(), {Path(".")}
        dest_root.mkdir(parents=True, exist_ok=True)

    ensure_dirs(dest_root, src_dirs)

    for rel_file in src_files:
        src = (src_root / rel_file).resolve()
        dest = dest_root / rel_file

        if dest.exists() or dest.is_symlink():
            if is_correct_symlink(dest,
