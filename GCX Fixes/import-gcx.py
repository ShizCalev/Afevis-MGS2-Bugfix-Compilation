import os
import sys
import hashlib
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Windows timestamp stuff
import ctypes
from ctypes import wintypes

# ==========================================================
# CONFIGURATION
# ==========================================================
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

HASH_FILE = SCRIPT_DIR / "original-sha1-hashes.txt"
IMPORT_SCRIPT_REL = Path("external/mgs_gcx_editor/_gcx_import_mgs2.py")
DIST_DIR_REL = Path("dist/assets/gcx")
THREADS = max(os.cpu_count() or 1, 1)  # Auto-detect CPU threads

# Global Git path cache (lowercase -> canonical git path)
GIT_PATH_CACHE: dict[str, str] | None = None

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

    def set_windows_times(path: Path, ts_unix: int) -> None:
        """Set creation + modified + access times on Windows."""
        handle = CreateFileW(
            str(path),
            0x40000000,
            0x00000001 | 0x00000002,
            None,
            3,
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
    def set_windows_times(path: Path, ts_unix: int) -> None:
        """Non-Windows fallback: set mtime/atime only."""
        os.utime(path, (ts_unix, ts_unix))


# ==========================================================
# HELPERS
# ==========================================================
print_lock = Lock()

def calc_sha1(path: Path) -> str:
    """Compute SHA1 hash for a file."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_hash_list(file_path: Path) -> list[tuple[str, str]]:
    """Load list of (relative_path, sha1) from text file."""
    if not file_path.exists():
        sys.exit(f"Error: Hash list not found: {file_path}")
    entries: list[tuple[str, str]] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "," not in line:
                continue
            rel_path, sha1 = line.split(",", 1)
            entries.append((rel_path.strip(), sha1.strip().lower()))
    return entries


def get_python_cmd() -> str:
    """Return 'py' or 'python' depending on availability."""
    if shutil.which("py"):
        return "py"
    if shutil.which("python"):
        return "python"
    sys.exit("Error: Python launcher not found. Ensure 'py' or 'python' is on PATH.")


def get_git_root() -> Path:
    """Get git repo root, or die."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        root = Path(result.stdout.strip())
        if not root.exists():
            raise RuntimeError
        return root
    except Exception:
        sys.exit("Error: not inside a git repository (git rev-parse failed).")


def build_git_path_cache(repo_root: Path) -> dict[str, str]:
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
        sys.exit(f"Error: git ls-files failed: {result.stderr.strip()}")

    cache: dict[str, str] = {}
    for line in result.stdout.splitlines():
        p = line.strip()
        if not p:
            continue
        cache[p.lower()] = p

    GIT_PATH_CACHE = cache
    return cache


def get_git_last_change_unix(repo_root: Path, path: Path) -> int | None:
    """
    Return Unix timestamp of last commit where file contents changed (A/M),
    following renames, case-insensitive.
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
            print(f"WARNING: case-insensitive git match not found for {rel_str}")
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


def import_and_copy_gcx(
    python_cmd: str,
    repo_root: Path,
    script_path: Path,
    gcx_path: Path,
    rel_csv_path: str,
    dist_root: Path,
) -> tuple[str, int]:
    """
    Run GCX import and copy the result into dist/assets/gcx preserving structure
    relative to the CSV path. Then set GCX timestamps to the CSV's Git last-change time.
    """
    result = subprocess.run(
        [python_cmd, str(script_path), str(gcx_path)],
        text=True,
    )
    code = result.returncode

    if code == 0:
        rel_gcx_path = Path(rel_csv_path).with_suffix(".gcx")
        dest_path = dist_root / rel_gcx_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(gcx_path, dest_path)
            # Get Git timestamp of the CSV (last content change)
            csv_abs = SCRIPT_DIR / rel_csv_path
            ts = get_git_last_change_unix(repo_root, csv_abs)
            if ts is not None:
                try:
                    set_windows_times(dest_path, ts)
                except Exception as e:
                    with print_lock:
                        print(f"    [TIME FAILED] {dest_path} -> {e}")
            with print_lock:
                print(f"    Copied -> {dest_path.relative_to(repo_root)}")
        except Exception as e:
            with print_lock:
                print(f"    [COPY FAILED] {gcx_path} -> {e}")
            code = 2

    return (rel_csv_path, code)


# ==========================================================
# MAIN
# ==========================================================
def main():
    # Resolve repo root via git
    repo_root = get_git_root()
    # Build git path cache up-front so threads only read it
    build_git_path_cache(repo_root)

    script_path = repo_root / IMPORT_SCRIPT_REL
    dist_root = repo_root / DIST_DIR_REL

    if not script_path.exists():
        sys.exit(f"Error: Import script not found at {script_path}")

    entries = load_hash_list(HASH_FILE)
    python_cmd = get_python_cmd()
    differences: list[tuple[str, str, str]] = []
    import_targets: list[tuple[Path, str]] = []
    import_failed = False

    print(f"Detected {THREADS} CPU thread(s).")
    print(f"Verifying {len(entries)} CSV hashes...\n")

    # Step 1: Check hashes and queue changed CSVs
    for rel_path, old_sha1 in entries:
        csv_path = SCRIPT_DIR / rel_path
        if not csv_path.exists():
            with print_lock:
                print(f"[MISSING] {rel_path}")
            continue

        new_sha1 = calc_sha1(csv_path)
        if new_sha1 != old_sha1:
            differences.append((rel_path, old_sha1, new_sha1))
            with print_lock:
                print(f"[CHANGED] {rel_path}")
            gcx_path = csv_path.with_suffix(".gcx")
            if gcx_path.exists():
                import_targets.append((gcx_path, rel_path))
            else:
                with print_lock:
                    print(f"    [MISSING GCX] {gcx_path}")

    # Step 2: Run GCX imports + copy concurrently
    if import_targets:
        print(f"\nStarting GCX imports for {len(import_targets)} changed file(s)...\n")

        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = {
                executor.submit(
                    import_and_copy_gcx,
                    python_cmd,
                    repo_root,
                    script_path,
                    gcx_path,
                    rel_path,
                    dist_root,
                ): rel_path
                for gcx_path, rel_path in import_targets
            }

            for i, future in enumerate(as_completed(futures), 1):
                rel_path = futures[future]
                try:
                    rel, code = future.result()
                    if code != 0:
                        import_failed = True
                    color = "\033[92m" if code == 0 else "\033[91m"
                    reset = "\033[0m"
                    with print_lock:
                        print(
                            f"[{i}/{len(import_targets)}] {rel} -> "
                            f"{color}{'OK' if code == 0 else f'FAILED ({code})'}{reset}"
                        )
                except Exception as e:
                    import_failed = True
                    with print_lock:
                        print(
                            f"[{i}/{len(import_targets)}] {rel_path} -> "
                            f"\033[91mERROR: {e}\033[0m"
                        )

    # Step 3: Summary + exit code
    if import_failed:
        print("\nOne or more GCX imports failed.")
        sys.exit(1)

    if differences:
        print(f"\n{len(differences)} file(s) changed:")
        for rel_path, old, new in differences:
            print(f"  {rel_path}\n    OLD: {old}\n    NEW: {new}")
        sys.exit(0)
    else:
        print("\nAll hashes match. No differences found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
