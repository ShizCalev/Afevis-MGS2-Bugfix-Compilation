import os
import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import subprocess
import sys

# ==========================================================
# CONFIGURATION
# ==========================================================
# Resolve repo root dynamically from script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Directories relative to repo root
TGA_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
PNG_DIR = os.path.join(REPO_ROOT, "external", "MGS2-PS2-Textures", "final_verification_nov22_2025")
LOG_PATH = os.path.join(SCRIPT_DIR, "non_matching_pngs.txt")
NEXT_SCRIPT = os.path.join(SCRIPT_DIR, "0002 - sort alpha.py")

OUTPUT_LOCK = threading.Lock()

# ==========================================================
# HELPERS
# ==========================================================
def calc_sha1(path):
    """Compute SHA1 hash for a file."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_index(root_dir):
    """Recursively index all files by base filename (without extension)."""
    index = {}
    for root, _, files in os.walk(root_dir):
        for f in files:
            name, ext = os.path.splitext(f)
            if ext.lower() in [".tga", ".png"]:
                index.setdefault(name.lower(), []).append(os.path.join(root, f))
    return index


def process_png(png_path, tga_index):
    """Process one PNG file."""
    name = os.path.splitext(os.path.basename(png_path))[0].lower()

    # Case 1: TGA match — skip entirely
    if name in tga_index:
        for existing_path in tga_index[name]:
            if existing_path.lower().endswith(".tga"):
                return None  # Skip - TGA takes precedence

    # Case 2: PNG match — compare hashes
    if name in tga_index:
        for existing_path in tga_index[name]:
            if existing_path.lower().endswith(".png"):
                current_hash = calc_sha1(png_path)
                existing_hash = calc_sha1(existing_path)
                if current_hash != existing_hash:
                    with OUTPUT_LOCK:
                        with open(LOG_PATH, "a", encoding="utf-8") as log:
                            rel_path = os.path.relpath(png_path, REPO_ROOT)
                            log.write(f"{rel_path}\n")
                        print(f"[MISMATCH] {name}.png (press Enter to continue)")
                    input()
                return None  # Handled regardless of match/mismatch

    # Case 3: No match at all — copy file
    dest_path = os.path.join(TGA_DIR, os.path.basename(png_path))
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(png_path, dest_path)
    with OUTPUT_LOCK:
        print(f"[COPIED] {os.path.basename(png_path)}")
    return None


# ==========================================================
# MAIN
# ==========================================================
def main():
    print(f"[+] Repo root: {REPO_ROOT}")
    print("[+] Indexing TGA_DIR recursively...")
    tga_index = build_index(TGA_DIR)
    print(f"[+] Indexed {len(tga_index)} unique filenames.")

    print("[+] Scanning PNG_DIR recursively...")
    png_files = []
    for root, _, files in os.walk(PNG_DIR):
        for f in files:
            if f.lower().endswith(".png"):
                png_files.append(os.path.join(root, f))

    print(f"[+] Found {len(png_files)} PNGs to process.\n")

    # Clear log file before writing
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)

    # Process in parallel
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = [executor.submit(process_png, f, tga_index) for f in png_files]
        for _ in as_completed(futures):
            pass

    print("\n[+] Done.")
    print(f"[+] Non-matching PNGs logged to: {LOG_PATH}")
    
        # ==========================================================
    # CLEANUP: Remove PNGs in TGA_DIR that do NOT exist in PNG_DIR
    # ==========================================================
    print("[+] Cleaning up orphan PNGs in TGA_DIR...")

    # Build a set of valid PNG basenames from PNG_DIR
    valid_png_names = set()
    for root, _, files in os.walk(PNG_DIR):
        for f in files:
            if f.lower().endswith(".png"):
                name = os.path.splitext(f)[0].lower()
                valid_png_names.add(name)

    removed_count = 0

    for root, _, files in os.walk(TGA_DIR):
        for f in files:
            if not f.lower().endswith(".png"):
                continue

            name = os.path.splitext(f)[0].lower()
            full_path = os.path.join(root, f)

            if name not in valid_png_names:
                try:
                    os.remove(full_path)
                    removed_count += 1
                    print(f"[REMOVED ORPHAN] {full_path}")
                except Exception as e:
                    print(f"[ERROR] Failed to remove {full_path}: {e}")

    print(f"[+] Removed {removed_count} orphan PNG(s).\n")


    # --- Run the next script ---
    print("\n[+] Launching next stage: 0002 - sort alpha.py")
    if os.path.exists(NEXT_SCRIPT):
        try:
            subprocess.run([sys.executable, NEXT_SCRIPT], check=True)
            print(f"[+] Successfully completed next stage: {os.path.basename(NEXT_SCRIPT)}")
        except subprocess.CalledProcessError as e:
            print(f"[!] Next script failed with exit code {e.returncode}")
        except Exception as e:
            print(f"[!] Error while running next script: {e}")
    else:
        print(f"[!] Next script not found: {NEXT_SCRIPT}")

    print("\nFile verification complete, and alpha sorting has been triggered.\n")


if __name__ == "__main__":
    main()
