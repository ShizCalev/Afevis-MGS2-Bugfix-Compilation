from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from threading import Lock

from PIL import Image


# ==========================================================
# CONFIG
# ==========================================================
CTXR3_EXE = Path(r"J:\Mega\Games\MG Master Collection\Self made mods\Tooling\CTXR3\CTXR-Converter 1.6\ctxr3.exe")

PREFIX = "mgs2/textures/flatlist/_win"
OUT_CTXR_LIST_TXT = "ctxr_list.txt"
DEPLOY_DIRS_TXT = "deploy_directories.txt"
CONVERSION_CSV = "conversion_hashes.csv"

TEXTURE_FIXES_ROOT = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes")

# This script will ONLY process images (PNG or TGA) whose stem matches NO-MIP rules (DPF_NOMIPS equivalent)
NO_MIP_REGEX_PATH = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes\no_mip_regex.txt")
MANUAL_UI_TEXTURES_PATH = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes\ps2 textures\manual_ui_textures.txt")

PRINT_LOCK = Lock()


def log(msg: str) -> None:
    with PRINT_LOCK:
        print(msg)


def pause_and_exit(code: int = 1) -> int:
    try:
        input("\nPress ENTER to exit...")
    except KeyboardInterrupt:
        pass
    return code


def sha1_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def image_has_any_transparency(path: Path) -> bool:
    """
    True if image contains any alpha < 255 anywhere (any transparency).
    Supports PNG, TGA, and other formats PIL can open.
    """
    with Image.open(path) as im:
        if im.mode == "P":
            if "transparency" in im.info:
                im = im.convert("RGBA")
            else:
                return False

        if im.mode in ("RGBA", "LA"):
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            alpha = im.getchannel("A")
            lo, _hi = alpha.getextrema()
            return lo < 255

        return False


def read_deploy_directories(txt_path: Path, base_dir: Path) -> list[Path]:
    if not txt_path.is_file():
        raise FileNotFoundError(f"Missing {DEPLOY_DIRS_TXT} in CWD: {txt_path}")

    out: list[Path] = []
    for raw in txt_path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(";"):
            continue

        p = Path(s)
        if not p.is_absolute():
            p = (base_dir / p).resolve()

        out.append(p)

    seen: set[str] = set()
    unique: list[Path] = []
    for p in out:
        k = str(p).lower()
        if k in seen:
            continue
        seen.add(k)
        unique.append(p)

    return unique


def ensure_under_texture_fixes_root(cwd: Path) -> Path:
    try:
        rel = cwd.resolve().relative_to(TEXTURE_FIXES_ROOT.resolve())
    except Exception:
        raise RuntimeError(
            "Current working directory is not under Texture Fixes root.\n"
            f"Texture Fixes root:\n  {TEXTURE_FIXES_ROOT}\n"
            f"Current working directory:\n  {cwd}\n"
        )
    return rel


def load_existing_csv(csv_path: Path) -> dict[str, dict[str, str]]:
    if not csv_path.is_file():
        return {}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return {}

        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            fn = (row.get("filename") or "").strip()
            if not fn:
                continue
            rows[fn] = {k: (v if v is not None else "") for k, v in row.items()}
        return rows


def write_conversion_csv(csv_path: Path, rows_by_filename: dict[str, dict[str, str]]) -> None:
    header = ["filename", "before_hash", "ctxr_hash", "mipmaps", "origin_folder", "opacity_stripped", "upscaled"]
    tmp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()

        for filename in sorted(rows_by_filename.keys(), key=lambda s: s.lower()):
            row = rows_by_filename[filename]
            out = {h: row.get(h, "") for h in header}
            writer.writerow(out)

    tmp_path.replace(csv_path)


def delete_ctxrs(ctxr_paths: list[Path]) -> None:
    deleted = 0
    failed: list[tuple[Path, str]] = []

    for p in ctxr_paths:
        try:
            if p.is_file():
                p.unlink()
                deleted += 1
        except Exception as e:
            failed.append((p, str(e)))

    log(f"\nCleanup: deleted {deleted} .ctxr files from CWD.")
    if failed:
        log("Cleanup: some deletions failed:")
        for p, err in failed[:50]:
            log(f"  {p.name}: {err}")
        if len(failed) > 50:
            log(f"  ...and {len(failed) - 50} more")


def cleanup_existing_ctxrs(cwd: Path) -> None:
    ctxrs = sorted(p for p in cwd.iterdir() if p.is_file() and p.suffix.lower() == ".ctxr")

    if not ctxrs:
        return

    log(f"Startup cleanup: removing {len(ctxrs)} existing .ctxr files from CWD...")
    failures: list[tuple[Path, str]] = []

    for p in ctxrs:
        try:
            p.unlink()
            log(f"  deleted {p.name}")
        except Exception as e:
            failures.append((p, str(e)))

    if failures:
        log("ERROR: Failed to delete some existing .ctxr files:")
        for p, err in failures:
            log(f"  {p.name}: {err}")
        raise RuntimeError("Startup cleanup failed due to locked or undeletable .ctxr files")


# ==========================================================
# NO-MIP (DPF_NOMIPS) FILTER
# ==========================================================
def load_no_mip_regexes_or_die(path: Path) -> list[re.Pattern]:
    if not path.is_file():
        raise RuntimeError(f"no_mip_regex.txt not found: {path}")

    patterns: list[re.Pattern] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(line, flags=re.IGNORECASE))
        except re.error as e:
            raise RuntimeError(f"Invalid regex in {path}: {line} ({e})")

    return patterns


def load_manual_ui_textures_or_die(path: Path) -> set[str]:
    if not path.is_file():
        raise RuntimeError(f"manual_ui_textures.txt not found: {path}")

    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line.lower())

    return out


def should_use_nomips(stem_lower: str, rx_list: list[re.Pattern], manual_set: set[str]) -> bool:
    if stem_lower in manual_set:
        return True

    for rx in rx_list:
        if rx.search(stem_lower) is not None:
            return True

    return False


def main() -> int:
    cwd = Path.cwd()

    # HARD CLEAN: remove any leftover ctxrs before starting (in CWD)
    try:
        cleanup_existing_ctxrs(cwd)
    except Exception as e:
        log(str(e))
        return pause_and_exit(1)

    if not CTXR3_EXE.is_file():
        log(f"ERROR: ctxr3.exe not found:\n{CTXR3_EXE}")
        return pause_and_exit(1)

    try:
        origin_rel = ensure_under_texture_fixes_root(cwd)
    except Exception as e:
        log(f"ERROR: {e}")
        return pause_and_exit(1)

    origin_folder = str(origin_rel)

    # Load NO-MIP rules (DPF_NOMIPS equivalent)
    try:
        no_mip_regexes = load_no_mip_regexes_or_die(NO_MIP_REGEX_PATH)
        manual_ui_textures = load_manual_ui_textures_or_die(MANUAL_UI_TEXTURES_PATH)
    except Exception as e:
        log(f"ERROR: {e}")
        return pause_and_exit(1)

    # Gather PNGs + TGAs from CWD, then FILTER to only DPF_NOMIPS-qualifying stems
    all_images = sorted(
        p
        for p in cwd.iterdir()
        if p.is_file() and p.suffix.lower() in {".png", ".tga"}
    )
    if not all_images:
        log(f"ERROR: No PNG or TGA files found in CWD:\n{cwd}")
        return pause_and_exit(1)

    tex_paths: list[Path] = []
    skipped: list[Path] = []
    for p in all_images:
        stem_lower = p.stem.lower()
        if should_use_nomips(stem_lower, no_mip_regexes, manual_ui_textures):
            tex_paths.append(p)
        else:
            skipped.append(p)

    if skipped:
        log(f"[INFO] Skipping {len(skipped)} image(s) that are NOT NO-MIPS (manual handling expected for these).")
        for p in skipped[:50]:
            log(f"  [SKIP NOT NOMIPS] {p.name}")
        if len(skipped) > 50:
            log(f"  ...and {len(skipped) - 50} more")
        log("")

    if not tex_paths:
        log("ERROR: After NO-MIPS filtering, there are 0 images to process in CWD.")
        log("This script now only processes textures that would use DPF_NOMIPS.")
        return pause_and_exit(1)

    stems = [p.stem for p in tex_paths]
    ctxr_names = [f"{s}.ctxr" for s in stems]
    line = f"{PREFIX}/<{'|'.join(ctxr_names)}>"

    ctxr_list_path = cwd / OUT_CTXR_LIST_TXT
    ctxr_list_path.write_text(line + "\n", encoding="utf-8", newline="\n")
    log(f"Wrote 1 line to: {ctxr_list_path}")

    deploy_txt = cwd / DEPLOY_DIRS_TXT
    try:
        deploy_dirs = read_deploy_directories(deploy_txt, cwd)
    except Exception as e:
        log(f"ERROR: {e}")
        return pause_and_exit(1)

    if not deploy_dirs:
        log(f"ERROR: {DEPLOY_DIRS_TXT} has no valid directories.")
        return pause_and_exit(1)

    for d in deploy_dirs:
        if not d.is_dir():
            log(f"ERROR: Deploy directory does not exist or is not a folder:\n  {d}")
            return pause_and_exit(1)

    os.startfile(ctxr_list_path)

    log(f"Launching CTXR3 and waiting for it to close:\n{CTXR3_EXE}")
    proc = subprocess.Popen([str(CTXR3_EXE)], cwd=CTXR3_EXE.parent, shell=False)
    exit_code = proc.wait()
    log(f"CTXR3 exited with code: {exit_code}")

    # Precompute metadata (ONLY for the NO-MIPS filtered set)
    log("\nHashing source images + checking transparency...")
    tex_meta: dict[str, tuple[str, str]] = {}  # stem -> (before_hash, opacity_stripped)
    for p in tex_paths:
        before_hash = sha1_file(p)
        # true if NO transparency
        opacity_stripped = "true" if not image_has_any_transparency(p) else "false"
        tex_meta[p.stem] = (before_hash, opacity_stripped)

    # Discover whatever .ctxr files CTXR3 actually created in this folder
    ctxr_files = sorted(
        p for p in cwd.iterdir()
        if p.is_file() and p.suffix.lower() == ".ctxr"
    )

    if not ctxr_files:
        log("ERROR: No .ctxr files found in CWD after CTXR3 run. Nothing to deploy.")
        return pause_and_exit(1)

    # Only process ctxrs whose stems match NO-MIPS source images we know about
    processed_ctxr_files: list[Path] = []
    ignored_ctxr_files: list[Path] = []

    for p in ctxr_files:
        if p.stem in tex_meta:
            processed_ctxr_files.append(p)
        else:
            ignored_ctxr_files.append(p)

    if not processed_ctxr_files:
        log("ERROR: Found .ctxr files, but none match NO-MIPS source images in this folder.")
        if ignored_ctxr_files:
            log("The following .ctxr files were ignored because their stems do not match any NO-MIPS image:")
            for p in ignored_ctxr_files[:50]:
                log(f"  {p.name}")
            if len(ignored_ctxr_files) > 50:
                log(f"  ...and {len(ignored_ctxr_files) - 50} more")
        return pause_and_exit(1)

    log(f"\nFound {len(processed_ctxr_files)} .ctxr file(s) to process.")
    if ignored_ctxr_files:
        log(f"Ignoring {len(ignored_ctxr_files)} .ctxr file(s) with unknown stems.")
        for p in ignored_ctxr_files[:50]:
            log(f"  [IGNORED] {p.name}")
        if len(ignored_ctxr_files) > 50:
            log(f"  ...and {len(ignored_ctxr_files) - 50} more")

    # Hash the ctxrs we are actually going to process
    log("\nHashing CTXRs...")
    ctxr_hashes: dict[str, str] = {}
    for p in processed_ctxr_files:
        ctxr_hashes[p.stem] = sha1_file(p)

    # Deploy and update CSVs for the processed ctxrs only
    log("\nDeploying...")
    for d in deploy_dirs:
        copied = 0
        csv_path = d / CONVERSION_CSV
        rows = load_existing_csv(csv_path)

        for ctxr_file in processed_ctxr_files:
            s = ctxr_file.stem
            src_ctxr = ctxr_file
            dst_ctxr = d / src_ctxr.name
            shutil.copy2(src_ctxr, dst_ctxr)
            copied += 1

            before_hash, opacity_stripped = tex_meta[s]
            row = rows.get(s, {})

            row["filename"] = s
            row["before_hash"] = before_hash
            row["ctxr_hash"] = ctxr_hashes[s]
            row["mipmaps"] = "false"
            row["origin_folder"] = origin_folder
            row["opacity_stripped"] = opacity_stripped

            # Preserve any existing "upscaled" field if already present, otherwise leave blank
            if "upscaled" not in row:
                row["upscaled"] = row.get("upscaled", "")

            rows[s] = row

        write_conversion_csv(csv_path, rows)

        log(f"  Deployed {copied} ctxr file(s) -> {d}")
        log(f"  Updated -> {csv_path}")

    # Cleanup only the ctxr files we processed from CWD
    delete_ctxrs(processed_ctxr_files)

    log("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
