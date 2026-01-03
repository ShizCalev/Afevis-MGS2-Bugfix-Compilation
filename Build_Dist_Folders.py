from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional


MAX_WORKERS = os.cpu_count() or 8

GIT_ROOT: Optional[Path] = None

# Global map: repo-relative lowercase path -> unix timestamp (last content change)
GIT_MTIME_INDEX: Dict[str, float] = {}
GIT_INDEX_BUILT = False
GIT_INDEX_LOCK = Lock()


def find_git_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[ERROR] Failed to find git root via git: {exc}")
        sys.exit(1)

    root = result.stdout.strip()
    if not root:
        print("[ERROR] git rev-parse returned empty path")
        sys.exit(1)

    git_root = Path(root).resolve()
    print(f"[INFO] Git root: {git_root}")
    return git_root


def parse_bool(value: str) -> bool:
    if value is None:
        return False

    value = value.strip().lower()
    return value in {"1", "true", "yes", "y"}


def normalize_repo_path(path: Path) -> Optional[str]:
    """
    Convert a filesystem path to a repo-relative lowercase path with forward slashes.
    Returns None if the path is not under GIT_ROOT.
    """
    global GIT_ROOT
    if GIT_ROOT is None:
        return None

    try:
        rel = path.resolve().relative_to(GIT_ROOT)
    except ValueError:
        return None

    return str(rel).replace("\\", "/").lower()


def build_git_mtime_index(git_root: Path) -> None:
    """
    Walk the entire git history once (oldest to newest) and build a map of:
        repo-relative lowercase path -> last *content* change timestamp,
    following renames and ignoring pure rename-only commits.

    We use:
        git log --name-status --find-renames --format=%at --reverse

    Rules per commit (timestamp T):

      - A/M:
          path_ts[path] = T

      - R<100 (rename + modify):
          path_ts[new_path] = T

      - R100 (pure rename, no content change):
          path_ts[new_path] = path_ts.get(old_path, T)

    So the timestamp reflects the last add/modify of the file contents, while
    still tracking renames across paths.
    """
    global GIT_MTIME_INDEX, GIT_INDEX_BUILT

    with GIT_INDEX_LOCK:
        if GIT_INDEX_BUILT:
            return

        print("[INFO] Building git mtime index (reverse log, rename-aware, content changes only)...")

        cmd = [
            "git",
            "-C",
            str(git_root),
            "log",
            "--name-status",
            "--find-renames",
            "--format=%at",
            "--reverse",
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            print(f"[ERROR] git not found when building mtime index: {exc}")
            sys.exit(1)

        path_ts: Dict[str, float] = {}
        current_ts: Optional[float] = None

        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")

            if not line:
                continue

            # Timestamp lines from --format=%at are just digits
            if line[0].isdigit() and line.strip().isdigit():
                try:
                    current_ts = float(line.strip())
                except ValueError:
                    current_ts = None
                continue

            # Name-status line
            if current_ts is None:
                continue

            parts = line.split("\t")
            if not parts:
                continue

            status = parts[0]
            kind = status[0]

            if kind in {"A", "M", "D"}:
                # Normal add/modify/delete entry: status\tpath
                if len(parts) < 2:
                    continue
                raw_path = parts[1]
                key = raw_path.replace("\\", "/").lower()

                if kind in {"A", "M"}:
                    # Real content change
                    path_ts[key] = current_ts
                # D: delete does not update last content change; ignore for our purposes.

            elif kind in {"R", "C"}:
                # Rename or copy: Rnn\told\tnew (or Cnn\told\tnew)
                if len(parts) < 3:
                    continue

                old_path = parts[1]
                new_path = parts[2]

                old_key = old_path.replace("\\", "/").lower()
                new_key = new_path.replace("\\", "/").lower()

                if kind == "R":
                    # Extract similarity score if present, e.g. "R100"
                    score_str = status[1:] if len(status) > 1 else ""
                    pure_rename = score_str == "100"

                    if pure_rename:
                        # Pure rename: carry over old timestamp if it exists.
                        old_ts = path_ts.get(old_key)
                        if old_ts is not None:
                            path_ts[new_key] = old_ts
                        else:
                            # No previous record (shallow history, etc.), treat as content introduction.
                            path_ts[new_key] = current_ts
                    else:
                        # Rename + modify: treat as content change at this commit.
                        path_ts[new_key] = current_ts
                else:
                    # Copy: treat as new content at this commit for the new path.
                    path_ts[new_key] = current_ts

            else:
                # Unknown status; ignore
                continue

        stdout_data, stderr_data = proc.communicate()
        if proc.returncode not in (0, None):
            print(f"[WARN] git log exited with code {proc.returncode}")
            if stderr_data:
                print(f"[WARN] git log stderr:\n{stderr_data}")

        GIT_MTIME_INDEX = path_ts
        GIT_INDEX_BUILT = True

        print(f"[INFO] Git mtime index built with {len(GIT_MTIME_INDEX)} paths.")


def get_git_mtime(path: Path) -> Optional[float]:
    """
    Return the last content-change Unix timestamp for the given path, using the
    prebuilt git mtime index. If no entry exists, return None.
    """
    key = normalize_repo_path(path)
    if key is None:
        return None

    return GIT_MTIME_INDEX.get(key)


def set_mtime(path: Path, ts: float) -> None:
    try:
        os.utime(path, (ts, ts))
        print(f"  [UTIME] {path} -> {int(ts)}")
    except Exception as exc:
        print(f"  [UTIME FAIL] {path}: {exc}")


def compute_mtime_for_src(
    src: Path,
    ctxr_mtime_map: Optional[dict[str, float]] = None,
) -> Optional[float]:
    """
    Decide which mtime to use for a source file before moving:
      1) If ctxr_mtime_map is provided and this is a .ctxr, prefer the
         per-path timestamp from that map (PS2/MC/Self Remade canonical dates).
      2) Otherwise, fall back to git content-change timestamp from the index.
    """
    ts: Optional[float] = None

    if ctxr_mtime_map is not None and src.suffix.lower() == ".ctxr":
        repo_key = normalize_repo_path(src)
        if repo_key is not None:
            ts = ctxr_mtime_map.get(repo_key)

    if ts is None:
        ts = get_git_mtime(src)

    return ts


def move_tree_all(
    origin: Path,
    dest: Path,
    ctxr_mtime_map: Optional[dict[str, float]] = None,
) -> None:
    for root, dirs, files in os.walk(origin):
        root_path = Path(root)
        rel_root = root_path.relative_to(origin)
        target_root = dest / rel_root
        target_root.mkdir(parents=True, exist_ok=True)

        for filename in files:
            src_file = root_path / filename
            dst_file = target_root / filename
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            mtime = compute_mtime_for_src(src_file, ctxr_mtime_map)
            shutil.move(str(src_file), str(dst_file))
            print(f"  [MOVE] {src_file} -> {dst_file}")

            if mtime is not None:
                set_mtime(dst_file, mtime)


def move_tree_ctxr_only(
    origin: Path,
    dest: Path,
    ctxr_mtime_map: Optional[dict[str, float]],
) -> None:
    moved_any = False
    for ctxr in origin.rglob("*.ctxr"):
        rel_path = ctxr.relative_to(origin)
        target = dest / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        mtime = compute_mtime_for_src(ctxr, ctxr_mtime_map)
        shutil.move(str(ctxr), str(target))
        print(f"  [MOVE .ctxr] {ctxr} -> {target}")
        moved_any = True

        if mtime is not None:
            set_mtime(target, mtime)

    if not moved_any:
        print("  [INFO] No .ctxr files found to move.")


def prune_empty_dirs(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        return

    removed_any = False

    for current_root, dirs, files in os.walk(root, topdown=False):
        cur_path = Path(current_root)

        if not dirs and not files:
            try:
                os.rmdir(cur_path)
                print(f"  [RMDIR] {cur_path}")
                removed_any = True
            except OSError as exc:
                print(f"  [RMDIR FAIL] {cur_path}: {exc}")

    if not removed_any:
        print("  [INFO] No empty folders to remove under origin.")


def load_ps2_origin_dates(csv_path: Path) -> dict[str, float]:
    """
    Load PS2 origin dates from:
      stem,tga_hash,origin_date,origin_version
    origin_date is a Unix timestamp.

    NOTE: 'stem' is treated as an exact stem from CSV. We only strip and lowercase.
    """
    mapping: dict[str, float] = {}

    if not csv_path.is_file():
        print(f"[ERROR] PS2 origin dates CSV not found: {csv_path}")
        sys.exit(1)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"stem", "origin_date"}
        if not required.issubset(set(reader.fieldnames or [])):
            print("[ERROR] PS2 dates CSV missing required headers: stem,origin_date")
            sys.exit(1)

        for row in reader:
            stem = (row.get("stem") or "").strip()
            ts_str = (row.get("origin_date") or "").strip()
            if not stem or not ts_str:
                continue

            try:
                ts = float(ts_str)
            except ValueError:
                print(f"[WARN] Invalid PS2 origin_date '{ts_str}' for stem '{stem}'")
                continue

            mapping[stem.lower()] = ts

    print(f"[INFO] Loaded {len(mapping)} PS2 origin date entries.")
    return mapping


def parse_mc_datetime_to_ts(value: str) -> Optional[float]:
    """
    Parse 'YYYY-MM-DD - HH:MM:SS UTC' into a Unix timestamp (UTC).
    """
    if not value:
        return None

    raw = value.strip()
    if raw.upper().endswith("UTC"):
        raw = raw[:-3].strip()

    try:
        dt = datetime.strptime(raw, "%Y-%m-%d - %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        print(f"[WARN] Could not parse MC datetime '{value}': {exc}")
        return None

    return dt.timestamp()


def load_mc_origin_dates(csv_path: Path) -> dict[str, float]:
    """
    Load MC origin dates from:
      texture_name,modified_time_utc,sha1
    modified_time_utc is 'YYYY-MM-DD - HH:MM:SS UTC'.

    NOTE: 'texture_name' is treated as an exact stem from CSV. We only strip and lowercase.
    """
    mapping: dict[str, float] = {}

    if not csv_path.is_file():
        print(f"[ERROR] MC origin dates CSV not found: {csv_path}")
        sys.exit(1)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"texture_name", "modified_time_utc"}
        if not required.issubset(set(reader.fieldnames or [])):
            print("[ERROR] MC dates CSV missing required headers: texture_name,modified_time_utc")
            sys.exit(1)

        for row in reader:
            name = (row.get("texture_name") or "").strip()
            ts_str = (row.get("modified_time_utc") or "").strip()
            if not name or not ts_str:
                continue

            ts = parse_mc_datetime_to_ts(ts_str)
            if ts is None:
                continue

            mapping[name.lower()] = ts

    print(f"[INFO] Loaded {len(mapping)} MC origin date entries.")
    return mapping


def load_self_remade_dates(csv_path: Path) -> dict[str, float]:
    """
    Load Self Remade origin dates from:
      stem,modified_unix_time
    modified_unix_time is a Unix timestamp.

    NOTE: 'stem' is treated as an exact stem from CSV. We only strip and lowercase.
    """
    mapping: dict[str, float] = {}

    if not csv_path.is_file():
        print(f"[ERROR] Self Remade dates CSV not found: {csv_path}")
        sys.exit(1)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"stem", "modified_unix_time"}
        if not required.issubset(set(reader.fieldnames or [])):
            print("[ERROR] Self Remade dates CSV missing required headers: stem,modified_unix_time")
            sys.exit(1)

        for row in reader:
            stem = (row.get("stem") or "").strip()
            ts_str = (row.get("modified_unix_time") or "").strip()
            if not stem or not ts_str:
                continue

            try:
                ts = float(ts_str)
            except ValueError:
                print(f"[WARN] Invalid Self Remade modified_unix_time '{ts_str}' for stem '{stem}'")
                continue

            mapping[stem.lower()] = ts

    print(f"[INFO] Loaded {len(mapping)} Self Remade date entries.")
    return mapping


def build_ctxr_mtime_map(
    origin_root: Path,
    ps2_dates: dict[str, float],
    mc_dates: dict[str, float],
    self_remade_dates: dict[str, float],
) -> dict[str, float]:
    """
    Walk origin_root for conversion_hashes.csv and build a map:
        repo_relative_ctxr_path_lower -> mtime (float)

    IMPORTANT:
      - filename in conversion_hashes.csv is already an exact stem
        (for you that includes the extension, e.g. 'foo.bmp').
      - We do not call Path(...).stem on CSV data.
      - We only strip and lowercase CSV values.
      - We only assign PS2/MC/Self Remade origin dates when origin_folder
        starts with the appropriate prefix; everything else falls back to git mtime.
    """
    ctxr_mtime_map: dict[str, float] = {}
    csv_count = 0
    rows_used = 0

    for csv_path in origin_root.rglob("conversion_hashes.csv"):
        csv_count += 1
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"filename", "origin_folder"}
            if not required.issubset(set(reader.fieldnames or [])):
                print(
                    f"[WARN] conversion_hashes.csv at {csv_path} missing "
                    f"filename/origin_folder columns, skipping."
                )
                continue

            for row in reader:
                filename = (row.get("filename") or "").strip()
                origin_folder = (row.get("origin_folder") or "").strip().lower()

                if not filename or not origin_folder:
                    continue

                csv_key = filename.lower()

                ts: Optional[float] = None
                if origin_folder.startswith("ps2 textures"):
                    ts = ps2_dates.get(csv_key)
                elif origin_folder.startswith("mc textures"):
                    ts = mc_dates.get(csv_key)
                elif origin_folder.startswith("self remade"):
                    ts = self_remade_dates.get(csv_key)
                else:
                    # Upscaled, other buckets, etc - no PS2/MC/Self Remade override
                    continue

                if ts is None:
                    continue

                # Concrete CTXR filename: filename already includes .bmp
                ctxr_filename = f"{filename}.ctxr"
                ctxr_path = (csv_path.parent / ctxr_filename).resolve()

                if not ctxr_path.is_file():
                    continue

                repo_key = normalize_repo_path(ctxr_path)
                if repo_key is None:
                    continue

                if repo_key not in ctxr_mtime_map:
                    ctxr_mtime_map[repo_key] = ts
                    rows_used += 1

    if csv_count:
        print(
            f"[INFO] Built ctxr_mtime_map from {csv_count} conversion_hashes.csv files, "
            f"{rows_used} ctxr files with PS2/MC/Self Remade timestamps."
        )
    else:
        print("[INFO] No conversion_hashes.csv found under origin for ctxr mtime mapping.")

    return ctxr_mtime_map


def process_mapping(
    origin_abs: Path,
    dest_abs: Path,
    prune_non_ctxr: bool,
    idx: int,
    ps2_dates: dict[str, float],
    mc_dates: dict[str, float],
    self_remade_dates: dict[str, float],
) -> None:
    print(f"\n[MAP {idx}]")
    print(f"  Origin:          {origin_abs}")
    print(f"  Destination:     {dest_abs}")
    print(f"  prune_non_ctxr:  {prune_non_ctxr}")

    if not origin_abs.exists():
        print(f"[WARN] Origin does not exist, skipping: {origin_abs}")
        return

    ctxr_mtime_map: Optional[dict[str, float]] = None
    if prune_non_ctxr and origin_abs.is_dir():
        ctxr_mtime_map = build_ctxr_mtime_map(origin_abs, ps2_dates, mc_dates, self_remade_dates)

    # Single file case
    if origin_abs.is_file():
        dest_abs.parent.mkdir(parents=True, exist_ok=True)

        if prune_non_ctxr and origin_abs.suffix.lower() != ".ctxr":
            print(f"[SKIP] prune_non_ctxr enabled, skipping non .ctxr file: {origin_abs}")
            return

        mtime = compute_mtime_for_src(origin_abs, ctxr_mtime_map)
        shutil.move(str(origin_abs), str(dest_abs))
        print(f"[MOVE FILE] {origin_abs} -> {dest_abs}")

        if mtime is not None:
            set_mtime(dest_abs, mtime)

        return

    dest_abs.mkdir(parents=True, exist_ok=True)

    if prune_non_ctxr:
        print("[INFO] prune_non_ctxr = TRUE, moving only .ctxr files:")
        print(f"       {origin_abs} -> {dest_abs}")
        move_tree_ctxr_only(origin_abs, dest_abs, ctxr_mtime_map)
    else:
        print("[INFO] Moving full tree:")
        print(f"       {origin_abs} -> {dest_abs}")
        move_tree_all(origin_abs, dest_abs)

    print(f"[INFO] Pruning empty folders under origin: {origin_abs}")
    prune_empty_dirs(origin_abs)


def main() -> None:
    global GIT_ROOT

    git_root = find_git_root()
    GIT_ROOT = git_root

    # Build git mtime index once, up front
    build_git_mtime_index(git_root)

    csv_path = git_root / "Release_Structure.csv"

    if not csv_path.is_file():
        print(f"[ERROR] Release_Structure.csv not found at git root: {csv_path}")
        sys.exit(1)

    print(f"[INFO] Using mapping file: {csv_path}")

    mappings: list[tuple[int, Path, Path, bool]] = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"origin_path", "destination_path", "prune_non_ctxr"}
        if not required.issubset(set(reader.fieldnames or [])):
            print("[ERROR] CSV must have headers: origin_path,destination_path,prune_non_ctxr")
            sys.exit(1)

        for idx, row in enumerate(reader, start=1):
            origin_rel = (row.get("origin_path") or "").strip()
            dest_rel = (row.get("destination_path") or "").strip()
            prune_flag = parse_bool(row.get("prune_non_ctxr") or "")

            if not origin_rel or not dest_rel:
                print(f"[WARN] Row {idx} has empty origin or destination, skipping")
                continue

            if origin_rel.startswith("#"):
                continue

            origin_abs = (git_root / origin_rel).resolve()
            dest_abs = (git_root / dest_rel).resolve()

            mappings.append((idx, origin_abs, dest_abs, prune_flag))

    if not mappings:
        print("[INFO] No valid mappings found in CSV.")
        print("\n[INFO] Done.")
        return

    any_pruned = any(prune_flag for (_, _, _, prune_flag) in mappings)
    if any_pruned:
        external_dir = (
            git_root
            / "external"
            / "MGS2-PS2-Textures"
            / "u - dumped from substance"
        )
        ps2_dates_csv = external_dir / "mgs2_ps2_substance_version_dates.csv"
        mc_dates_csv = external_dir / "mgs2_mc_real_dates.csv"
        self_remade_csv = git_root / "self_remade_modified_dates.csv"

        ps2_dates = load_ps2_origin_dates(ps2_dates_csv)
        mc_dates = load_mc_origin_dates(mc_dates_csv)
        self_remade_dates = load_self_remade_dates(self_remade_csv)
    else:
        ps2_dates = {}
        mc_dates = {}
        self_remade_dates = {}

    print(f"[INFO] Processing {len(mappings)} mappings with up to {MAX_WORKERS} worker threads.\n")

    def worker(mapping: tuple[int, Path, Path, bool]) -> None:
        idx, origin_abs, dest_abs, prune_flag = mapping
        process_mapping(origin_abs, dest_abs, prune_flag, idx, ps2_dates, mc_dates, self_remade_dates)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, m) for m in mappings]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"[ERROR] Mapping task raised an exception: {exc}")

    print("\n[INFO] Done.")


if __name__ == "__main__":
    main()
