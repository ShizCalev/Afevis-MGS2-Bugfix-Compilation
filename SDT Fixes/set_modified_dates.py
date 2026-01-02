from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict

import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock


# ==========================================================
# CONFIG
# ==========================================================
TARGET_DIR_REL = Path("SDT Fixes\\Staging")

# Threads
MAX_WORKERS = max((os.cpu_count() or 4) * 2, 4)

# Global Git path cache (lowercase -> canonical git path)
GIT_PATH_CACHE: Dict[str, str] | None = None

print_lock = Lock()


# ==========================================================
# WINDOWS FILETIME HELPERS
# ==========================================================
if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    CreateFileW.restype = wintypes.HANDLE

    SetFileTime = kernel32.SetFileTime
    SetFileTime.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    SetFileTime.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    def _unix_to_filetime(ts: int) -> wintypes.FILETIME:
        WINDOWS_TICK = 10_000_000
        SEC_TO_UNIX_EPOCH = 11_644_473_600
        filetime = int((ts + SEC_TO_UNIX_EPOCH) * WINDOWS_TICK)
        return wintypes.FILETIME(filetime & 0xFFFFFFFF, filetime >> 32)

    def set_fs_times(path: Path, ts_unix: int) -> None:
        """Set creation + modified + access times on Windows."""
        handle = CreateFileW(
            str(path),
            0x40000000,  # GENERIC_WRITE
            0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
            None,
            3,  # OPEN_EXISTING
            0,
            None,
        )

        if handle == wintypes.HANDLE(-1).value:
            raise OSError(f"Failed to open handle for {path}")

        ft = _unix_to_filetime(ts_unix)

        ok = SetFileTime(handle, ctypes.byref(ft), ctypes.byref(ft), ctypes.byref(ft))
        CloseHandle(handle)

        if not ok:
            raise OSError(f"SetFileTime failed on {path}")
else:
    def set_fs_times(path: Path, ts_unix: int) -> None:
        """Non-Windows: set modified and access times."""
        os.utime(path, (ts_unix, ts_unix))


# ==========================================================
# GIT HELPERS
# ==========================================================
def get_git_root() -> Path:
    """Return the git repo root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise SystemExit("Error: git is not installed or not on PATH.")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Error: not inside a git repository.\n{e.stderr}")

    root = Path(result.stdout.strip())
    if not root.exists():
        raise SystemExit(f"Error: git root path does not exist: {root}")
    return root


def build_git_path_cache(repo_root: Path) -> Dict[str, str]:
    """Build case-insensitive map of git-tracked paths."""
    global GIT_PATH_CACHE
    if GIT_PATH_CACHE is not None:
        return GIT_PATH_CACHE

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Error: git ls-files failed: {result.stderr.strip()}")

    cache: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        p = line.strip()
        if not p:
            continue
        cache[p.lower()] = p

    GIT_PATH_CACHE = cache
    return cache


def get_git_last_change_unix(repo_root: Path, path: Path) -> int | None:
    """
    Return Unix timestamp of last commit where file contents changed (add or modify),
    following renames, case-insensitive. Returns None if not tracked or no history.
    """
    cache = build_git_path_cache(repo_root)

    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        with print_lock:
            print(f"WARNING: {path} is not under repo root {repo_root}")
        return None

    rel_str = str(rel).replace("\\", "/")
    key = rel_str.lower()

    if key not in cache:
        with print_lock:
            print(f"WARNING: not tracked in git (no ls-files match): {rel_str}")
        return None

    canonical = cache[key]

    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--follow",
            "--diff-filter=AM",
            "--format=%ct",
            "--",
            canonical,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        with print_lock:
            print(
                f"WARNING: git log failed for {canonical}: "
                f"{result.stderr.strip()}"
            )
        return None

    out = result.stdout.strip()
    if not out:
        with print_lock:
            print(f"WARNING: no git content-change log for {canonical}")
        return None

    try:
        return int(out)
    except ValueError:
        with print_lock:
            print(f"WARNING: invalid git timestamp for {canonical}: {out!r}")
        return None


# ==========================================================
# WORKER
# ==========================================================
def process_file(repo_root: Path, path: Path) -> tuple[Path, bool]:
    """
    Worker for a single file.

    Returns (path, updated_ok)
    """
    ts = get_git_last_change_unix(repo_root, path)
    if ts is None:
        with print_lock:
            print(f"SKIP (no git ts): {path.relative_to(repo_root)}")
        return path, False

    try:
        set_fs_times(path, ts)
        with print_lock:
            print(f"SET  {path.relative_to(repo_root)} -> {ts}")
        return path, True
    except Exception as e:
        with print_lock:
            print(f"FAIL {path.relative_to(repo_root)} -> {e}")
        return path, False


# ==========================================================
# MAIN
# ==========================================================
def main() -> None:
    repo_root = get_git_root()
    print(f"Repo root: {repo_root}")

    target_dir = repo_root / TARGET_DIR_REL
    if not target_dir.is_dir():
        raise SystemExit(f"Error: target folder does not exist: {target_dir}")

    # Build cache once so threads only read it
    build_git_path_cache(repo_root)

    files = [p for p in target_dir.rglob("*") if p.is_file()]
    if not files:
        print(f"No files found under {target_dir}")
        return

    total = len(files)
    print(f"Found {total} file(s) under {target_dir}. Using {MAX_WORKERS} workers.\n")

    updated = 0
    skipped = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_file, repo_root, path): path for path in files
        }

        for future in as_completed(futures):
            _path, ok = future.result()
            if ok:
                updated += 1
            else:
                skipped += 1

    print("\nSummary:")
    print(f"  Total files:   {total}")
    print(f"  Updated times: {updated}")
    print(f"  Skipped:       {skipped}")


if __name__ == "__main__":
    main()
