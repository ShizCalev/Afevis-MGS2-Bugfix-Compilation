from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm


# ==========================================================
# CONFIG
# ==========================================================
VERSION_CSV_REL = Path(
    r"external\MGS2-PS2-Textures\u - dumped from substance\mgs2_ps2_substance_version_dates.csv"
)

TEXTURE_FIXES_ROOT_REL = Path(r"Texture Fixes")

STAGING_DIRS_REL = [
    Path(r"Texture Fixes\Staging"),
    Path(r"Texture Fixes\Staging - 2x Upscaled"),
    Path(r"Texture Fixes\Staging - 4x Upscaled"),
]

CONVERSION_CSV_NAME = "conversion_hashes.csv"
CTXR_EXT = ".ctxr"

MC_DATES_CSV_REL = Path(r"external\MGS2-PS2-Textures\u - dumped from substance\mgs2_mc_real_dates.csv")

# How many worker threads per CSV
MAX_WORKERS = max(4, (os.cpu_count() or 4) * 2)

# Global cache for git paths (lowercase -> canonical path)
GIT_PATH_CACHE: Dict[str, str] | None = None


# ==========================================================
# WINDOWS FILETIME HELPERS
# ==========================================================
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


def unix_to_filetime(ts: int) -> wintypes.FILETIME:
    WINDOWS_TICK = 10_000_000
    SEC_TO_UNIX_EPOCH = 11_644_473_600
    filetime = int((ts + SEC_TO_UNIX_EPOCH) * WINDOWS_TICK)
    return wintypes.FILETIME(filetime & 0xFFFFFFFF, filetime >> 32)


def set_windows_times(path: Path, ts_unix: int) -> None:
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

    ft = unix_to_filetime(ts_unix)

    ok = SetFileTime(handle, ctypes.byref(ft), ctypes.byref(ft), ctypes.byref(ft))
    CloseHandle(handle)

    if not ok:
        raise OSError(f"SetFileTime failed on {path}")


# ==========================================================
# HELPERS
# ==========================================================
def get_git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise SystemExit("Error: not inside a git repo")

    root = Path(result.stdout.strip())
    if not root.exists():
        raise SystemExit("Git root does not exist")

    return root


def load_origin_dates(csv_path: Path) -> Dict[str, int]:
    if not csv_path.is_file():
        raise SystemExit(f"Origin date CSV missing: {csv_path}")

    mapping: Dict[str, int] = {}
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"stem", "tga_hash", "origin_date", "origin_version"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"{csv_path} is missing columns: {', '.join(sorted(missing))}"
            )

        for row in reader:
            stem = row["stem"].strip()
            if not stem:
                continue
            mapping[stem] = int(row["origin_date"])

    print(f"Loaded {len(mapping)} origin date entries from {csv_path}")
    return mapping


def parse_mc_time_to_unix(time_str: str, stem: str) -> int:
    # Format: 2011-10-13 - 19:33:42 UTC
    s = time_str.strip()
    dt = datetime.strptime(s, "%Y-%m-%d - %H:%M:%S UTC")
    dt = dt.replace(tzinfo=timezone.utc)

    if dt.year < 2011:
        print(
            f"ERROR: MC modified_time_utc for '{stem}' is before 2011: {s} "
            f"(year={dt.year})"
        )
        input("Press Enter to exit...")
        raise SystemExit("MC real file date before 2011 detected, aborting.")

    return int(dt.timestamp())


def load_mc_dates(csv_path: Path) -> Dict[str, str]:
    """
    Load MC CSV as texture_name -> modified_time_utc (string).
    The year check is done only when we actually apply an MC timestamp.
    """
    if not csv_path.is_file():
        raise SystemExit(f"MC real file dates CSV missing: {csv_path}")

    mapping: Dict[str, str] = {}
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"texture_name", "modified_time_utc", "sha1"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"{csv_path} is missing columns: {', '.join(sorted(missing))}"
            )

        for row in reader:
            stem = (row.get("texture_name") or "").strip()
            if not stem:
                continue

            time_str = (row.get("modified_time_utc") or "").strip()
            if not time_str:
                raise SystemExit(
                    f"Empty modified_time_utc for '{stem}' in {csv_path}"
                )

            mapping[stem] = time_str

    print(f"Loaded {len(mapping)} MC modified_time_utc entries from {csv_path}")
    return mapping


def build_git_path_cache(repo_root: Path) -> Dict[str, str]:
    global GIT_PATH_CACHE
    if GIT_PATH_CACHE is not None:
        return GIT_PATH_CACHE

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise SystemExit(f"git ls-files failed: {result.stderr.strip()}")

    cache: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            cache[line.lower()] = line

    GIT_PATH_CACHE = cache
    return cache


def get_git_last_change_unix(repo_root: Path, path: Path) -> int | None:
    cache = build_git_path_cache(repo_root)

    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        print(f"WARNING: {path} is not under repo root {repo_root}")
        return None

    rel_str = str(rel).replace("\\", "/")
    key = rel_str.lower()

    if key not in cache:
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
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(
            f"WARNING: git log failed for {canonical}: {result.stderr.strip()}"
        )
        return None

    out = result.stdout.strip()
    if not out:
        print(f"WARNING: no git content-change log for {canonical}")
        return None

    return int(out)


def find_self_remade_source(
    texture_fixes_root: Path, origin_folder_raw: str, stem: str
) -> Path | None:
    norm = origin_folder_raw.replace("/", "\\").lstrip("\\")
    origin_dir = texture_fixes_root / norm

    candidates: List[Path] = []
    for ext in (".png", ".tga"):
        p = origin_dir / f"{stem}{ext}"
        if p.is_file():
            candidates.append(p)

    if not candidates:
        print(
            f"WARNING: Self Remade source not found for '{stem}' in {origin_dir}"
        )
        return None

    if len(candidates) > 1:
        print(
            f"WARNING: Multiple Self Remade sources for '{stem}' in {origin_dir}: "
            f"{[c.name for c in candidates]}"
        )
        return None

    return candidates[0]


def find_conversion_csvs(root: Path) -> List[Path]:
    if not root.is_dir():
        print(f"Skipping missing staging dir: {root}")
        return []
    return list(root.rglob(CONVERSION_CSV_NAME))


# ==========================================================
# PER-ROW TASK LOGIC (RUN IN THREADS)
# ==========================================================
def process_row_task(
    repo_root: Path,
    texture_fixes_root: Path,
    row: dict,
    origin_dates: Dict[str, int],
    mc_dates: Dict[str, str],
    ctxr_path: Path,
) -> Tuple[bool, str]:
    """
    Run the real work for a single row.

    Returns (updated, reason)
    updated = True if timestamps were set
    updated = False if skipped for any reason, 'reason' is a short label
    """
    origin_folder_raw = row["origin_folder"] or ""
    origin_folder_norm = origin_folder_raw.replace("/", "\\").lstrip("\\")
    origin_folder_lower = origin_folder_norm.lower()

    stem = row["filename"].strip()
    # ctxr_path existence already checked by caller

    # PS2 textures
    if "ps2 textures" in origin_folder_lower:
        ts = origin_dates.get(stem)
        if ts is None:
            return False, "no_ps2_origin_date"

        set_windows_times(ctxr_path, ts)
        return True, "ps2"

    # Self Remade
    if origin_folder_lower.startswith("self remade\\"):
        src = find_self_remade_source(texture_fixes_root, origin_folder_raw, stem)
        if src is None:
            return False, "no_self_remade_src"

        ts = get_git_last_change_unix(repo_root, src)
        if ts is None:
            return False, "no_git_ts"

        set_windows_times(ctxr_path, ts)
        return True, "self_remade"

    # MC textures
    if origin_folder_lower.startswith("mc textures\\"):
        time_str = mc_dates.get(stem)
        if time_str is None:
            return False, "no_mc_date"

        ts = parse_mc_time_to_unix(time_str, stem)
        set_windows_times(ctxr_path, ts)
        return True, "mc"

    # Everything else ignored
    return False, "other_origin"


# ==========================================================
# PER-CSV PROCESSING (PARALLEL PER ROW)
# ==========================================================
def process_conversion_csv(
    repo_root: Path,
    texture_fixes_root: Path,
    conv_csv: Path,
    origin_dates: Dict[str, int],
    mc_dates: Dict[str, str],
) -> tuple[int, int, int]:
    """
    Returns (total_rows, updated_files, skipped_rows)
    """
    total = 0
    updated = 0
    skipped = 0

    # Load rows
    with conv_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {
            "filename",
            "before_hash",
            "ctxr_hash",
            "mipmaps",
            "origin_folder",
            "opacity_stripped",
            "upscaled",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"{conv_csv} is missing columns: {', '.join(sorted(missing))}"
            )

        rows: List[dict] = list(reader)

    total = len(rows)
    if total == 0:
        return 0, 0, 0

    # Build tasks list
    tasks: List[Tuple[dict, Path]] = []

    for row in rows:
        stem = (row.get("filename") or "").strip()
        if not stem:
            skipped += 1
            continue

        ctxr_path = conv_csv.parent / f"{stem}{CTXR_EXT}"
        if not ctxr_path.is_file():
            print(f"Missing ctxr for {stem}: {ctxr_path}")
            skipped += 1
            continue

        # Everything else (origin_folder filters etc.) handled inside the worker.
        tasks.append((row, ctxr_path))

    if not tasks:
        return total, updated, skipped

    # Run tasks in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                process_row_task,
                repo_root,
                texture_fixes_root,
                row,
                origin_dates,
                mc_dates,
                ctxr_path,
            ): (row, ctxr_path)
            for (row, ctxr_path) in tasks
        }

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"Processing {conv_csv.name}",
            unit="file",
        ):
            try:
                ok, _reason = future.result()
            except SystemExit:
                # Propagate hard abort from parse_mc_time_to_unix or any fatal path
                raise
            except Exception as e:
                # Treat any other exception as a skip
                # and keep going, but log it.
                row, ctxr_path = futures[future]
                stem = (row.get("filename") or "").strip()
                print(f"ERROR processing '{stem}' at {ctxr_path}: {e!r}")
                skipped += 1
                continue

            if ok:
                updated += 1
            else:
                skipped += 1

    return total, updated, skipped


# ==========================================================
# MAIN
# ==========================================================
def main() -> None:
    repo_root = get_git_root()
    print(f"Repo root: {repo_root}")

    texture_fixes_root = repo_root / TEXTURE_FIXES_ROOT_REL

    origin_dates = load_origin_dates(repo_root / VERSION_CSV_REL)
    mc_dates = load_mc_dates(repo_root / MC_DATES_CSV_REL)

    # Build git cache up-front so threads only read it
    build_git_path_cache(repo_root)

    staging_dirs = [repo_root / p for p in STAGING_DIRS_REL]

    all_csvs: List[Path] = []
    for d in staging_dirs:
        found = find_conversion_csvs(d)
        print(f"Found {len(found)} '{CONVERSION_CSV_NAME}' files under {d}")
        all_csvs.extend(found)

    if not all_csvs:
        print("No conversion_hashes.csv found")
        return

    total = updated = skipped = 0

    for conv_csv in sorted(all_csvs):
        print(f"\nProcessing {conv_csv}")
        t, u, s = process_conversion_csv(
            repo_root, texture_fixes_root, conv_csv, origin_dates, mc_dates
        )
        total += t
        updated += u
        skipped += s
        print(f"Rows: {t}  Updated: {u}  Skipped: {s}")

    print("\n=== SUMMARY ===")
    print(f"Total rows: {total}")
    print(f"Updated files: {updated}")
    print(f"Skipped: {skipped}")


if __name__ == "__main__":
    main()
