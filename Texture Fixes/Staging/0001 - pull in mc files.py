import os
import csv
import hashlib
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ==========================================================
# HELPERS
# ==========================================================
def get_git_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL
        )
        return Path(out.decode().strip())
    except Exception as e:
        raise RuntimeError(f"Failed to determine git repo root: {e}")

def scan_paths(base: Path):
    return [p for p in base.rglob("*") if p.is_file()]

def sha1_of_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

# ==========================================================
# MAIN
# ==========================================================
def main():
    gitroot = get_git_root()
    source_dir = gitroot / "Texture Fixes" / "mc textures"
    staging_dir = gitroot / "Texture Fixes" / "Staging"
    win_dir = staging_dir / "_win"

    if not source_dir.exists():
        raise RuntimeError(f"Source directory does not exist: {source_dir}")

    # Gather all files
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as exe:
        files = exe.submit(scan_paths, source_dir).result()

    pngs = {}
    ctxrs = {}

    for f in files:
        ext = f.suffix.lower()
        if ext == ".png":
            pngs[f.stem] = f
        elif ext == ".ctxr":
            ctxrs[f.stem] = f

    # Detect mismatches
    missing_ctxr = [p for stem, p in pngs.items() if stem not in ctxrs]
    missing_png = [p for stem, p in ctxrs.items() if stem not in pngs]

    # Log mismatches
    log_path = gitroot / "mc_texture_mismatch_log.txt"
    with open(log_path, "w", encoding="utf8") as log:
        if missing_ctxr:
            log.write("PNG files missing matching .ctxr:\n")
            for p in missing_ctxr:
                log.write(f"{p}\n")
            log.write("\n")

        if missing_png:
            log.write("CTXR files missing matching .png:\n")
            for p in missing_png:
                log.write(f"{p}\n")
            log.write("\n")

    mismatch_count = len(missing_ctxr) + len(missing_png)

    if mismatch_count > 0:
        print(f"Mismatches found: {mismatch_count}")
        print(f"See log: {log_path}")
        input("Press Enter to exit...")
        return

    print("All PNG/CTXR pairs match. Proceeding with staging + CSV export.")

    staging_dir.mkdir(parents=True, exist_ok=True)
    win_dir.mkdir(parents=True, exist_ok=True)

    # ==========================================================
    # COPY ONLY PNG FILES TO STAGING/_win
    # ==========================================================
    copied_pngs = []

    for f in pngs.values():
        dst = win_dir / f.name
        shutil.copy2(f, dst)
        copied_pngs.append(dst)

    # ==========================================================
    # WRITE CSV WITH name, sha1(png), sha1(ctxr)
    # (CSV stays in Staging)
    # ==========================================================
    csv_path = staging_dir / "mc_textures.csv"

    with open(csv_path, "w", newline="", encoding="utf8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["name", "png_sha1", "ctxr_sha1"])

        for name in sorted(pngs.keys()):
            png_path = pngs[name]
            ctxr_path = ctxrs[name]

            png_sha = sha1_of_file(png_path)
            ctxr_sha = sha1_of_file(ctxr_path)

            writer.writerow([name, png_sha, ctxr_sha])

    print(f"Copied {len(copied_pngs)} PNG files into {win_dir}")
    print(f"CSV written: {csv_path}")

if __name__ == "__main__":
    main()
