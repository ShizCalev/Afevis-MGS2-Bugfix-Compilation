import os
import csv
import hashlib
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from tqdm import tqdm

# ==========================================================
# CONFIG
# ==========================================================
MAX_WORKERS = max(4, os.cpu_count() or 4)

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

def pil_resave(path: Path) -> str:
    with Image.open(path) as img:
        img.save(path, format="PNG", optimize=False)
    return sha1_of_file(path)

def alpha_strip_if_needed(path: Path, from_opaque: bool) -> str:
    if not from_opaque:
        return sha1_of_file(path)

    with Image.open(path) as img:
        if img.mode in ("RGBA", "LA"):
            rgb = img.convert("RGB")
            rgb.save(path, format="PNG")

    return sha1_of_file(path)

def process_texture_pair(name: str,
                         src_png: Path,
                         src_ctxr: Path,
                         win_dir: Path,
                         opaque_dir: Path):

    # Original hashes
    png_sha1 = sha1_of_file(src_png)
    ctxr_sha1 = sha1_of_file(src_ctxr)

    # Copy to _win with lowercase filename
    lower_name = src_png.name.lower()
    dst_path = win_dir / lower_name

    if dst_path.exists():
        dst_path.unlink()

    shutil.copy2(src_png, dst_path)

    # PIL resave
    pil_sha1 = pil_resave(dst_path)

    # Determine if from /opaque
    from_opaque = opaque_dir in src_png.parents

    # Alpha strip if needed
    adjusted_sha1 = alpha_strip_if_needed(dst_path, from_opaque)

    return (name, png_sha1, ctxr_sha1, pil_sha1, adjusted_sha1)

# ==========================================================
# MAIN
# ==========================================================
def main():
    gitroot = get_git_root()
    source_dir = gitroot / "Texture Fixes" / "mc textures"
    staging_dir = gitroot / "Texture Fixes" / "Staging"
    win_dir = staging_dir / "_win"
    opaque_dir = source_dir / "opaque"

    if not source_dir.exists():
        raise RuntimeError(f"Source directory does not exist: {source_dir}")

    # Collect files
    files = scan_paths(source_dir)

    pngs = {}
    ctxrs = {}

    for f in files:
        ext = f.suffix.lower()
        if ext == ".png":
            pngs[f.stem] = f
        elif ext == ".ctxr":
            ctxrs[f.stem] = f

    # Mismatch detection
    missing_ctxr = [p for stem, p in pngs.items() if stem not in ctxrs]
    missing_png = [p for stem, p in ctxrs.items() if stem not in pngs]

    # Log mismatches
    log_path = gitroot / "mc_texture_mismatch_log.txt"
    with open(log_path, "w", encoding="utf8") as log:
        if missing_ctxr:
            log.write("PNG missing CTXR:\n")
            for p in missing_ctxr:
                log.write(f"{p}\n")
            log.write("\n")
        if missing_png:
            log.write("CTXR missing PNG:\n")
            for p in missing_png:
                log.write(f"{p}\n")
            log.write("\n")

    mismatch_count = len(missing_ctxr) + len(missing_png)

    if mismatch_count > 0:
        print(f"Mismatches found: {mismatch_count}")
        print(f"See log at: {log_path}")
        input("Press Enter to exit...")
        return

    print("Pairs match. Starting multithreaded pipeline...")

    staging_dir.mkdir(parents=True, exist_ok=True)
    win_dir.mkdir(parents=True, exist_ok=True)


    # Delete ALL contents of _win but keep the folder itself
    for item in win_dir.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


    names = sorted(pngs.keys())
    results = []

    # ==========================================================
    # MULTITHREADED PROCESSING WITH PROGRESS BAR + ETA
    # ==========================================================
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_name = {
            executor.submit(
                process_texture_pair,
                name,
                pngs[name],
                ctxrs[name],
                win_dir,
                opaque_dir
            ): name
            for name in names
        }

        for future in tqdm(as_completed(future_to_name),
                           total=len(future_to_name),
                           unit="file",
                           desc="Processing",
                           smoothing=0.1):
            results.append(future.result())

    results.sort(key=lambda r: r[0])

    # ==========================================================
    # WRITE CSV
    # ==========================================================
    csv_path = staging_dir / "mc_textures.csv"

    with open(csv_path, "w", newline="", encoding="utf8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "name",
            "png_sha1",
            "ctxr_sha1",
            "pil_png_sha1",
            "mc_alpha_adjusted_sha1",
        ])

        for row in results:
            writer.writerow(row)

    print(f"\nComplete: {len(results)} processed.")
    print(f"CSV: {csv_path}")
    print(f"Lowercased PNGs: {win_dir}")

if __name__ == "__main__":
    main()
