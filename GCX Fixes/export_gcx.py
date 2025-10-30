import os
import subprocess
import sys
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ==========================================================
# CONFIGURATION
# ==========================================================
THREADS = 8  # Adjust based on CPU cores
SCRIPT_REL_PATH = os.path.join("external", "mgs_gcx_editor", "_gcx_export_mgs2.py")
DUMP_HASH_SCRIPT = "dump_csv_hashes.py"  # script to call after successful exports

# ==========================================================
# HELPERS
# ==========================================================
print_lock = Lock()


def find_repo_root() -> Path:
    """Use git to determine the repo root."""
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        sys.exit("Error: Failed to determine git repository root. Are you inside a git repo?")


def get_python_cmd() -> str:
    """Return 'py' or 'python' depending on availability."""
    if shutil.which("py"):
        return "py"
    elif shutil.which("python"):
        return "python"
    else:
        sys.exit("Error: Python launcher not found. Ensure 'py' or 'python' is on PATH.")


def find_gcx_files(root: Path):
    """Recursively yield all .gcx files."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".gcx"):
                yield Path(dirpath) / name


def export_gcx(python_cmd: str, script_path: Path, gcx_path: Path) -> tuple[Path, int]:
    """Run the GCX export command for a single file."""
    process = subprocess.run([python_cmd, str(script_path), str(gcx_path)], capture_output=True, text=True)
    return (gcx_path, process.returncode, process.stdout.strip(), process.stderr.strip())


def run_dump_csv_hashes(python_cmd: str, cwd: Path):
    """Run dump_csv_hashes.py after successful exports."""
    hash_script = cwd / DUMP_HASH_SCRIPT
    if not hash_script.exists():
        print(f"\n[!] Warning: {hash_script} not found, skipping hash dump.")
        return

    print(f"\nRunning post-export hash dump: {hash_script}\n")
    process = subprocess.run([python_cmd, str(hash_script)], text=True)
    if process.returncode == 0:
        print("\033[92mHash dump completed successfully.\033[0m")
    else:
        print(f"\033[91mHash dump failed with exit code {process.returncode}.\033[0m")


# ==========================================================
# MAIN
# ==========================================================
def main():
    cwd = Path.cwd()
    repo_root = find_repo_root()
    script_path = repo_root / SCRIPT_REL_PATH

    if not script_path.exists():
        sys.exit(f"Error: Could not find editor script at: {script_path}")

    gcx_files = list(find_gcx_files(cwd))
    total = len(gcx_files)
    if total == 0:
        print(f"No .gcx files found in {cwd}.")
        return

    print(f"Found {total} .gcx files. Starting exports...\n")

    python_cmd = get_python_cmd()
    fail_count = 0

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = {executor.submit(export_gcx, python_cmd, script_path, path): path for path in gcx_files}

        for i, future in enumerate(as_completed(futures), 1):
            gcx_path = futures[future]
            rel_path = gcx_path.relative_to(cwd)
            try:
                path, code, stdout, stderr = future.result()
                with print_lock:
                    status = "OK" if code == 0 else f"FAILED ({code})"
                    color = "\033[92m" if code == 0 else "\033[91m"
                    reset = "\033[0m"
                    print(f"[{i}/{total}] {rel_path} -> {color}{status}{reset}")
                    if code != 0:
                        fail_count += 1
                        if stderr:
                            print(stderr.strip())
            except Exception as e:
                with print_lock:
                    print(f"[{i}/{total}] {rel_path} -> \033[91mERROR: {e}\033[0m")
                fail_count += 1

    print("\n" + ("=" * 60))
    if fail_count:
        print(f"\033[91m{fail_count} of {total} exports failed.\033[0m")
        sys.exit(1)
    else:
        print(f"\033[92mAll {total} exports succeeded.\033[0m")

    # ======================================================
    # Run post-export hash dump
    # ======================================================
    run_dump_csv_hashes(python_cmd, cwd)


if __name__ == "__main__":
    main()
