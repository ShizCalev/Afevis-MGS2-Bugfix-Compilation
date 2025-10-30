import os
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
ROOT_DIR = os.getcwd()  # current directory; change if needed
OUTPUT_FILE = os.path.join(ROOT_DIR, "original-sha1-hashes.txt")
THREADS = 12  # adjust for your CPU cores

# ==========================================================
# GLOBALS
# ==========================================================
print_lock = Lock()

# ==========================================================
# HELPERS
# ==========================================================
def calc_sha1(path: str) -> str:
    """Compute SHA1 hash for a file."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def process_file(file_path: str) -> tuple[str, str]:
    """Calculate SHA1 and return (relative_path, sha1)."""
    rel_path = os.path.relpath(file_path, ROOT_DIR)
    sha1 = calc_sha1(file_path)
    return (rel_path, sha1)


def find_csv_files(root: str):
    """Recursively find all .csv files."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".csv"):
                yield os.path.join(dirpath, name)


# ==========================================================
# MAIN
# ==========================================================
def main():
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    csv_files = list(find_csv_files(ROOT_DIR))
    total = len(csv_files)
    if total == 0:
        print("No CSV files found.")
        return

    print(f"Found {total} CSV files. Starting SHA1 computation...")

    results = []

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = {executor.submit(process_file, path): path for path in csv_files}

        for i, future in enumerate(as_completed(futures), 1):
            file_path = futures[future]
            try:
                rel_path, sha1 = future.result()
                results.append((rel_path, sha1))
                with print_lock:
                    print(f"[{i}/{total}] {rel_path} => {sha1}")
            except Exception as e:
                with print_lock:
                    print(f"[ERROR] {file_path}: {e}")

    # Sort lexicographically by relative path
    results.sort(key=lambda x: x[0].lower())

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out_f:
        for rel_path, sha1 in results:
            out_f.write(f"{rel_path},{sha1}\n")

    print(f"\nSHA1 hash log written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
