import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
# Resolve repo root dynamically from script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Relative paths
SRC_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures", "OPAQUE", "bp_remade")
CTXR_SOURCE = os.path.join(REPO_ROOT, "external", "MGS2-PS2-Textures", "flatlist", "_win")
DEST_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "mc textures", "opaque", "bp_remade")
ROGUE_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "mc textures", "opaque", "ROGUE FILE")

THREADS = 12
LOG_PATH = os.path.join(SCRIPT_DIR, "missing_ctxr_log.txt")

# Next stage scripts
NEXT_SCRIPT_1 = os.path.join(SCRIPT_DIR, "0006 - strip alpha from opaque mc pngs.py")
NEXT_SCRIPT_2 = os.path.join(SCRIPT_DIR, "0009 - find incorrect ps2 to mc alpha levels.py")

# ==========================================================
# UTILITIES
# ==========================================================
print_lock = Lock()

def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def find_ctxr(target_name):
    """Find ctxr file in CTXR_SOURCE with matching name (no extension)."""
    name_no_ext = os.path.splitext(target_name)[0].lower()
    for root, _, files in os.walk(CTXR_SOURCE):
        for f in files:
            if f.lower().endswith(".ctxr") and os.path.splitext(f)[0].lower() == name_no_ext:
                return os.path.join(root, f)
    return None


def copy_ctxr(file_path):
    """Locate and copy ctxr file if found, skip if already exists."""
    rel_path = os.path.relpath(file_path, SRC_DIR)
    rel_base = os.path.splitext(rel_path)[0] + ".ctxr"
    dest_path = os.path.join(DEST_DIR, rel_base)

    if os.path.exists(dest_path):
        with print_lock:
            print(f"[Skipped - already exists] {dest_path}")
        return "skipped"

    match = find_ctxr(os.path.basename(file_path))
    if not match:
        with print_lock:
            print(f"[Missing] {file_path}")
        return file_path  # return full path for logging

    try:
        ensure_dir(dest_path)
        shutil.copy2(match, dest_path)
        with print_lock:
            print(f"[Copied] {match} → {dest_path}")
        return "copied"
    except Exception as e:
        with print_lock:
            print(f"[Error] {file_path}: {e}")
        return "error"


def get_all_textures(root_dir):
    """Recursively gather all .png and .tga files."""
    files = []
    for root, _, fns in os.walk(root_dir):
        for f in fns:
            if f.lower().endswith((".png", ".tga")):
                files.append(os.path.join(root, f))
    return files


# ==========================================================
# ROGUE CHECK
# ==========================================================
def find_rogue_pngs():
    """Find .png files in DEST_DIR without matching .ctxr and move to ROGUE_DIR."""
    rogue_files = []
    for root, _, files in os.walk(DEST_DIR):
        for f in files:
            if f.lower().endswith(".png"):
                png_path = os.path.join(root, f)
                ctxr_path = os.path.splitext(png_path)[0] + ".ctxr"
                if not os.path.exists(ctxr_path):
                    rogue_files.append(png_path)

    if not rogue_files:
        print("[+] No rogue PNGs detected.")
        return 0

    rogue_files.sort(key=lambda x: (os.path.dirname(x).lower(), os.path.basename(x).lower()))
    print(f"[!] Found {len(rogue_files)} rogue PNGs. Moving to: {ROGUE_DIR}")

    for path in rogue_files:
        rel_path = os.path.relpath(path, DEST_DIR)
        dest_path = os.path.join(ROGUE_DIR, rel_path)
        ensure_dir(dest_path)
        try:
            shutil.move(path, dest_path)
            with print_lock:
                print(f"[Moved → ROGUE FILE] {path}")
        except Exception as e:
            with print_lock:
                print(f"[Error moving rogue file] {path}: {e}")

    return len(rogue_files)


# ==========================================================
# STAGE RUNNER
# ==========================================================
def run_next_stage(script_path):
    """Run the next Python script, handling output and errors cleanly."""
    print(f"\n[+] Launching next stage: {os.path.basename(script_path)}")
    try:
        subprocess.run(["python", script_path], check=True)
        print(f"[✓] Stage completed successfully: {os.path.basename(script_path)}")
    except subprocess.CalledProcessError as e:
        print(f"[!] Stage failed with non-zero exit code ({e.returncode}): {script_path}")
    except FileNotFoundError:
        print(f"[!] Stage script not found: {script_path}")
    except Exception as e:
        print(f"[!] Failed to launch next stage ({script_path}): {e}")


# ==========================================================
# MAIN
# ==========================================================
def main():
    print(f"[+] Repo root: {REPO_ROOT}")
    all_textures = get_all_textures(SRC_DIR)
    print(f"[+] Found {len(all_textures)} texture files in {SRC_DIR}")

    results = {"copied": 0, "skipped": 0, "error": 0}
    missing_files = []

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(copy_ctxr, f) for f in all_textures]
        for fut in as_completed(futures):
            res = fut.result()
            if res == "copied":
                results["copied"] += 1
            elif res == "skipped":
                results["skipped"] += 1
            elif res == "error":
                results["error"] += 1
            elif isinstance(res, str) and os.path.isabs(res):
                missing_files.append(res)

    # --- Write missing log ---
    if missing_files:
        missing_files.sort(key=lambda x: (os.path.dirname(x).lower(), os.path.basename(x).lower()))
        with open(LOG_PATH, "w", encoding="utf-8") as log:
            log.write("\n".join(missing_files))
        print(f"[+] Logged {len(missing_files)} missing ctxr files to: {LOG_PATH}")
    else:
        print("[+] No missing ctxr files detected.")

    print("\n[+] Copy Stage Completed.")
    print(f"    Copied : {results['copied']}")
    print(f"    Skipped: {results['skipped']}")
    print(f"    Errors : {results['error']}")
    print(f"    Missing: {len(missing_files)}")

    # --- Rogue PNG verification ---
    print("\n[+] Starting rogue PNG verification...")
    rogue_count = find_rogue_pngs()
    print(f"[+] Rogue verification complete. Total rogue PNGs moved: {rogue_count}")

    # --- Launch subsequent stages ---
    #run_next_stage(NEXT_SCRIPT_1)
    run_next_stage(NEXT_SCRIPT_2)


if __name__ == "__main__":
    main()
