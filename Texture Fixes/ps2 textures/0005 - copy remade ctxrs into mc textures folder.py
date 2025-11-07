import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import multiprocessing

# ==========================================================
# CONFIGURATION
# ==========================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Root search folders
PS2_ROOT = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
MC_ROOT = os.path.join(REPO_ROOT, "Texture Fixes", "mc textures")

# Correct CTXR source path
CTXR_SOURCE = r"G:\Steam\steamapps\common\MGS2\textures\flatlist\_win"

ROGUE_DIR = os.path.join(MC_ROOT, "ROGUE FILE")
LOG_PATH = os.path.join(SCRIPT_DIR, "missing_ctxr_log.txt")

THREADS = max(4, multiprocessing.cpu_count())

# Next stage scripts
NEXT_SCRIPT_1 = os.path.join(SCRIPT_DIR, "0006 - strip alpha from opaque mc pngs.py")
NEXT_SCRIPT_2 = os.path.join(SCRIPT_DIR, "0009 - find incorrect ps2 to mc alpha levels.py")

print_lock = Lock()

# ==========================================================
# UTILITIES
# ==========================================================
def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def normalize_name(filename):
    """Lowercase and remove only the final extension (.png/.tga/.ctxr)."""
    name = filename.lower()
    for ext in (".png", ".tga", ".ctxr"):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def build_ctxr_index():
    """Build lookup index of all .ctxr files in CTXR_SOURCE."""
    print(f"[+] Building CTXR index from: {CTXR_SOURCE}")
    index = {}
    for root, _, files in os.walk(CTXR_SOURCE):
        for f in files:
            if f.lower().endswith(".ctxr"):
                key = normalize_name(f)
                index[key] = os.path.join(root, f)
    print(f"[+] Indexed {len(index)} ctxr files.")
    return index


def should_include_texture(path):
    """
    Determine if a texture should be included:
    - Always include if under OPAQUE/bp_remade/
    - For other folders, only include if under a subfolder of bp_remade/
    """
    rel = os.path.relpath(path, PS2_ROOT)
    parts = rel.lower().split(os.sep)

    if "opaque" in parts and "bp_remade" in parts:
        return True

    if "bp_remade" in parts:
        idx = parts.index("bp_remade")
        if idx < len(parts) - 2:
            return True

    return False


def get_all_bp_remade_textures(root_dir):
    """Recursively find all .png/.tga files under valid bp_remade subfolders."""
    textures = []
    for root, _, files in os.walk(root_dir):
        if "bp_remade" in root.lower():
            for f in files:
                if f.lower().endswith((".png", ".tga")):
                    full_path = os.path.join(root, f)
                    if should_include_texture(full_path):
                        textures.append(full_path)
    return textures


def find_ctxr(target_name, ctxr_index):
    """Find matching ctxr path from index using strict name match."""
    key = normalize_name(target_name)
    return ctxr_index.get(key)


def copy_ctxr(file_path, ctxr_index):
    """Locate and copy ctxr file if found, skip if already exists."""
    rel_path = os.path.relpath(file_path, PS2_ROOT)
    rel_base = os.path.splitext(rel_path)[0] + ".ctxr"
    dest_path = os.path.join(MC_ROOT, rel_base)

    if os.path.exists(dest_path):
        with print_lock:
            print(f"[Skipped - already exists] {dest_path}")
        return "skipped"

    match = find_ctxr(os.path.basename(file_path), ctxr_index)
    if not match:
        with print_lock:
            print(f"[Missing] {file_path}")
        return file_path

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


# ==========================================================
# CLEANUP / SYNC
# ==========================================================
def cleanup_removed_ps2_textures():
    """
    Remove .ctxr files from MC_ROOT that no longer have a corresponding
    .png or .tga in PS2_ROOT under bp_remade.
    """
    print("\n[+] Checking for stale ctxr files in MC textures...")

    removed = 0
    for root, _, files in os.walk(MC_ROOT):
        if "bp_remade" not in root.lower():
            continue

        for f in files:
            if not f.lower().endswith(".ctxr"):
                continue

            mc_ctxr_path = os.path.join(root, f)
            rel_ctxr = os.path.relpath(mc_ctxr_path, MC_ROOT)
            rel_base = os.path.splitext(rel_ctxr)[0]

            ps2_png = os.path.join(PS2_ROOT, rel_base + ".png")
            ps2_tga = os.path.join(PS2_ROOT, rel_base + ".tga")

            if not os.path.exists(ps2_png) and not os.path.exists(ps2_tga):
                try:
                    os.remove(mc_ctxr_path)
                    removed += 1
                    with print_lock:
                        print(f"[Removed stale ctxr] {mc_ctxr_path}")
                except Exception as e:
                    with print_lock:
                        print(f"[Error removing {mc_ctxr_path}] {e}")

    print(f"[+] Cleanup complete. Removed {removed} stale ctxr files.")
    return removed


# ==========================================================
# ROGUE CHECK
# ==========================================================
def find_rogue_pngs():
    """Find .png files in MC_ROOT without matching .ctxr and move to ROGUE_DIR."""
    rogue_files = []
    for root, _, files in os.walk(MC_ROOT):
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
        rel_path = os.path.relpath(path, MC_ROOT)
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

    all_textures = get_all_bp_remade_textures(PS2_ROOT)
    print(f"[+] Found {len(all_textures)} valid textures for processing under ps2 textures.")

    ctxr_index = build_ctxr_index()

    results = {"copied": 0, "skipped": 0, "error": 0}
    missing_files = []

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(copy_ctxr, f, ctxr_index) for f in all_textures]
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

    # --- Cleanup stale ctxr files ---
    cleanup_removed_ps2_textures()

    # --- Rogue PNG verification ---
    print("\n[+] Starting rogue PNG verification...")
    rogue_count = find_rogue_pngs()
    print(f"[+] Rogue verification complete. Total rogue PNGs moved: {rogue_count}")

    # --- Launch subsequent stages ---
    #run_next_stage(NEXT_SCRIPT_1)
    run_next_stage(NEXT_SCRIPT_2)


if __name__ == "__main__":
    main()
