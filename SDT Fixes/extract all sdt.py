import subprocess
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================================
# CONFIGURATION
# ==========================================================
SCRIPT = Path("0000.SDT_extractor.py")  # Path to your extractor script
THREADS = os.cpu_count() or 8  # Auto-detect threads
DEST_ROOT = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\SDT Fixes\jp installed")

# ==========================================================
# MAIN LOGIC
# ==========================================================
def process_file(sdt_path: Path, repo_root: Path):
    rel_path = sdt_path.relative_to(repo_root)
    csv_path = DEST_ROOT / rel_path.with_suffix(".csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["python", str(SCRIPT), str(sdt_path), str(csv_path)],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return f"[OK] {rel_path}"
        else:
            return f"[ERR] {rel_path}\n{result.stderr.strip()}"
    except Exception as e:
        return f"[FAIL] {rel_path}: {e}"

def main():
    repo_root = Path.cwd()
    sdt_files = list(repo_root.rglob("*.sdt"))

    if not sdt_files:
        print("No .sdt files found recursively under current directory.")
        return

    print(f"Found {len(sdt_files)} .sdt files. Processing with {THREADS} threads...\n")

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = {executor.submit(process_file, f, repo_root): f for f in sdt_files}
        for fut in as_completed(futures):
            print(fut.result())

    print("\nAll tasks complete.")

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    main()
