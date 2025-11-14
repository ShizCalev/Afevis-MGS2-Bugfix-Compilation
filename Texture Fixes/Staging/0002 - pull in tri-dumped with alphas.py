import os
import csv
import subprocess
from pathlib import Path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import hashlib

# ==========================================================
# CONFIG
# ==========================================================
MAX_WORKERS = max(4, os.cpu_count() or 4)

# ==========================================================
# HELPERS
# ==========================================================
def get_git_root() -> Path:
    out = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        stderr=subprocess.DEVNULL
    )
    return Path(out.decode().strip())

def sha1_of_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def list_direct_tga(folder: Path):
    """Return *.tga in folder (NOT recursive)."""
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".tga"]

def convert_tga_to_png(src: Path, win_dir: Path):
    """
    Convert .tga -> .png (lowercase filename),
    skip if output already exists.
    Returns tuple for CSV or None if skipped:
    (name, source_sha1, png_sha1)
    """
    out_name = (src.stem + ".png").lower()
    dst_path = win_dir / out_name

    # Skip if already exists
    if dst_path.exists():
        return None

    # SHA1 of source TGA
    source_sha = sha1_of_file(src)

    # Convert
    with Image.open(src) as img:
        img.save(dst_path, format="PNG", optimize=False)

    # SHA1 of resulting PNG
    png_sha = sha1_of_file(dst_path)

    return (src.stem, source_sha, png_sha)

# ==========================================================
# MAIN
# ==========================================================
def main():
    gitroot = get_git_root()

    root_a = gitroot / "Texture Fixes" / "ps2 textures" / "tri with alpha"
    root_b = root_a / "no_mip_fixes"
    staging_dir = gitroot / "Texture Fixes" / "Staging"
    win_dir = staging_dir / "_win"

    if not win_dir.exists():
        raise RuntimeError("_win does not exist. Run the MC PNG pipeline first.")

    # Collect TGAs from EXACT folders only
    tga_files = []
    if root_a.exists():
        tga_files.extend(list_direct_tga(root_a))
    if root_b.exists():
        tga_files.extend(list_direct_tga(root_b))

    print(f"Found {len(tga_files)} TGA files (non-recursive).")

    results = []

    # ==========================================================
    # MULTITHREADED CONVERSION
    # ==========================================================
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(convert_tga_to_png, tga, win_dir): tga
            for tga in tga_files
        }

        for future in tqdm(
            as_completed(future_map),
            total=len(future_map),
            unit="file",
            desc="Converting TGAs",
            smoothing=0.1
        ):
            row = future.result()
            if row is not None:
                results.append(row)

    print(f"\nConverted {len(results)} new PNGs (skipped existing).")

    # ==========================================================
    # WRITE CSV
    # ==========================================================
    csv_path = staging_dir / "tri_with_alpha.csv"

    # sort results by texture name
    results.sort(key=lambda r: r[0].lower())

    with open(csv_path, "w", newline="", encoding="utf8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "source_sha1", "png_sha1"])
        for row in results:
            writer.writerow(row)


    print(f"CSV written: {csv_path}")
    print(f"Output PNGs: {win_dir}")

if __name__ == "__main__":
    main()
