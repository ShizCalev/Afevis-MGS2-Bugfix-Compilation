from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================================
# CONFIG
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent

FOLDERS_TXT_NAME = "folders to process.txt"
STAGING_MAIN_NAME = "_staging_main.py"

# Shared main script that lives next to THIS orchestrator
STAGING_MAIN_PATH = SCRIPT_DIR / STAGING_MAIN_NAME

# Script to run AFTER all staging tiers finish
SET_CTXR_DATES_NAME = "set_ctxr_modified_dates.py"
SET_CTXR_DATES_PATH = SCRIPT_DIR / SET_CTXR_DATES_NAME

# How many jobs to run in parallel within each staging tier
THREADS_PER_TIER = 4

CONVERSION_CSV_NAME = "conversion_hashes.csv"
CONVERSION_CSV_HEADER = "filename,before_hash,ctxr_hash,mipmaps,origin_folder,opacity_stripped,upscaled\n"

NOT_IN_FOLDER_CSV_NAME = "not_in_folder.csv"
UNPROCESSED_FOLDERS_CSV_NAME = "unprocessed_folders.csv"

# Relative location of never_upscale.txt inside the git repo
NEVER_UPSCALE_REL_PATH = Path("Texture Fixes") / "never_upscale.txt"

# ==========================================================
# HARDCODED STAGING ROOTS
# ==========================================================
BUGFIX_ROOT = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes")
DEMASTER_ROOT = Path(r"C:\Development\Git\MGS2-Demastered-Substance-Edition\Textures")
UPSCALED_UI_ROOT = Path(r"C:\Development\Git\MGS2-Upscaled-UI-Textures\Textures")

STAGING_ROOTS: list[Path] = [
    # Bugfix Compilation
    BUGFIX_ROOT / "Staging",
    BUGFIX_ROOT / "Staging - 2x Upscaled",
    BUGFIX_ROOT / "Staging - 4x Upscaled",

    # Demastered pack
    DEMASTER_ROOT / "Staging",
    DEMASTER_ROOT / "Staging - 2x Upscaled",
    DEMASTER_ROOT / "Staging - 4x Upscaled",
    
    DEMASTER_ROOT / "Staging - UI",
    DEMASTER_ROOT / "Staging - UI - 2x Upscaled",
    DEMASTER_ROOT / "Staging - UI - 4x Upscaled",

    # Upscaled UI pack (2x / 4x only)
    UPSCALED_UI_ROOT / "Staging - 2x Upscaled",
    UPSCALED_UI_ROOT / "Staging - 4x Upscaled",
]

# Self Remade Finalized folder and output CSV name
SELF_REMADE_FINALIZED_DIR = BUGFIX_ROOT / "Self Remade" / "Finalized"
SELF_REMADE_MODIFIED_DATES_CSV_NAME = "self_remade_modified_dates.csv"


# ==========================================================
# GIT / CSV HELPERS
# ==========================================================
def get_git_root() -> Path:
    """
    Use git to find the repository root.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("ERROR: git is not installed or not on PATH.")
        sys.exit(1)

    if result.returncode != 0:
        print("ERROR: Not inside a git repository.")
        stderr = result.stderr.strip()
        if stderr:
            print(stderr)
        sys.exit(1)

    root = Path(result.stdout.strip()).resolve()
    if not root.is_dir():
        print(f"ERROR: Git root reported by git does not exist: {root}")
        sys.exit(1)

    return root


def load_dimensions_names(dimensions_csv: Path) -> dict[str, str]:
    """
    Load texture_name entries from mgs2_ps2_dimensions.csv.

    Returns dict:
        logical_name_lower (full filename including .bmp) -> original texture_name

    CSV vs CSV comparisons are done on this full logical name, case insensitive.
    """
    if not dimensions_csv.is_file():
        print(f"ERROR: Dimensions CSV not found at: {dimensions_csv}")
        sys.exit(1)

    names: dict[str, str] = {}
    with dimensions_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "texture_name" not in reader.fieldnames:
            print(f"ERROR: 'texture_name' column not found in {dimensions_csv}")
            sys.exit(1)

        for row in reader:
            name = (row.get("texture_name") or "").strip()
            if not name:
                continue

            key = name.lower()
            if key not in names:
                names[key] = name

    if not names:
        print(f"WARNING: No texture_name entries found in {dimensions_csv}")

    return names


def build_ps2_texture_index(ps2_root: Path) -> dict[str, Path]:
    """
    Index all .tga and .png files under 'Texture Fixes/ps2 textures',
    mapping lowercase Path(path).stem -> full path.

    For filenames like 'w03b_ent01.bmp.tga', Path(...).stem.lower() is 'w03b_ent01.bmp',
    which matches your logical name.
    """
    if not ps2_root.is_dir():
        print(f"WARNING: PS2 textures root does not exist: {ps2_root}")
        return {}

    index: dict[str, Path] = {}

    for ext in ("*.tga", "*.png"):
        for path in ps2_root.rglob(ext):
            if not path.is_file():
                continue
            key = path.stem.lower()
            if key not in index:
                index[key] = path

    if not index:
        print(f"WARNING: No .tga or .png files found under {ps2_root}")

    return index


def collect_converted_names(conversion_csv: Path) -> set[str]:
    """
    Read conversion_hashes.csv and collect lowercase full filenames
    from the 'filename' column.

    This keeps the extension as part of the comparison, case insensitive.
    """
    names: set[str] = set()

    if not conversion_csv.is_file():
        print(f"WARNING: conversion_hashes.csv not found at {conversion_csv}, treating as empty.")
        return names

    with conversion_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "filename" not in (reader.fieldnames or []):
            print(f"WARNING: 'filename' column missing in {conversion_csv}, treating as no entries.")
            return names

        for row in reader:
            filename = (row.get("filename") or "").strip()
            if not filename:
                continue
            names.add(filename.lower())

    return names


def load_never_upscale_stems(never_upscale_path: Path) -> set[str]:
    """
    Load logical names from never_upscale.txt.

    Each nonempty, non-comment line is treated as a full logical name
    (including .bmp) and stored as lowercase. No extensions are added
    or modified. Comparison is exact on that normalized string.
    """
    stems: set[str] = set()

    if not never_upscale_path.is_file():
        print(f"[WARN] never_upscale.txt not found at {never_upscale_path}, no stems will be skipped.")
        return stems

    try:
        with never_upscale_path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                stems.add(raw.lower())
    except OSError as e:
        print(f"[ERROR] Failed to read never_upscale.txt at {never_upscale_path}: {e}")

    if stems:
        print(f"[INFO] Loaded {len(stems)} stem(s) from never_upscale.txt")

    return stems


def write_not_in_folder_csv(
    job_dir: Path,
    dim_names: dict[str, str],
    ps2_texture_index: dict[str, Path],
    never_upscale_stems: set[str],
) -> None:
    """
    For a given job directory:
      - Load conversion_hashes.csv
      - Compute textures that exist in mgs2_ps2_dimensions.csv
        but do not appear in conversion_hashes.csv (full logical name, including .bmp, case insensitive)
      - Skip any logical names whose normalized value is in never_upscale_stems
      - For each remaining texture:
          * If there is a matching .tga/.png in ps2_texture_index
            (matched via Path(path).stem.lower()), record its full path
          * If there is NO matching .tga/.png, still record the filename, with
            an empty full_path
      - Write not_in_folder.csv beside conversion_hashes.csv with:
            filename,full_path
      - Also write unprocessed_folders.csv listing unique parent folders of
        entries that DO have a non-empty full_path.
    """
    conversion_csv = job_dir / CONVERSION_CSV_NAME
    if not conversion_csv.is_file():
        print(f"[WARN] {CONVERSION_CSV_NAME} missing in job dir, skipping not_in_folder.csv: {job_dir}")
        return

    converted_names = collect_converted_names(conversion_csv)
    if not dim_names:
        print(f"[INFO] No dimension names loaded, skipping not_in_folder for {job_dir}")
        return

    rows: list[tuple[str, str]] = []

    # dim_names keys are logical_name_lower (including .bmp)
    for logical_name_lower in sorted(dim_names.keys()):
        # Already present in conversion_hashes.csv for this job
        if logical_name_lower in converted_names:
            continue

        # Skip entries that should never be upscaled (for 2x/4x tiers)
        if logical_name_lower in never_upscale_stems:
            continue

        original_name = dim_names[logical_name_lower]

        # Map to TGA/PNG using the logical name as the "stem" (including .bmp)
        stem_key = original_name.lower()
        tex_path = ps2_texture_index.get(stem_key)

        if tex_path is not None:
            full_path_str = str(tex_path)
        else:
            # No corresponding TGA/PNG in ps2 textures folder, but we still
            # want this filename to appear in not_in_folder.csv
            full_path_str = ""

        rows.append((original_name, full_path_str))

    output_csv = job_dir / NOT_IN_FOLDER_CSV_NAME
    output_folders_csv = job_dir / UNPROCESSED_FOLDERS_CSV_NAME

    if not rows:
        # No missing textures for this job. Still create CSVs with headers so it is explicit.
        try:
            with output_csv.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["filename", "full_path"])
            print(f"[INFO] No missing textures for job, wrote empty {output_csv}")
        except OSError as e:
            print(f"[ERROR] Failed to write empty {output_csv}: {e}")

        try:
            with output_folders_csv.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["folder"])
            print(f"[INFO] No missing textures for job, wrote empty {output_folders_csv}")
        except OSError as e:
            print(f"[ERROR] Failed to write empty {output_folders_csv}: {e}")
        return

    # Write not_in_folder.csv
    try:
        with output_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["filename", "full_path"])
            for filename, full_path in rows:
                writer.writerow([filename, full_path])
        print(f"[INFO] Wrote {len(rows)} missing entries to {output_csv}")
    except OSError as e:
        print(f"[ERROR] Failed to write {output_csv}: {e}")

    # Derive unique folders from full_path column and write unprocessed_folders.csv.
    # Only entries with a non-empty full_path are considered here.
    folder_set: set[str] = set()
    for _, full_path in rows:
        if not full_path:
            continue
        folder_set.add(str(Path(full_path).parent))

    sorted_folders = sorted(folder_set)

    try:
        with output_folders_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["folder"])
            for folder in sorted_folders:
                writer.writerow([folder])
        print(f"[INFO] Wrote {len(sorted_folders)} folders to {output_folders_csv}")
    except OSError as e:
        print(f"[ERROR] Failed to write {output_folders_csv}: {e}")


# ==========================================================
# STAGING HELPERS
# ==========================================================
def find_jobs(root: Path) -> list[Path]:
    """
    Find all "folders to process.txt" files under root.
    Return their parent directories as job directories.
    """
    if not root.is_dir():
        print(f"[WARN] Staging root does not exist, skipping: {root}")
        return []

    jobs: list[Path] = []
    for txt in root.rglob(FOLDERS_TXT_NAME):
        if txt.is_file():
            jobs.append(txt.parent)

    jobs.sort()
    return jobs


def run_staging_main(job_dir: Path) -> None:
    """
    Run shared _staging_main.py with CWD set to the job directory.
    """
    if not STAGING_MAIN_PATH.is_file():
        raise SystemExit(f"ERROR: Cannot find {STAGING_MAIN_NAME} at {STAGING_MAIN_PATH}")

    print("=================================================")
    print(f"Running: {STAGING_MAIN_PATH}")
    print(f"CWD:     {job_dir}")
    print("=================================================")

    result = subprocess.run(
        [sys.executable, str(STAGING_MAIN_PATH)],
        cwd=str(job_dir),
    )

    if result.returncode != 0:
        raise SystemExit(
            f"{STAGING_MAIN_NAME} failed in {job_dir} with exit code {result.returncode}"
        )


def run_tier(root: Path) -> list[Path]:
    """
    Run all jobs under a single staging root in parallel.
    Wait for all jobs in this tier to finish before returning.
    Return the list of job directories processed.
    """
    jobs = find_jobs(root)

    if not jobs:
        print(f"[INFO] No '{FOLDERS_TXT_NAME}' found under {root}")
        return []

    print(f"[INFO] Found {len(jobs)} job(s) under {root}")

    workers = min(max(1, THREADS_PER_TIER), len(jobs))
    print(f"[INFO] Running up to {workers} job(s) in parallel")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(run_staging_main, job_dir): job_dir
            for job_dir in jobs
        }

        for idx, future in enumerate(as_completed(future_map), start=1):
            job_dir = future_map[future]
            try:
                future.result()
                print(f"[INFO] Completed ({idx}/{len(jobs)}): {job_dir}")
            except SystemExit as e:
                print(f"[ERROR] Job failed in {job_dir}: {e}")
                # Kill the whole run if any job fails
                sys.exit(1)
            except Exception as e:
                print(f"[ERROR] Unexpected error in {job_dir}: {e}")
                sys.exit(1)

    print(f"[INFO] Finished all jobs under {root}")
    return jobs


def run_set_ctxr_dates() -> None:
    if not SET_CTXR_DATES_PATH.is_file():
        print(f"ERROR: Could not find {SET_CTXR_DATES_NAME} at: {SET_CTXR_DATES_PATH}")
        sys.exit(1)

    print()
    print("#################################################")
    print(f"Running final script: {SET_CTXR_DATES_PATH}")
    print("#################################################")

    result = subprocess.run(
        [sys.executable, str(SET_CTXR_DATES_PATH)],
        cwd=str(SCRIPT_DIR),
    )

    if result.returncode != 0:
        print(f"ERROR: {SET_CTXR_DATES_NAME} failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    print("[INFO] set_ctxr_modified_dates.py completed successfully.")


def _sync_2x_4x_pair(root_2x: Path, root_4x: Path) -> None:
    """
    Internal helper: sync 2x <-> 4x folders_to_process for a single project root pair.
    """
    if not root_2x.is_dir():
        print(f"[INFO] 2x staging root does not exist, skipping 2x sync: {root_2x}")
        return

    if not root_4x.is_dir():
        print(f"[WARN] 4x staging root does not exist, skipping 2x sync: {root_4x}")
        return

    # Collect all relative FOLDERS_TXT paths under 4x
    rel_paths_4x: set[Path] = set()
    for txt_4x in root_4x.rglob(FOLDERS_TXT_NAME):
        if txt_4x.is_file():
            rel_paths_4x.add(txt_4x.relative_to(root_4x))

    if not rel_paths_4x:
        print(f"[WARN] No 'folders to process.txt' found under 4x: {root_4x}, skipping 2x sync.")
        return

    print("[INFO] Syncing 'folders to process.txt' between 2x and 4x tiers")
    print(f"       2x root: {root_2x}")
    print(f"       4x root: {root_4x}")

    # First handle existing 2x files
    seen_rel_2x: set[Path] = set()

    for txt_2x in root_2x.rglob(FOLDERS_TXT_NAME):
        if not txt_2x.is_file():
            continue

        rel = txt_2x.relative_to(root_2x)
        seen_rel_2x.add(rel)

        # If not in 4x -> delete
        if rel not in rel_paths_4x:
            print(f"[INFO] Removing 2x only '{FOLDERS_TXT_NAME}': {txt_2x}")
            try:
                txt_2x.unlink()
            except OSError as e:
                print(f"[ERROR] Failed to delete {txt_2x}: {e}")
            continue

        # Exists in both -> ensure contents match
        txt_4x = root_4x / rel
        try:
            data_2x = txt_2x.read_bytes()
            data_4x = txt_4x.read_bytes()
        except OSError as e:
            print(f"[ERROR] Failed to read one of the paired files {txt_2x} / {txt_4x}: {e}")
            continue

        if data_2x != data_4x:
            print(f"[INFO] Updating 2x '{FOLDERS_TXT_NAME}' to match 4x: {txt_2x}")
            try:
                txt_2x.write_bytes(data_4x)
            except OSError as e:
                print(f"[ERROR] Failed to overwrite {txt_2x} with {txt_4x}: {e}")

    # Now handle files that exist ONLY in 4x
    for rel in rel_paths_4x:
        if rel in seen_rel_2x:
            continue

        src = root_4x / rel
        dst = root_2x / rel

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            print(f"[INFO] Added missing 2x '{FOLDERS_TXT_NAME}': {dst}")
        except OSError as e:
            print(f"[ERROR] Failed to copy missing 4x file to 2x: {src} -> {dst}: {e}")

    # Finally, remove empty directories under 2x (but keep the root)
    for dirpath, dirnames, filenames in os.walk(root_2x, topdown=False):
        p = Path(dirpath)
        if p == root_2x:
            continue

        try:
            if not any(p.iterdir()):
                print(f"[INFO] Removing empty directory under 2x: {p}")
                p.rmdir()
        except OSError as e:
            print(f"[ERROR] Failed to remove empty directory {p}: {e}")


def sync_2x_folders_txt_with_4x() -> None:
    """
    Sync logic for all projects:
      - Bugfix Compilation: Texture Fixes 2x <-> 4x
      - Demastered pack:    Textures 2x <-> 4x
      - Upscaled UI pack:   Textures 2x <-> 4x
    """
    _sync_2x_4x_pair(
        BUGFIX_ROOT / "Staging - 2x Upscaled",
        BUGFIX_ROOT / "Staging - 4x Upscaled",
    )

    _sync_2x_4x_pair(
        DEMASTER_ROOT / "Staging - 2x Upscaled",
        DEMASTER_ROOT / "Staging - 4x Upscaled",
    )

    _sync_2x_4x_pair(
        UPSCALED_UI_ROOT / "Staging - 2x Upscaled",
        UPSCALED_UI_ROOT / "Staging - 4x Upscaled",
    )


def ensure_conversion_csv_for_all_jobs() -> None:
    """
    For every 'folders to process.txt' under all staging roots,
    ensure a 'conversion_hashes.csv' exists beside it with the correct header.
    """
    for root in STAGING_ROOTS:
        if not root.is_dir():
            continue

        for txt in root.rglob(FOLDERS_TXT_NAME):
            if not txt.is_file():
                continue

            job_dir = txt.parent
            csv_path = job_dir / CONVERSION_CSV_NAME

            if csv_path.exists():
                continue

            print(f"[INFO] Creating missing {CONVERSION_CSV_NAME}: {csv_path}")
            try:
                # newline="" to avoid double newlines on Windows
                csv_path.write_text(CONVERSION_CSV_HEADER, encoding="utf-8", newline="")
            except OSError as e:
                print(f"[ERROR] Failed to create {csv_path}: {e}")


def is_eligible_upscale_job(job_dir: Path) -> bool:
    """
    Only generate not_in_folder/unprocessed_folders for jobs whose path
    clearly sits under either ovr_stm/_win or flatlist/_win.
    Comparison is done case-insensitively on the normalized path string.
    """
    p = str(job_dir).replace("\\", "/").lower()

    return (
        "/ovr_stm/_win/" in p
        or p.endswith("/ovr_stm/_win")
        or "/flatlist/_win/" in p
        or p.endswith("/flatlist/_win")
    )


def generate_not_in_folder_for_tier(
    root: Path,
    dim_names: dict[str, str],
    ps2_texture_index: dict[str, Path],
    never_upscale_stems: set[str],
) -> None:
    jobs = find_jobs(root)
    if not jobs:
        print(f"[INFO] No jobs under {root} for not_in_folder.csv generation.")
        return

    print(f"[INFO] Generating {NOT_IN_FOLDER_CSV_NAME} and {UNPROCESSED_FOLDERS_CSV_NAME} for {len(jobs)} job(s) under {root}")
    for job_dir in jobs:
        if not is_eligible_upscale_job(job_dir):
            print(f"[INFO] Skipping not_in_folder generation for non-target job: {job_dir}")
            continue

        write_not_in_folder_csv(job_dir, dim_names, ps2_texture_index, never_upscale_stems)


def write_self_remade_modified_dates() -> None:
    """
    Walk all .png and .tga files under Self Remade\\Finalized (except
    the 'Source Files' subdirectory) and write stems + chosen timestamp
    (earlier of ctime and mtime) to self_remade_modified_dates.csv in
    the parent folder of each of:
      - BUGFIX_ROOT
      - DEMASTER_ROOT
      - UPSCALED_UI_ROOT

    If multiple files share the same stem, only the earliest timestamp
    across all of them is kept.
    """
    target_dir = SELF_REMADE_FINALIZED_DIR

    if not target_dir.is_dir():
        print(f"[WARN] Self Remade Finalized directory does not exist: {target_dir}")
        return

    # Determine all output roots that actually exist on disk
    output_roots: list[Path] = []
    for project_root in (BUGFIX_ROOT, DEMASTER_ROOT, UPSCALED_UI_ROOT):
        parent = project_root.parent
        if parent.is_dir():
            output_roots.append(parent)

    if not output_roots:
        print("[WARN] No valid parent directories found for writing self_remade_modified_dates.csv")
        return

    print()
    print("#################################################")
    print(f"Collecting modified dates for Self Remade Finalized under: {target_dir}")
    print(f"Skipping: {target_dir / 'Source Files'}")
    print("Will write self_remade_modified_dates.csv to:")
    for out_root in output_roots:
        print(f"  - {out_root / SELF_REMADE_MODIFIED_DATES_CSV_NAME}")
    print("#################################################")

    # stem -> earliest chosen_time
    stem_to_time: dict[str, int] = {}

    skip_dir_name = "source files"

    for root_dir, dirnames, filenames in os.walk(target_dir):
        # Prevent recursion into Source Files (case-insensitive)
        dirnames[:] = [d for d in dirnames if d.lower() != skip_dir_name]

        base = Path(root_dir)
        for fname in filenames:
            path = base / fname
            if not path.is_file():
                continue

            suffix = path.suffix.lower()
            if suffix not in {".png", ".tga"}:
                continue

            try:
                stat = path.stat()
                mtime = int(stat.st_mtime)
                ctime = int(stat.st_ctime)

                # Prefer the earlier timestamp between ctime and mtime
                chosen_time = ctime if ctime < mtime else mtime

            except OSError as e:
                print(f"[ERROR] Failed to stat {path}: {e}")
                continue

            stem = path.stem

            existing = stem_to_time.get(stem)
            if existing is None or chosen_time < existing:
                stem_to_time[stem] = chosen_time

    # Convert to sorted list of (stem, time)
    rows = sorted(stem_to_time.items(), key=lambda r: r[0])

    # Write the same CSV content to each parent folder
    for out_root in output_roots:
        csv_path = out_root / SELF_REMADE_MODIFIED_DATES_CSV_NAME

        try:
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["stem", "modified_unix_time"])
                for stem, mtime in rows:
                    writer.writerow([stem, mtime])

            print(f"[INFO] Wrote {len(rows)} entries to {csv_path}")
        except OSError as e:
            print(f"[ERROR] Failed to write {csv_path}: {e}")


# ==========================================================
# MAIN
# ==========================================================
def main() -> None:
    # Very first step: sync 2x folders_to_process with 4x for all projects
    sync_2x_folders_txt_with_4x()

    # Second step: ensure every job has a conversion_hashes.csv with header
    ensure_conversion_csv_for_all_jobs()

    if not STAGING_MAIN_PATH.is_file():
        print(f"ERROR: _staging_main.py not found at: {STAGING_MAIN_PATH}")
        sys.exit(1)

    # Set up git root and PS2 data
    git_root = get_git_root()

    dimensions_csv = (
        git_root
        / "external"
        / "MGS2-PS2-Textures"
        / "u - dumped from substance"
        / "mgs2_ps2_dimensions.csv"
    )
    dim_names = load_dimensions_names(dimensions_csv)

    ps2_textures_root = git_root / "Texture Fixes" / "ps2 textures"
    ps2_texture_index = build_ps2_texture_index(ps2_textures_root)

    # Load never_upscale.txt from repo
    never_upscale_path = git_root / NEVER_UPSCALE_REL_PATH
    never_upscale_stems = load_never_upscale_stems(never_upscale_path)

    for root in STAGING_ROOTS:
        print()
        print("#################################################")
        print(f"Processing staging root: {root}")
        print("#################################################")

        # Run the actual staging pipeline for this tier
        run_tier(root)

        # Decide whether to apply never_upscale filter for this tier
        root_lower = str(root).lower()
        if "2x upscaled" in root_lower or "4x upscaled" in root_lower:
            tier_blocklist = never_upscale_stems
        else:
            tier_blocklist = set()

        # After the tier has finished, generate not_in_folder.csv and unprocessed_folders.csv for each job
        generate_not_in_folder_for_tier(root, dim_names, ps2_texture_index, tier_blocklist)

    print()
    print("[INFO] All staging roots processed.")

    # Final step: update ctxr modified dates
    run_set_ctxr_dates()

    # Extra final step: capture modified dates for Self Remade Finalized
    write_self_remade_modified_dates()


if __name__ == "__main__":
    main()
