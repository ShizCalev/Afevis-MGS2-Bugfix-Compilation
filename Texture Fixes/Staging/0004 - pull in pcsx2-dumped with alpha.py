import os
import csv
import subprocess
import hashlib
from pathlib import Path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

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

def list_pngs(folder: Path):
    """List PNG files (NOT recursive)."""
    if not folder.exists():
        return []
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".png"]

def pil_resave(path: Path):
    """Open → resave PNG deterministically."""
    with Image.open(path) as img:
        img.save(path, format="PNG", optimize=False)

def copy_and_resave(src: Path, win_dir: Path):
    """
    Copy PNG → _win using lowercase filename.
    Skip if output already exists.
    PIL-resave after copy.
    Returns CSV row: (name, source_sha1, png_sha1)
    """
    out_name = src.name.lower()
    dst = win_dir / out_name

    # Skip overwrite
    if dst.exists():
        return None

    # original file hash
    source_sha = sha1_of_file(src)

    # Copy
    dst.write_bytes(src.read_bytes())

    # PIL resave for deterministic hash
    pil_resave(dst)

    # final hash
    png_sha = sha1_of_file(dst)

    return (src.stem, source_sha, png_sha)

# ==========================================================
# MAIN
# ==========================================================
def main():
    gitroot = get_git_root()

    base = gitroot / "Texture Fixes" / "ps2 textures" / "HAS ALPHA"

    folders = [
        base,
        base / "no_mip_fixes",
        base / "power of two" / "no_mip_fixes",
    ]

    staging_dir = gitroot / "Texture Fixes" / "Staging"
    win_dir = staging_dir / "_win"

    if not win_dir.exists():
        raise RuntimeError("_win folder missing — run your MC pipeline first.")

    # Gather non-recursive PNGs
    png_files = []
    for folder in folders:
        png_files.extend(list_pngs(folder))

    print(f"Found {len(png_files)} PNG files in HAS ALPHA folders.")

    results = []

    # ==========================================================
    # MULTITHREADED COPY + RESAVE
    # ==========================================================
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {
            exe.submit(copy_and_resave, src, win_dir): src
            for src in png_files
        }

        for fut in tqdm(
            as_completed(futures),
            total=len(futures),
            unit="file",
            desc="Copying HAS ALPHA PNGs",
            smoothing=0.1,
        ):
            row = fut.result()
            if row is not None:
                results.append(row)

    print(f"\nCopied and resaved {len(results)} PNGs into _win (skipped existing).")

    # ==========================================================
    # WRITE CSV (alphabetically sorted)
    # ==========================================================
    csv_path = staging_dir / "pcxs2_dumped_with_alpha.csv"

    results.sort(key=lambda r: r[0].lower())

    with open(csv_path, "w", newline="", encoding="utf8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "source_sha1", "png_sha1"])
        for row in results:
            writer.writerow(row)

    print(f"CSV written: {csv_path}")
    print(f"Output PNGs in: {win_dir}")

if __name__ == "__main__":
    main()
