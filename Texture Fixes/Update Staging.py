from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================================
# CONFIG
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent

STAGING_ORDER = [
    "Staging",
    "Staging - 2x Upscaled",
    "Staging - 4x Upscaled",
]

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


# ==========================================================
# HELPERS
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


def run_tier(root: Path) -> None:
    """
    Run all jobs under a single staging root in parallel.
    Wait for all jobs in this tier to finish before returning.
    """
    jobs = find_jobs(root)

    if not jobs:
        print(f"[INFO] No '{FOLDERS_TXT_NAME}' found under {root}")
        return

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


def sync_2x_folders_txt_with_4x() -> None:
    """
    Sync logic:
      - Remove any 2x 'folders to process.txt' that do not exist in 4x
      - Overwrite 2x with 4x if contents differ
      - Create missing 2x files if they exist in 4x
      - Remove now empty directories under 2x
    """
    root_2x = SCRIPT_DIR / "Staging - 2x Upscaled"
    root_4x = SCRIPT_DIR / "Staging - 4x Upscaled"

    if not root_2x.is_dir():
        print("[INFO] 2x staging root does not exist, skipping 2x sync.")
        return

    if not root_4x.is_dir():
        print("[WARN] 4x staging root does not exist, skipping 2x sync.")
        return

    # Collect all relative FOLDERS_TXT paths under 4x
    rel_paths_4x: set[Path] = set()
    for txt_4x in root_4x.rglob(FOLDERS_TXT_NAME):
        if txt_4x.is_file():
            rel_paths_4x.add(txt_4x.relative_to(root_4x))

    if not rel_paths_4x:
        print("[WARN] No 'folders to process.txt' found under 4x, skipping 2x sync.")
        return

    print("[INFO] Syncing 'folders to process.txt' between 2x and 4x tiers")

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


def ensure_conversion_csv_for_all_jobs() -> None:
    """
    For every 'folders to process.txt' under all staging roots,
    ensure a 'conversion_hashes.csv' exists beside it with the correct header.
    """
    for staging_name in STAGING_ORDER:
        root = SCRIPT_DIR / staging_name
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


# ==========================================================
# MAIN
# ==========================================================
def main() -> None:
    # Very first step: sync 2x folders_to_process with 4x
    sync_2x_folders_txt_with_4x()

    # Second step: ensure every job has a conversion_hashes.csv with header
    ensure_conversion_csv_for_all_jobs()

    if not STAGING_MAIN_PATH.is_file():
        print(f"ERROR: _staging_main.py not found at: {STAGING_MAIN_PATH}")
        sys.exit(1)

    for staging_name in STAGING_ORDER:
        root = SCRIPT_DIR / staging_name

        print()
        print("#################################################")
        print(f"Processing staging root: {root}")
        print("#################################################")

        run_tier(root)

    print()
    print("[INFO] All staging roots processed.")

    # Final step
    run_set_ctxr_dates()


if __name__ == "__main__":
    main()
