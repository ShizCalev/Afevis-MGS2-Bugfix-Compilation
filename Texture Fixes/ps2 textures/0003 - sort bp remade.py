import os
import csv
import math
import shutil
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
# Resolve repo root dynamically from script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Relative paths from repo root
CSV_PATH = os.path.join(REPO_ROOT, "external", "MGS2-PS2-Textures", "u - dumped from substance", "mgs2_mc_dimensions.csv")
ROOT_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
HAS_ALPHA_DIR = os.path.join(ROOT_DIR, "HAS ALPHA")
NO_MIP_REGEX_FILE = os.path.join(REPO_ROOT, "Texture Fixes", "no_mip_regex.txt")

BLACKLIST = ["processed", "bp_remade"]
THREADS = 12

# Manual blacklist (filenames without extension)
MANUAL_LIST = {
    "0015d707",
    "0015d707_cd82fa959c0f81d19f22c0b0fdf8d230",
    "008ae623",
    "008ae623_fad237f35f44f84013d072b01d34bfc0",
}

# Manual UI override list (filenames without extension)
MANUAL_UI_FILE = os.path.join(SCRIPT_DIR, "manual_ui_textures.txt")

# Follow-up script path (same folder as this one)
FOLLOWUP_SCRIPT = os.path.join(SCRIPT_DIR, "0004 - log opaque with wrong alpha.py")

# ==========================================================
# UTILITIES
# ==========================================================
print_lock = Lock()


def read_csv_dimensions(path):
    dims = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["texture_name"].strip().lower()
            try:
                dims[name] = (int(row["mc_width"]), int(row["mc_height"]))
            except ValueError:
                continue
    return dims


def next_power_of_two(n):
    return 1 if n <= 0 else 1 << (n - 1).bit_length()


def is_power_of_two(n):
    return n > 0 and (n & (n - 1) == 0)


def should_skip(path):
    p = path.lower()
    return any(term in p for term in BLACKLIST)


def move_file(file_path, folder_name):
    dest_dir = os.path.join(os.path.dirname(file_path), folder_name)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(file_path))
    try:
        shutil.move(file_path, dest_path)
        with print_lock:
            print(f"[Moved → {folder_name}] {file_path}")
    except Exception as e:
        with print_lock:
            print(f"[Error moving] {file_path}: {e}")


# ==========================================================
# MANUAL BLACKLIST HANDLING
# ==========================================================
def handle_manual_blacklist(file_path):
    """If filename (no extension) is in manual list, move to /manual and skip."""
    lower_path = file_path.lower()
    if "manual" in lower_path:
        return False  # already inside manual, skip moving again

    name = os.path.splitext(os.path.basename(file_path))[0].lower()
    if name in MANUAL_LIST:
        move_file(file_path, "manual")
        return True
    return False


# ==========================================================
# BP_REMADE CHECKS
# ==========================================================
def check_bp_remade(file_path, dims_map):
    if handle_manual_blacklist(file_path):
        return
    name = os.path.splitext(os.path.basename(file_path))[0].lower()
    if name not in dims_map:
        return
    try:
        with Image.open(file_path) as img:
            width, height = img.size
    except Exception as e:
        with print_lock:
            print(f"[Error reading] {file_path}: {e}")
        return
    mc_w, mc_h = dims_map[name]
    if mc_w > next_power_of_two(width) or mc_h > next_power_of_two(height):
        move_file(file_path, "bp_remade")


def check_has_alpha_file(file_path, dims_map):
    if handle_manual_blacklist(file_path):
        return
    name = os.path.splitext(os.path.basename(file_path))[0].lower()
    if name not in dims_map:
        return
    try:
        with Image.open(file_path) as img:
            width, height = img.size
    except Exception as e:
        with print_lock:
            print(f"[Error reading] {file_path}: {e}")
        return

    pow2_w = next_power_of_two(width)
    pow2_h = next_power_of_two(height)
    mc_w, mc_h = dims_map[name]

    if mc_w < pow2_w or mc_h < pow2_h:
        move_file(file_path, "bp_mismatch")
    elif is_power_of_two(width) and is_power_of_two(height):
        move_file(file_path, "power of two")


# ==========================================================
# STAGE 3: NO-MIP FIX DETECTION
# ==========================================================
def load_no_mip_patterns(path):
    patterns = []
    if not os.path.exists(path):
        print(f"[!] No-Mip regex file not found: {path}")
        return patterns

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                patterns.append(re.compile(line, re.IGNORECASE))
            except re.error as e:
                print(f"[!] Invalid regex skipped: {line} ({e})")

    print(f"[+] Loaded {len(patterns)} no-mip regex patterns.")
    return patterns


def matches_no_mip_patterns(filename, patterns):
    for p in patterns:
        if p.search(filename):
            return True
    return False


def check_no_mip_fix(file_path, patterns):
    if handle_manual_blacklist(file_path):
        return
    lower_path = file_path.lower()
    if "processed" in lower_path or "no_mip_fixes" in lower_path:
        return

    name_no_ext = os.path.splitext(os.path.basename(file_path))[0].lower()
    if matches_no_mip_patterns(name_no_ext, patterns):
        dest_dir = os.path.join(os.path.dirname(file_path), "no_mip_fixes")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, os.path.basename(file_path))
        try:
            shutil.move(file_path, dest_path)
            with print_lock:
                print(f"[Moved → no_mip_fix] {file_path}")
        except Exception as e:
            with print_lock:
                print(f"[Error moving to no_mip_fix] {file_path}: {e}")


# ==========================================================
# STAGE 4: NPOT UI / NOT_REGEX_MATCHED_UI
# ==========================================================
def handle_npot_ui_file(file_path, npot_names, patterns):
    if handle_manual_blacklist(file_path):
        return 0

    lower_path = file_path.lower()

    # Already in a final destination folder, skip
    if (
        "no_mip_fixes" in lower_path
        and (f"{os.sep}ui{os.sep}" in lower_path or "not_regex_matched_ui" in lower_path)
    ):
        return 0

    name_no_ext = os.path.splitext(os.path.basename(file_path))[0].lower()
    if name_no_ext not in npot_names:
        return 0

    # Figure out the correct base no_mip_fixes directory:
    #   - if the path already contains a no_mip_fixes segment, use that as base
    #   - otherwise, create a no_mip_fixes folder next to the current file
    dirpath = os.path.dirname(file_path)
    parts = dirpath.split(os.sep)
    parts_lower = [p.lower() for p in parts]

    if "no_mip_fixes" in parts_lower:
        idx = parts_lower.index("no_mip_fixes")
        base_dir = os.sep.join(parts[:idx + 1])
    else:
        base_dir = os.path.join(dirpath, "no_mip_fixes")

    # Decide final subfolder
    if matches_no_mip_patterns(name_no_ext, patterns):
        dest_dir = os.path.join(base_dir, "ui")
        label = "ui"
    else:
        dest_dir = os.path.join(base_dir, "not_regex_matched_ui")
        label = "not_regex_matched_ui"

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, os.path.basename(file_path))

    try:
        shutil.move(file_path, dest_path)
        with print_lock:
            print(f"[NPOT → {label}] {file_path}")
        return 1
    except Exception as e:
        with print_lock:
            print(f"[Error NPOT move] {file_path}: {e}")
        return 0


def stage4_npot_ui_move(dims_map, patterns):
    # Collect all CSV entries with NPOT mc dimensions
    npot_names = set()
    for name, (mc_w, mc_h) in dims_map.items():
        if not is_power_of_two(mc_w) or not is_power_of_two(mc_h):
            npot_names.add(name)

    print(f"[+] Stage 4: Found {len(npot_names)} NPOT CSV entries (mc_width/mc_height).")

    # Walk filesystem and move any matching textures
    candidate_files = []
    for root, _, files in os.walk(ROOT_DIR):
        for f in files:
            if f.lower().endswith((".png", ".tga")):
                candidate_files.append(os.path.join(root, f))

    print(f"[+] Stage 4: Scanning {len(candidate_files)} texture files for NPOT UI classification...")

    moved_count = 0
    with ThreadPoolExecutor(max_workers=THREADS) as exe:
        futures = [exe.submit(handle_npot_ui_file, path, npot_names, patterns) for path in candidate_files]
        for fut in as_completed(futures):
            moved_count += fut.result() or 0

    print(f"[+] Stage 4: Completed NPOT UI sorting. Moved {moved_count} files.")


# ==========================================================
# STAGE 5: MANUAL UI OVERRIDES INSIDE no_mip_fixes
# ==========================================================
def load_manual_ui_list(path):
    manual_set = set()
    if not os.path.exists(path):
        print(f"[!] Manual UI texture list not found: {path}")
        return manual_set

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            manual_set.add(line.lower())

    print(f"[+] Loaded {len(manual_set)} manual UI texture names.")
    return manual_set


def handle_manual_ui_file(file_path, manual_ui_set):
    # Only operate on files inside a no_mip_fixes folder
    lower_path = file_path.lower()
    if "no_mip_fixes" not in lower_path:
        return 0

    # Skip if already inside .../no_mip_fixes/ui/...
    if f"{os.sep}no_mip_fixes{os.sep}ui{os.sep}" in lower_path:
        return 0

    name_no_ext = os.path.splitext(os.path.basename(file_path))[0].lower()
    if name_no_ext not in manual_ui_set:
        return 0

    dirpath = os.path.dirname(file_path)
    parts = dirpath.split(os.sep)
    parts_lower = [p.lower() for p in parts]

    # Find base no_mip_fixes dir for this file
    if "no_mip_fixes" not in parts_lower:
        return 0

    idx = parts_lower.index("no_mip_fixes")
    base_dir = os.sep.join(parts[:idx + 1])
    dest_dir = os.path.join(base_dir, "ui")
    os.makedirs(dest_dir, exist_ok=True)

    dest_path = os.path.join(dest_dir, os.path.basename(file_path))
    try:
        shutil.move(file_path, dest_path)
        with print_lock:
            print(f"[Manual UI] {file_path} → {dest_path}")
        return 1
    except Exception as e:
        with print_lock:
            print(f"[Error Manual UI move] {file_path}: {e}")
        return 0


def stage5_manual_ui_overrides(manual_ui_set):
    if not manual_ui_set:
        print("[+] Stage 5: No manual UI entries loaded, skipping manual UI overrides.")
        return

    candidate_files = []
    for root, _, files in os.walk(ROOT_DIR):
        if "no_mip_fixes" not in root.lower():
            continue
        for f in files:
            if f.lower().endswith((".png", ".tga")):
                candidate_files.append(os.path.join(root, f))

    print(f"[+] Stage 5: Scanning {len(candidate_files)} files under no_mip_fixes for manual UI overrides...")

    moved_count = 0
    with ThreadPoolExecutor(max_workers=THREADS) as exe:
        futures = [exe.submit(handle_manual_ui_file, path, manual_ui_set) for path in candidate_files]
        for fut in as_completed(futures):
            moved_count += fut.result() or 0

    print(f"[+] Stage 5: Manual UI overrides complete. Moved {moved_count} files to ui.")


# ==========================================================
# MAIN
# ==========================================================
def main():
    print(f"[+] Repo root: {REPO_ROOT}")
    dims_map = read_csv_dimensions(CSV_PATH)
    print(f"[+] Loaded {len(dims_map)} CSV entries")

    # --- Stage 1: recursive bp_remade check ---
    all_files = []
    for root, _, files in os.walk(ROOT_DIR):
        if should_skip(root):
            continue
        for f in files:
            if f.lower().endswith((".png", ".tga")):
                all_files.append(os.path.join(root, f))

    print(f"[+] Stage 1: Checking {len(all_files)} files for bp_remade...")
    with ThreadPoolExecutor(max_workers=THREADS) as exe:
        list(as_completed([exe.submit(check_bp_remade, f, dims_map) for f in all_files]))

    # --- Stage 2: process files in HAS ALPHA subfolder ---
    if not os.path.isdir(HAS_ALPHA_DIR):
        print(f"[!] HAS ALPHA directory not found: {HAS_ALPHA_DIR}")
    else:
        has_alpha_files = [
            os.path.join(HAS_ALPHA_DIR, f)
            for f in os.listdir(HAS_ALPHA_DIR)
            if f.lower().endswith((".png", ".tga"))
        ]
        print(f"[+] Stage 2: Checking {len(has_alpha_files)} files in HAS ALPHA for bp_mismatch/power of two...")
        with ThreadPoolExecutor(max_workers=THREADS) as exe:
            list(as_completed([exe.submit(check_has_alpha_file, f, dims_map) for f in has_alpha_files]))

    # --- Stage 3: no-mip fix check ---
    print("[+] Stage 3: Checking for no-mip regex matches across all subfolders...")
    patterns = load_no_mip_patterns(NO_MIP_REGEX_FILE)

    all_png_tga = []
    for root, _, files in os.walk(ROOT_DIR):
        for f in files:
            if f.lower().endswith((".png", ".tga")):
                all_png_tga.append(os.path.join(root, f))

    print(f"[+] Stage 3: Found {len(all_png_tga)} total candidate textures.")
    with ThreadPoolExecutor(max_workers=THREADS) as exe:
        list(as_completed([exe.submit(check_no_mip_fix, f, patterns) for f in all_png_tga]))

    # --- Stage 4: NPOT mc_width/mc_height → no_mip_fixes/ui or no_mip_fixes/not_regex_matched_ui ---
    stage4_npot_ui_move(dims_map, patterns)

    # --- Stage 5: Manual UI overrides inside no_mip_fixes ---
    manual_ui_set = load_manual_ui_list(MANUAL_UI_FILE)
    stage5_manual_ui_overrides(manual_ui_set)

    print("[+] Completed all stages.")

    # --- Follow-up call ---
    if os.path.exists(FOLLOWUP_SCRIPT):
        print(f"[+] Running follow-up script: {FOLLOWUP_SCRIPT}")
        try:
            subprocess.run(["py", FOLLOWUP_SCRIPT], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Follow-up script returned error code {e.returncode}")
        except Exception as e:
            print(f"[!] Failed to run follow-up script: {e}")
    else:
        print(f"[!] Follow-up script not found: {FOLLOWUP_SCRIPT}")


if __name__ == "__main__":
    main()
