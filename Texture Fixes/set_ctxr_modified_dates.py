from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path
from typing import Dict, List
import ctypes
from ctypes import wintypes


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

# Global cache for git paths (lowercase -> canonical path)
GIT_PATH_CACHE: Dict[str, str] | None = None


# ==========================================================
# WINDOWS FILETIME HELPERS
# ==========================================================
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [
    wintypes.LPCWSTR,  # lpFileName
    wintypes.DWORD,    # dwDesiredAccess
    wintypes.DWORD,    # dwShareMode
    wintypes.LPVOID,   # lpSecurityAttributes
    wintypes.DWORD,    # dwCreationDisposition
    wintypes.DWORD,    # dwFlagsAndAttributes
    wintypes.HANDLE,   # hTemplateFile
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
    # Windows FILETIME = 100ns intervals since 1601-01-01 UTC
    # Unix timestamp = seconds since 1970-01-01 UTC
    WINDOWS_TICK = 10_000_000
    SEC_TO_UNIX_EPOCH = 11_644_473_600
    filetime = int((ts + SEC_TO_UNIX_EPOCH) * WINDOWS_TICK)
    return wintypes.FILETIME(filetime & 0xFFFFFFFF, filetime >> 32)


def set_windows_times(path: Path, ts_unix: int) -> None:
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
            try:
                origin_date = int(row["origin_date"])
            except (TypeError, ValueError):
                raise SystemExit(
                    f"Invalid origin_date for stem '{stem}' in {csv_path}: "
                    f"{row['origin_date']!r}"
                )
            mapping[stem] = origin_date

    print(f"Loaded {len(mapping)} origin date entries from {csv_path}")
    return mapping


def find_conversion_csvs(root: Path) -> List[Path]:
    if not root.is_dir():
        print(f"Skipping missing staging dir: {root}")
        return []
    return list(root.rglob(CONVERSION_CSV_NAME))


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
        p = line.strip()
        if not p:
            continue
        cache[p.lower()] = p  # lowercase -> canonical git path

    GIT_PATH_CACHE = cache
    return cache


def get_git_last_change_unix(repo_root: Path, path: Path) -> int | None:
    """
    Return the Unix timestamp of the last commit where the file's content changed
    (added or modified), following renames, case-insensitive.
    """
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

    canonical_git_path = cache[key]

    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--follow",
            "--diff-filter=AM",  # Add or Modify only, ignore pure renames
            "--format=%ct",
            "--",
            canonical_git_path,
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(
            f"WARNING: git log failed for {canonical_git_path} "
            f"(code {result.returncode}): {result.stderr.strip()}"
        )
        return None

    out = result.stdout.strip()
    if not out:
        print(f"WARNING: no git content-change log for {canonical_git_path}")
        return None

    try:
        return int(out)
    except ValueError:
        print(f"WARNING: invalid git timestamp for {canonical_git_path}: {out!r}")
        return None


def find_self_remade_source(
    texture_fixes_root: Path, origin_folder_raw: str, stem: str
) -> Path | None:
    # origin_folder is stored relative to "Texture Fixes"
    norm = origin_folder_raw.replace("/", "\\").lstrip("\\")
    origin_dir = texture_fixes_root / norm

    candidates: List[Path] = []
    for ext in (".png", ".tga"):
        p = origin_dir / f"{stem}{ext}"
        if p.is_file():
            candidates.append(p)

    if not candidates:
        print(
            f"WARNING: Self Remade source not found for stem '{stem}' "
            f"in {origin_dir}"
        )
        return None

    if len(candidates) > 1:
        print(
            f"WARNING: Multiple Self Remade sources for stem '{stem}' in {origin_dir}: "
            f"{[c.name for c in candidates]}"
        )
        return None

    return candidates[0]


def process_conversion_csv(
    repo_root: Path,
    texture_fixes_root: Path,
    conv_csv: Path,
    origin_dates: Dict[str, int],
) -> tuple[int, int, int]:
    """
    Returns (total_rows, updated_files, skipped_rows)
    """
    total = 0
    updated = 0
    skipped = 0

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

        for row in reader:
            total += 1

            origin_folder_raw = row["origin_folder"] or ""
            origin_folder_norm = origin_folder_raw.replace("/", "\\").lstrip("\\")
            origin_folder_lower = origin_folder_norm.lower()

            stem = row["filename"].strip()
            if not stem:
                skipped += 1
                continue

            ctxr_path = conv_csv.parent / f"{stem}{CTXR_EXT}"
            if not ctxr_path.is_file():
                print(f"Missing ctxr for {stem}: {ctxr_path}")
                skipped += 1
                continue

            # Case 1: PS2 textures -> use origin_date from version CSV
            if "ps2 textures" in origin_folder_lower:
                origin_ts = origin_dates.get(stem)
                if origin_ts is None:
                    print(
                        f"WARNING: No origin_date entry for stem '{stem}' "
                        f"(needed by {conv_csv})"
                    )
                    skipped += 1
                    continue

                try:
                    set_windows_times(ctxr_path, origin_ts)
                    updated += 1
                except Exception as e:
                    print(f"FAILED timestamp set (ps2 textures): {ctxr_path}  ({e})")
                    skipped += 1
                continue

            # Case 2: Self Remade\... -> use Git last content-change time of original file
            if origin_folder_lower.startswith("self remade\\"):
                src = find_self_remade_source(
                    texture_fixes_root, origin_folder_raw, stem
                )
                if src is None:
                    skipped += 1
                    continue

                ts = get_git_last_change_unix(repo_root, src)
                if ts is None:
                    skipped += 1
                    continue

                try:
                    set_windows_times(ctxr_path, ts)
                    updated += 1
                except Exception as e:
                    print(f"FAILED timestamp set (Self Remade): {ctxr_path}  ({e})")
                    skipped += 1
                continue

            # Everything else: do nothing
            skipped += 1

    return total, updated, skipped


# ==========================================================
# MAIN
# ==========================================================
def main() -> None:
    repo_root = get_git_root()
    print(f"Repo root: {repo_root}")

    texture_fixes_root = repo_root / TEXTURE_FIXES_ROOT_REL

    origin_csv = repo_root / VERSION_CSV_REL
    origin_dates = load_origin_dates(origin_csv)

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
            repo_root, texture_fixes_root, conv_csv, origin_dates
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
