import csv
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================================
# CONFIG
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR  # recurse from where the script lives
CSV_FILE = SCRIPT_DIR / "MC real file dates.csv"
THREADS = max(4, os.cpu_count() or 4)


# ==========================================================
# HELPERS
# ==========================================================
def load_csv_mapping(csv_path: Path):
    """
    Load CSV into a mapping: sha1 (lowercase) -> (texture_name, unix_timestamp_utc)
    CSV format:
        texture_name,modified_time_utc,sha1
        00002016,2011-10-13 - 19:33:42 UTC,91afc03c9ce3...
    """
    mapping = {}

    if not csv_path.is_file():
        raise SystemExit(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tex_name = row["texture_name"].strip()
            time_str = row["modified_time_utc"].strip()
            sha1 = row["sha1"].strip().lower()

            if not sha1:
                continue

            # Parse "2011-10-13 - 19:33:42 UTC"
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d - %H:%M:%S UTC")
                dt = dt.replace(tzinfo=timezone.utc)
                ts = dt.timestamp()
            except Exception as e:
                print(f"Failed to parse datetime '{time_str}' for {tex_name}: {e}")
                continue

            mapping[sha1] = (tex_name, ts)

    print(f"Loaded {len(mapping)} records from CSV.")
    return mapping


def sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def set_mtime(path: Path, timestamp: float):
    """
    Set both atime and mtime to the given UTC timestamp.
    """
    try:
        os.utime(path, (timestamp, timestamp))
    except Exception as e:
        print(f"Failed to set mtime for {path}: {e}")


def process_ctxr(path: Path, sha_map: dict):
    """
    Worker for a single ctxr file:
      - compute sha1
      - if sha1 matches CSV, set mtime of ctxr and sibling png
    """
    try:
        file_sha1 = sha1_file(path)
    except Exception as e:
        print(f"Failed to hash {path}: {e}")
        return 0

    entry = sha_map.get(file_sha1)
    if entry is None:
        return 0

    tex_name, ts = entry

    # Set ctxr mtime
    set_mtime(path, ts)

    # If sibling PNG exists, set its mtime too
    png_path = path.with_suffix(".png")
    if png_path.is_file():
        set_mtime(png_path, ts)

    print(f"Matched SHA1 for {path.name} (texture_name={tex_name}), updated mtime.")
    return 1


# ==========================================================
# MAIN
# ==========================================================
def main():
    sha_map = load_csv_mapping(CSV_FILE)

    ctxr_files = sorted(ROOT_DIR.rglob("*.ctxr"))
    if not ctxr_files:
        print(f"No .ctxr files found under {ROOT_DIR}")
        return

    print(f"Found {len(ctxr_files)} .ctxr files. Processing...")

    total_matches = 0

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        future_to_path = {
            executor.submit(process_ctxr, path, sha_map): path for path in ctxr_files
        }

        for future in as_completed(future_to_path):
            try:
                result = future.result()
                if result:
                    total_matches += result
            except Exception as e:
                path = future_to_path[future]
                print(f"Error processing {path}: {e}")

    print(f"Done. Updated timestamps for {total_matches} matching files.")


if __name__ == "__main__":
    main()
