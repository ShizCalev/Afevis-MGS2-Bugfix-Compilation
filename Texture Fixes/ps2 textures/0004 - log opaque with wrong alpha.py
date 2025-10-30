import os
import csv
import ast
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from PIL import Image

# ==========================================================
# CONFIGURATION
# ==========================================================
# Resolve repo root dynamically from this script’s location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Relative paths
ROOT_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
OPAQUE_DIR = os.path.join(ROOT_DIR, "OPAQUE")
HAS_ALPHA_DIR = os.path.join(ROOT_DIR, "HAS ALPHA")
CSV_PATH = os.path.join(REPO_ROOT, "external", "MGS2-PS2-Textures", "u - dumped from substance", "mgs2_mc_dimensions.csv")

LOG_OPAQUE = os.path.join(ROOT_DIR, "MC_Incorrect_Alpha_Levels_For_Opaque.txt")
LOG_TRANSP = os.path.join(ROOT_DIR, "MC_Incorrect_Alpha_Levels_For_Transparents.txt")
THREADS = 12
NEXT_SCRIPT = os.path.join(SCRIPT_DIR, "0005 - copy remade ctxrs into mc textures folder.py")

# ==========================================================
# UTILITIES
# ==========================================================
print_lock = Lock()

def read_csv_alpha_levels(path):
    """Load CSV into dict {texture_name: mc_alpha_levels_string}"""
    data = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["texture_name"].strip().lower()
            data[name] = row["mc_alpha_levels"].strip()
    return data


def get_all_textures(folder):
    """Recursively gather all .png and .tga file paths."""
    paths = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".png", ".tga")):
                paths.append(os.path.join(root, f))
    return paths


# ==========================================================
# PASS 1: OPAQUE
# ==========================================================
def check_opaque_alpha(path, csv_data):
    """Compare CSV mc_alpha_levels for OPAQUE textures."""
    name_no_ext = os.path.splitext(os.path.basename(path))[0].lower()
    alpha = csv_data.get(name_no_ext)
    if alpha and alpha != "[128]":
        return path
    return None


# ==========================================================
# PASS 2: HAS ALPHA
# ==========================================================
def calc_image_alpha_levels(path):
    """Return a sorted list of unique alpha values for an image."""
    try:
        with Image.open(path) as img:
            if img.mode not in ("RGBA", "LA"):
                return [255]
            alpha = img.getchannel("A")
            return sorted(set(alpha.getdata()))
    except Exception:
        return []


def check_transparent_alpha(path, csv_data):
    """Compare actual alpha levels against CSV mc_alpha_levels."""
    name_no_ext = os.path.splitext(os.path.basename(path))[0].lower()
    if name_no_ext not in csv_data:
        return None

    csv_alpha_raw = csv_data[name_no_ext]
    try:
        csv_alpha_levels = ast.literal_eval(csv_alpha_raw)
        if not isinstance(csv_alpha_levels, list):
            csv_alpha_levels = [csv_alpha_raw]
    except Exception:
        csv_alpha_levels = [csv_alpha_raw]

    img_levels = calc_image_alpha_levels(path)
    if not img_levels or set(img_levels) != set(csv_alpha_levels):
        return path
    return None


# ==========================================================
# PASS RUNNER
# ==========================================================
def run_pass(label, folder, func, csv_data, log_path):
    print(f"[+] {label}: Scanning recursively under {folder}")
    if not os.path.isdir(folder):
        print(f"[!] Folder not found: {folder}")
        return

    files = get_all_textures(folder)
    print(f"[+] {label}: Found {len(files)} texture files")

    mismatches = []
    with ThreadPoolExecutor(max_workers=THREADS) as exe:
        futures = [exe.submit(func, f, csv_data) for f in files]
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                mismatches.append(res)

    mismatches = sorted(set(mismatches), key=lambda x: (os.path.dirname(x).lower(), os.path.basename(x).lower()))
    print(f"[+] {label}: Found {len(mismatches)} mismatches")

    if mismatches:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(mismatches))
        print(f"[+] {label}: Log written to {log_path}")
    else:
        print(f"[+] {label}: All textures matched expected alpha levels.")


# ==========================================================
# MAIN
# ==========================================================
def main():
    print(f"[+] Repo root: {REPO_ROOT}")
    print(f"[+] Loading CSV data from: {CSV_PATH}")
    csv_data = read_csv_alpha_levels(CSV_PATH)
    print(f"[+] Loaded {len(csv_data)} CSV entries")

    run_pass("OPAQUE PASS", OPAQUE_DIR, check_opaque_alpha, csv_data, LOG_OPAQUE)
    run_pass("TRANSPARENT PASS", HAS_ALPHA_DIR, check_transparent_alpha, csv_data, LOG_TRANSP)

    print("[+] Completed both passes.")
    print(f"[+] Launching next stage: {NEXT_SCRIPT}")

    try:
        subprocess.run(["python", NEXT_SCRIPT], check=True)
    except Exception as e:
        print(f"[!] Failed to launch next script: {e}")


if __name__ == "__main__":
    main()
