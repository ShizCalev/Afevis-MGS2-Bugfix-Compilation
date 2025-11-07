import os
import shutil
import subprocess
import sys
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

SUBMODULE_PATH = os.path.join(REPO_ROOT, "external", "MGS2-PS2-Textures")
FINAL_REBUILT_ROOT = os.path.join(SUBMODULE_PATH, "u - dumped from substance", "dump", "Final Rebuilt")
OPAQUE_SRC = os.path.join(FINAL_REBUILT_ROOT, "opaque")
HALF_ALPHA_SRC = os.path.join(FINAL_REBUILT_ROOT, "half_alpha")
GOOD_ALPHA_SRC = os.path.join(FINAL_REBUILT_ROOT, "good_alpha")
MIXED_ALPHA_SRC = os.path.join(FINAL_REBUILT_ROOT, "mixed_alpha")

DEST_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
TRI_WITH_ALPHA_DIR = os.path.join(DEST_DIR, "tri with alpha")

FINAL_VERIFICATION_DIR = os.path.join(SUBMODULE_PATH, "final_verification_nov22_2025")
FOLLOWUP_SCRIPT = os.path.join(SCRIPT_DIR, "0001 - bring in missing pcsx2 dumped.py")

THREADS = os.cpu_count() or 12
BRANCHES = ["main", "master"]

print_lock = Lock()

# ==========================================================
# UTILITIES
# ==========================================================
def run(cmd, cwd=None, check=True):
    print(f"\n$ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=cwd, check=check)
    except subprocess.CalledProcessError as e:
        print(f"[!] Command failed: {' '.join(cmd)} (exit code {e.returncode})")
        if check:
            sys.exit(e.returncode)


def git_output(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return result.stdout.strip()


def submodule_exists():
    if not os.path.isdir(SUBMODULE_PATH):
        print(f"[!] Submodule folder missing: {SUBMODULE_PATH}")
        return False
    git_ref = os.path.join(SUBMODULE_PATH, ".git")
    if os.path.exists(git_ref):
        return True
    print(f"[!] Submodule folder exists but missing .git reference: {git_ref}")
    return False


def calc_sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ==========================================================
# DESTINATION INDEX
# ==========================================================
def scan_file_for_index(path):
    try:
        sha1 = calc_sha1(path)
        return os.path.basename(path).lower(), {"path": path, "sha1": sha1}
    except Exception as e:
        with print_lock:
            print(f"[!] Failed to hash {path}: {e}")
        return None


def scan_dest_tgas(dest_dir):
    print(f"[+] Indexing .tga files in DEST_DIR: {dest_dir}")
    paths = []
    for root, _, files in os.walk(dest_dir):
        for f in files:
            if f.lower().endswith(".tga"):
                paths.append(os.path.join(root, f))

    index = {}
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(scan_file_for_index, p) for p in paths]
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                key, data = res
                index[key] = data

    print(f"[+] Indexed {len(index)} existing .tga files in DEST_DIR")
    return index


# ==========================================================
# SMART COPY LOGIC
# ==========================================================
def handle_tga_file(src_path, dest_dir, existing_index):
    filename = os.path.basename(src_path).lower()
    try:
        src_hash = calc_sha1(src_path)
    except Exception as e:
        with print_lock:
            print(f"[!] Hash failed for {src_path}: {e}")
        return "error"

    dest_path = os.path.join(dest_dir, filename)

    if filename in existing_index:
        existing = existing_index[filename]
        if existing["sha1"] == src_hash:
            return "skipped"
        try:
            os.remove(existing["path"])
            shutil.copy2(src_path, dest_path)
            existing_index[filename] = {"path": dest_path, "sha1": src_hash}
            with print_lock:
                print(f"[Replaced] {filename}")
            return "replaced"
        except Exception as e:
            with print_lock:
                print(f"[Error replacing] {filename}: {e}")
            return "error"
    else:
        try:
            shutil.copy2(src_path, dest_path)
            existing_index[filename] = {"path": dest_path, "sha1": src_hash}
            with print_lock:
                print(f"[Copied] {filename}")
            return "copied"
        except Exception as e:
            with print_lock:
                print(f"[Error copying] {filename}: {e}")
            return "error"


def copy_tga_files(src_dir, dest_dir, existing_index):
    if not os.path.isdir(src_dir):
        print(f"[!] Source not found: {src_dir}")
        return {"copied": 0, "replaced": 0, "skipped": 0, "error": 0}

    all_tgas = []
    for root, _, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith(".tga"):
                all_tgas.append(os.path.join(root, f))

    stats = {"copied": 0, "replaced": 0, "skipped": 0, "error": 0}

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(handle_tga_file, path, dest_dir, existing_index) for path in all_tgas]
        for fut in as_completed(futures):
            res = fut.result()
            if res in stats:
                stats[res] += 1

    print(f"[+] {os.path.basename(src_dir)}: {stats['copied']} copied, {stats['replaced']} replaced, {stats['skipped']} skipped, {stats['error']} errors")
    return stats


# ==========================================================
# FINAL VERIFICATION FILTER
# ==========================================================
def get_final_verification_names():
    """Return set of PNG base filenames (no extension) from FINAL_VERIFICATION_DIR."""
    names = set()
    if not os.path.isdir(FINAL_VERIFICATION_DIR):
        print(f"[!] Final verification directory missing: {FINAL_VERIFICATION_DIR}")
        return names

    for root, _, files in os.walk(FINAL_VERIFICATION_DIR):
        for f in files:
            if f.lower().endswith(".png"):
                names.add(os.path.splitext(f)[0].lower())
    print(f"[+] Loaded {len(names)} entries from final verification folder.")
    return names


def sync_tri_with_alpha(dest_dir, verification_names):
    """Remove existing TGAs that are in final verification; keep only new ones."""
    if not os.path.isdir(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    removed = 0
    for root, _, files in os.walk(dest_dir):
        for f in files:
            if f.lower().endswith(".tga") and os.path.splitext(f)[0].lower() in verification_names:
                path = os.path.join(root, f)
                try:
                    os.remove(path)
                    removed += 1
                    print(f"[Removed existing verified] {f}")
                except Exception as e:
                    print(f"[!] Failed to remove {path}: {e}")
    print(f"[+] Removed {removed} verified files from tri with alpha.")
    return removed


from PIL import Image

def has_alpha_above_128(path):
    """Return True if the image has any alpha > 128."""
    try:
        with Image.open(path) as im:
            if im.mode not in ("RGBA", "LA"):
                return False
            alpha = im.getchannel("A")
            extrema = alpha.getextrema()  # (min, max)
            return extrema[1] > 128
    except Exception as e:
        with print_lock:
            print(f"[!] Alpha check failed for {path}: {e}")
        return False


def copy_unverified_tgas(src_dir, dest_dir, verification_names):
    """Copy only TGA files not present in final verification and not over-alpha (max alpha > 128)."""
    copied = 0
    skipped = 0
    alpha_skipped = 0

    for root, _, files in os.walk(src_dir):
        for f in files:
            if not f.lower().endswith(".tga"):
                continue

            name_no_ext = os.path.splitext(f)[0].lower()
            src = os.path.join(root, f)

            if name_no_ext in verification_names:
                skipped += 1
                continue

            # Skip if alpha > 128
            if has_alpha_above_128(src):
                alpha_skipped += 1
                with print_lock:
                    print(f"[Skipped – alpha >128] {f}")
                continue

            dest = os.path.join(dest_dir, f)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            try:
                shutil.copy2(src, dest)
                copied += 1
                with print_lock:
                    print(f"[Copied to tri with alpha] {f}")
            except Exception as e:
                with print_lock:
                    print(f"[!] Failed to copy {src}: {e}")

    print(f"[+] {os.path.basename(src_dir)}: {copied} copied, {skipped} skipped (verified), {alpha_skipped} skipped (alpha >128).")
    return copied, skipped, alpha_skipped



# ==========================================================
# MAIN
# ==========================================================
def main():
    print("=== [ MGS2-PS2-Textures Submodule Updater + Smart Alpha Manager ] ===\n")
    print(f"[+] Repo root: {REPO_ROOT}")
    print(f"[+] Submodule: {SUBMODULE_PATH}\n")

    if not os.path.isdir(REPO_ROOT):
        print(f"[!] Repo root not found: {REPO_ROOT}")
        sys.exit(1)

    run(["git", "submodule", "init"], cwd=REPO_ROOT)
    run(["git", "submodule", "update", "--recursive", "--remote", "--init"], cwd=REPO_ROOT)

    if not submodule_exists():
        print(f"[!] Submodule directory not properly detected: {SUBMODULE_PATH}")
        sys.exit(1)

    old_commit = git_output(["git", "rev-parse", "HEAD"], cwd=SUBMODULE_PATH)
    print(f"[+] Current submodule commit: {old_commit}")

    print("\n[+] Fetching latest commits for submodule...")
    run(["git", "fetch", "origin"], cwd=SUBMODULE_PATH)

    checked_out = False
    for branch in BRANCHES:
        result = subprocess.run(["git", "rev-parse", "--verify", branch],
                                cwd=SUBMODULE_PATH, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            print(f"[+] Checking out branch: {branch}")
            run(["git", "checkout", branch], cwd=SUBMODULE_PATH)
            run(["git", "pull", "origin", branch], cwd=SUBMODULE_PATH)
            checked_out = True
            break

    if not checked_out:
        print("[!] No main/master branch found — staying on current HEAD.")

    print("[+] Updating nested submodules (if any)...")
    run(["git", "submodule", "update", "--recursive", "--remote", "--init"], cwd=SUBMODULE_PATH)

    print("\n[+] Building SHA1 index for DEST_DIR...")
    existing_index = scan_dest_tgas(DEST_DIR)

    print("\n[+] Copying from standard sources...")
    opaque_stats = copy_tga_files(OPAQUE_SRC, DEST_DIR, existing_index)
    half_stats = copy_tga_files(HALF_ALPHA_SRC, DEST_DIR, existing_index)

    total_updated = sum([
        opaque_stats["copied"], opaque_stats["replaced"],
        half_stats["copied"], half_stats["replaced"]
    ])


    print(f"\n[+] Smart TGA copy completed. Total new/replaced files: {total_updated}")

    # --- Handle tri with alpha sync
    print("\n[+] Syncing tri with alpha folder...")
    verification_names = get_final_verification_names()
    sync_tri_with_alpha(TRI_WITH_ALPHA_DIR, verification_names)

    print("[+] Copying new unverified TGAs to tri with alpha...")
    copy_unverified_tgas(GOOD_ALPHA_SRC, TRI_WITH_ALPHA_DIR, verification_names)
    copy_unverified_tgas(MIXED_ALPHA_SRC, TRI_WITH_ALPHA_DIR, verification_names)

    print("\n[+] Final submodule status:")
    run(["git", "status"], cwd=SUBMODULE_PATH)

    print("\n✅ Submodule fully synced and ps2 textures updated in:")
    print(f"   {DEST_DIR}\n")

    print(f"[+] Running follow-up script: {FOLLOWUP_SCRIPT}")
    if os.path.exists(FOLLOWUP_SCRIPT):
        try:
            subprocess.run([sys.executable, FOLLOWUP_SCRIPT], check=True)
        except subprocess.CalledProcessError as e:
            print(f"[!] Follow-up script failed with exit code {e.returncode}")
        except Exception as e:
            print(f"[!] Error launching follow-up script: {e}")
    else:
        print(f"[!] Follow-up script not found: {FOLLOWUP_SCRIPT}")


if __name__ == "__main__":
    main()
