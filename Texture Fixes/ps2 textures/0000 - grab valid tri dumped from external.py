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

DEST_DIR = os.path.join(REPO_ROOT, "Texture Fixes", "ps2 textures")
FOLLOWUP_SCRIPT = os.path.join(SCRIPT_DIR, "0001 - bring in missing pcsx2 dumped.py")

THREADS = os.cpu_count() or 12
BRANCHES = ["main", "master"]

print_lock = Lock()

# ==========================================================
# UTILITIES
# ==========================================================
def run(cmd, cwd=None, check=True):
    """Run a command with live output."""
    print(f"\n$ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=cwd, check=check)
    except subprocess.CalledProcessError as e:
        print(f"[!] Command failed: {' '.join(cmd)} (exit code {e.returncode})")
        if check:
            sys.exit(e.returncode)


def git_output(cmd, cwd):
    """Return captured stdout from git command."""
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return result.stdout.strip()


def submodule_exists():
    """Check if submodule exists and has valid git metadata (file or folder)."""
    if not os.path.isdir(SUBMODULE_PATH):
        print(f"[!] Submodule folder missing: {SUBMODULE_PATH}")
        return False
    git_ref = os.path.join(SUBMODULE_PATH, ".git")
    if os.path.exists(git_ref):
        return True
    print(f"[!] Submodule folder exists but missing .git reference: {git_ref}")
    return False


def calc_sha1(path):
    """Compute SHA1 hash of a file."""
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
    """Index all .tga files in DEST_DIR by filename -> path + sha1 (multithreaded)."""
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
    """Compare SHA1 and decide to skip, replace, or copy."""
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
    """Recursively copy .tga files from src_dir to dest_dir with SHA1 check (multithreaded)."""
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
# MAIN
# ==========================================================
def main():
    print("=== [ MGS2-PS2-Textures Submodule Updater + Multithreaded Smart TGA Copier ] ===\n")
    print(f"[+] Repo root: {REPO_ROOT}")
    print(f"[+] Submodule: {SUBMODULE_PATH}\n")

    if not os.path.isdir(REPO_ROOT):
        print(f"[!] Repo root not found: {REPO_ROOT}")
        sys.exit(1)

    # --- Step 1: Ensure submodule initialized and updated
    run(["git", "submodule", "init"], cwd=REPO_ROOT)
    run(["git", "submodule", "update", "--recursive", "--remote", "--init"], cwd=REPO_ROOT)

    if not submodule_exists():
        print(f"[!] Submodule directory not properly detected: {SUBMODULE_PATH}")
        sys.exit(1)

    # --- Step 2: Record current commit
    old_commit = git_output(["git", "rev-parse", "HEAD"], cwd=SUBMODULE_PATH)
    print(f"[+] Current submodule commit: {old_commit}")

    # --- Step 3: Update from origin
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

    # --- Step 4: Update nested submodules if any
    print("[+] Updating nested submodules (if any)...")
    run(["git", "submodule", "update", "--recursive", "--remote", "--init"], cwd=SUBMODULE_PATH)

    # --- Step 5: Smart copy stage
    print("\n[+] Building SHA1 index for DEST_DIR...")
    existing_index = scan_dest_tgas(DEST_DIR)

    print("\n[+] Starting multithreaded TGA copy stage...")
    opaque_stats = copy_tga_files(OPAQUE_SRC, DEST_DIR, existing_index)
    half_stats = copy_tga_files(HALF_ALPHA_SRC, DEST_DIR, existing_index)

    total_updated = sum([opaque_stats["copied"], opaque_stats["replaced"], half_stats["copied"], half_stats["replaced"]])

    print(f"\n[+] Smart TGA copy completed. Total new/replaced files: {total_updated}")

    # --- Step 6: Final confirmation
    print("\n[+] Final submodule status:")
    run(["git", "status"], cwd=SUBMODULE_PATH)

    print("\n✅ Submodule fully synced and ps2 textures updated in:")
    print(f"   {DEST_DIR}\n")

    # --- Step 7: Run follow-up script
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
