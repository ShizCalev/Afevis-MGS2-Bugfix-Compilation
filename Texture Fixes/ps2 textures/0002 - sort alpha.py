import os
import shutil
import threading
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from datetime import timedelta
import sys

# ==========================================================
# CONFIGURATION
# ==========================================================
# Resolve repo root dynamically from script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Relative paths from repo root
ROOT_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
OPAQUE_DIR = os.path.join(ROOT_DIR, "OPAQUE")
HAS_ALPHA_DIR = os.path.join(ROOT_DIR, "HAS ALPHA")
NEXT_SCRIPT = os.path.join(SCRIPT_DIR, "0003 - sort bp remade.py")

MAX_WORKERS = 12
UPDATE_INTERVAL = 1.0  # seconds between progress updates

# ==========================================================
# UTILITIES
# ==========================================================
def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def has_only_specific_alpha(img):
    """Return True if alpha channel is only 128, 255, or not present."""
    if img.mode not in ("RGBA", "LA"):
        return True  # no alpha channel -> opaque

    alpha = img.getchannel("A")
    extrema = alpha.getextrema()
    if not extrema:
        return True

    min_a, max_a = extrema
    if min_a == max_a == 255:
        return True
    if min_a == max_a == 128:
        return True
    return False


def process_file(path):
    """Check alpha and move accordingly."""
    try:
        with Image.open(path) as img:
            rel_name = os.path.basename(path)
            if has_only_specific_alpha(img):
                dest_path = os.path.join(OPAQUE_DIR, rel_name)
                ensure_dir(dest_path)
                shutil.move(path, dest_path)
                return "OPAQUE"
            else:
                dest_path = os.path.join(HAS_ALPHA_DIR, rel_name)
                ensure_dir(dest_path)
                shutil.move(path, dest_path)
                return "HAS_ALPHA"
    except Exception as e:
        return f"ERROR: {e}"


def progress_monitor(total, counter, start_time, stop_event):
    while not stop_event.is_set():
        processed = counter["processed"]
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        pct = (processed / total) * 100 if total else 0
        eta = str(timedelta(seconds=int(remaining)))
        print(f"\r[Progress] {processed}/{total} ({pct:.1f}%) | ETA: {eta}", end="", flush=True)
        time.sleep(UPDATE_INTERVAL)
    print()  # newline after finishing


# ==========================================================
# MAIN
# ==========================================================
def main():
    print(f"[+] Repo root: {REPO_ROOT}")
    print(f"[+] Scanning top-level of: {ROOT_DIR}")

    files = [os.path.join(ROOT_DIR, f) for f in os.listdir(ROOT_DIR)
             if f.lower().endswith((".png", ".tga"))]

    total = len(files)
    print(f"[+] Found {total} candidate files.")
    counter = {"processed": 0}
    errors = []
    opaque = []
    has_alpha = []

    stop_event = threading.Event()
    start_time = time.time()
    monitor_thread = threading.Thread(target=progress_monitor, args=(total, counter, start_time, stop_event))
    monitor_thread.start()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, f) for f in files]
        for fut in as_completed(futures):
            result = fut.result()
            counter["processed"] += 1
            if result == "OPAQUE":
                opaque.append(result)
            elif result == "HAS_ALPHA":
                has_alpha.append(result)
            elif result and result.startswith("ERROR"):
                errors.append(result)

    stop_event.set()
    monitor_thread.join()

    print(f"\n[+] Moved {len(opaque)} opaque/128 images to '{OPAQUE_DIR}'")
    print(f"[+] Moved {len(has_alpha)} images with other alpha values to '{HAS_ALPHA_DIR}'")
    if errors:
        print(f"[!] {len(errors)} errors encountered:")
        for err in errors:
            print("   ", err)

    # --- Run the next script automatically ---
    if os.path.exists(NEXT_SCRIPT):
        print(f"\n[+] Running next script: {NEXT_SCRIPT}")
        try:
            subprocess.run([sys.executable, NEXT_SCRIPT], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Next script failed with exit code {e.returncode}")
    else:
        print(f"[!] Next script not found: {NEXT_SCRIPT}")


if __name__ == "__main__":
    main()
