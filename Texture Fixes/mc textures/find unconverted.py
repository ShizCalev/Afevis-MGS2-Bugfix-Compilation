import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "missing_png_for_ctxr.txt"
MAX_WORKERS = max(4, os.cpu_count() or 4)

print_lock = Lock()


def check_file(ctxr_path: Path) -> Path | None:
    png_path = ctxr_path.with_suffix(".png")
    if not png_path.exists():
        return ctxr_path
    return None


def main():
    # Collect all .ctxr files first (single-threaded walk)
    ctxr_files = []
    for root, _, files in os.walk(SCRIPT_DIR):
        for f in files:
            if f.lower().endswith(".ctxr"):
                ctxr_files.append(Path(root) / f)

    if not ctxr_files:
        print("No .ctxr files found. Nothing to do.")
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        return

    missing = []

    # Multithread the checking phase
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {exe.submit(check_file, p): p for p in ctxr_files}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                with print_lock:
                    print(f"[NO PNG] {result}")
                missing.append(result)

    # Handle logging or clean-up
    if missing:
        with open(LOG_FILE, "w", encoding="utf8") as log:
            for m in missing:
                log.write(str(m) + "\n")
        print(f"\nMissing PNG entries logged to: {LOG_FILE}")
        print(f"Total missing: {len(missing)}")
    else:
        print("No missing PNGs found.")
        if LOG_FILE.exists():
            LOG_FILE.unlink()
            print(f"Removed {LOG_FILE} (not needed).")


if __name__ == "__main__":
    main()
