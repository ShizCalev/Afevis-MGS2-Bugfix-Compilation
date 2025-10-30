import os
import sys
import hashlib
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
HASH_FILE = "original-sha1-hashes.txt"
OUTPUT_LOG = "hash_differences.txt"
IMPORT_SCRIPT_REL = os.path.join("external", "mgs_gcx_editor", "_gcx_import_mgs2.py")
THREADS = 8  # Adjust for CPU cores
DIST_DIR_REL = os.path.join("_dist", "assets", "gcx")

# ==========================================================
# HELPERS
# ==========================================================
print_lock = Lock()

def calc_sha1(path: Path) -> str:
    """Compute SHA1 hash for a file."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_hash_list(file_path: Path) -> list[tuple[str, str]]:
    """Load list of (relative_path, sha1) from text file."""
    entries = []
    if not file_path.exists():
        raise FileNotFoundError(f"Hash list not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "," not in line:
                continue
            rel_path, sha1 = line.split(",", 1)
            entries.append((rel_path.strip(), sha1.strip().lower()))
    return entries


def get_python_cmd() -> str:
    """Return 'py' or 'python' depending on availability."""
    if shutil.which("py"):
        return "py"
    elif shutil.which("python"):
        return "python"
    else:
        sys.exit("Error: Python launcher not found. Ensure 'py' or 'python' is on PATH.")


def import_and_copy_gcx(python_cmd: str, repo_root: Path, script_path: Path, gcx_path: Path, rel_csv_path: str, dist_root: Path) -> tuple[str, int]:
    """Run GCX import and copy the result into _dist/assets/gcx preserving structure relative to the CSV path."""
    result = subprocess.run([python_cmd, str(script_path), str(gcx_path)], text=True)
    code = result.returncode

    if code == 0:
        # Compute the relative path from CSV entry, not from repo
        rel_gcx_path = Path(rel_csv_path).with_suffix(".gcx")
        dest_path = dist_root / rel_gcx_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(gcx_path, dest_path)
            with print_lock:
                print(f"    Copied -> {dest_path.relative_to(repo_root)}")
        except Exception as e:
            with print_lock:
                print(f"    [COPY FAILED] {gcx_path} -> {e}")
            code = 2

    return (rel_csv_path, code)


# ==========================================================
# MAIN
# ==========================================================
def main():
    cwd = Path.cwd()

    # Try to find repo root via git
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        repo_root = Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        repo_root = cwd

    script_path = repo_root / IMPORT_SCRIPT_REL
    dist_root = repo_root / DIST_DIR_REL

    if not script_path.exists():
        sys.exit(f"Error: Import script not found at {script_path}")

    hash_file = cwd / HASH_FILE
    output_log = cwd / OUTPUT_LOG
    entries = load_hash_list(hash_file)

    python_cmd = get_python_cmd()
    differences = []
    import_targets = []

    print(f"Verifying {len(entries)} CSV hashes...\n")

    # Step 1: Check hashes and queue changed CSVs
    for rel_path, old_sha1 in entries:
        csv_path = cwd / rel_path
        if not csv_path.exists():
            with print_lock:
                print(f"[MISSING] {rel_path}")
            continue

        new_sha1 = calc_sha1(csv_path)
        if new_sha1 != old_sha1:
            differences.append((rel_path, old_sha1, new_sha1))
            with print_lock:
                print(f"[CHANGED] {rel_path}")
            gcx_path = csv_path.with_suffix(".gcx")
            if gcx_path.exists():
                import_targets.append((gcx_path, rel_path))
            else:
                with print_lock:
                    print(f"    [MISSING GCX] {gcx_path}")

    # Step 2: Run GCX imports + copy concurrently
    if import_targets:
        print(f"\nStarting GCX imports for {len(import_targets)} changed file(s)...\n")

        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = {
                executor.submit(import_and_copy_gcx, python_cmd, repo_root, script_path, gcx_path, rel_path, dist_root): rel_path
                for gcx_path, rel_path in import_targets
            }

            for i, future in enumerate(as_completed(futures), 1):
                rel_path = futures[future]
                try:
                    rel, code = future.result()
                    color = "\033[92m" if code == 0 else "\033[91m"
                    reset = "\033[0m"
                    with print_lock:
                        print(f"[{i}/{len(import_targets)}] {rel} -> {color}{'OK' if code == 0 else f'FAILED ({code})'}{reset}")
                except Exception as e:
                    with print_lock:
                        print(f"[{i}/{len(import_targets)}] {rel_path} -> \033[91mERROR: {e}\033[0m")

    # Step 3: Write log
    with open(output_log, "w", encoding="utf-8") as f:
        if differences:
            f.write("=== Files with Different SHA1 Hashes ===\n\n")
            for rel_path, old, new in differences:
                f.write(f"{rel_path}\n    OLD: {old}\n    NEW: {new}\n\n")
        else:
            f.write("All hashes match. No differences found.\n")

    if differences:
        print(f"\n{len(differences)} file(s) changed. Logged to: {output_log}")
    else:
        print("\nAll hashes match.")


if __name__ == "__main__":
    main()
