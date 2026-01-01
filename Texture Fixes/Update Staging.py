from __future__ import annotations

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
    #"Staging - 2x Upscaled",
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


# ==========================================================
# MAIN
# ==========================================================
def main() -> None:
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

    # === FINAL STEP ===
    run_set_ctxr_dates()


if __name__ == "__main__":
    main()
