from __future__ import annotations

import csv
import hashlib
import os
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


def png_has_any_transparency(png_path: Path) -> bool:
    """
    True if PNG contains any alpha < 255 anywhere (any transparency).
    """
    with Image.open(png_path) as im:
        if im.mode == "P":
            if "transparency" in im.info:
                im = im.convert("RGBA")
            else:
                return False

        if im.mode in ("RGBA", "LA"):
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            alpha = im.getchannel("A")
            lo, hi = alpha.getextrema()
            return lo < 255

        return False


def read_deploy_directories(txt_path: Path, script_dir: Path) -> list[Path]:
    if not txt_path.is_file():
        raise FileNotFoundError(f"Missing {DEPLOY_DIRS_TXT} beside the script: {txt_path}")

    out: list[Path] = []
    for raw in txt_path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(";"):
            continue

        p = Path(s)
        if not p.is_absolute():
            p = (script_dir / p).resolve()

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


def ensure_under_texture_fixes_root(script_dir: Path) -> Path:
    try:
        rel = script_dir.resolve().relative_to(TEXTURE_FIXES_ROOT.resolve())
    except Exception:
        raise RuntimeError(
            "Script folder is not under Texture Fixes root.\n"
            f"Texture Fixes root:\n  {TEXTURE_FIXES_ROOT}\n"
            f"Script folder:\n  {script_dir}\n"
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
    header = ["filename", "before_hash", "ctxr_hash", "mipmaps", "origin_folder", "opacity_stripped"]
    tmp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()

        for filename in sorted(rows_by_filename.keys()):
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

    log(f"\nCleanup: deleted {deleted} .ctxr files from the script folder.")
    if failed:
        log("Cleanup: some deletions failed:")
        for p, err in failed[:50]:
            log(f"  {p.name}: {err}")
        if len(failed) > 50:
            log(f"  ...and {len(failed) - 50} more")

def cleanup_existing_ctxrs(script_dir: Path) -> None:
    ctxrs = sorted(p for p in script_dir.iterdir() if p.is_file() and p.suffix.lower() == ".ctxr")

    if not ctxrs:
        return

    log(f"Startup cleanup: removing {len(ctxrs)} existing .ctxr files...")
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


def main() -> int:
    script_dir = Path(__file__).resolve().parent

    # HARD CLEAN: remove any leftover ctxrs before starting
    try:
        cleanup_existing_ctxrs(script_dir)
    except Exception as e:
        log(str(e))
        return pause_and_exit(1)


    if not CTXR3_EXE.is_file():
        log(f"ERROR: ctxr3.exe not found:\n{CTXR3_EXE}")
        return pause_and_exit(1)

    try:
        origin_rel = ensure_under_texture_fixes_root(script_dir)
    except Exception as e:
        log(f"ERROR: {e}")
        return pause_and_exit(1)

    origin_folder = str(origin_rel)

    pngs = sorted(p for p in script_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png")
    if not pngs:
        log(f"ERROR: No PNGs found in:\n{script_dir}")
        return pause_and_exit(1)

    stems = [p.stem for p in pngs]
    ctxr_names = [f"{s}.ctxr" for s in stems]
    line = f"{PREFIX}/<{'|'.join(ctxr_names)}>"

    ctxr_list_path = script_dir / OUT_CTXR_LIST_TXT
    ctxr_list_path.write_text(line + "\n", encoding="utf-8", newline="\n")
    log(f"Wrote 1 line to: {ctxr_list_path}")

    deploy_txt = script_dir / DEPLOY_DIRS_TXT
    try:
        deploy_dirs = read_deploy_directories(deploy_txt, script_dir)
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

    # Verify ctxr files exist
    expected_ctxr_paths: list[Path] = []
    missing_ctxr: list[str] = []

    for s in stems:
        p = script_dir / f"{s}.ctxr"
        expected_ctxr_paths.append(p)
        if not p.is_file():
            missing_ctxr.append(p.name)

    if missing_ctxr:
        log("ERROR: Missing expected .ctxr files (did CTXR3 generate them in this folder?):")
        for name in missing_ctxr[:50]:
            log(f"  {name}")
        if len(missing_ctxr) > 50:
            log(f"  ...and {len(missing_ctxr) - 50} more")
        return pause_and_exit(1)

    # Precompute metadata
    log("\nHashing PNGs + checking transparency...")
    png_meta: dict[str, tuple[str, str]] = {}  # stem -> (before_hash, opacity_stripped)
    for p in pngs:
        before_hash = sha1_file(p)
        # Per your correction: true if NO transparency
        opacity_stripped = "true" if not png_has_any_transparency(p) else "false"
        png_meta[p.stem] = (before_hash, opacity_stripped)

    log("Hashing CTXRs...")
    ctxr_hashes: dict[str, str] = {}
    for s in stems:
        ctxr_hashes[s] = sha1_file(script_dir / f"{s}.ctxr")

    # Deploy and update CSVs
    log("\nDeploying...")
    for d in deploy_dirs:
        copied = 0
        for s in stems:
            src_ctxr = script_dir / f"{s}.ctxr"
            dst_ctxr = d / src_ctxr.name
            shutil.copy2(src_ctxr, dst_ctxr)
            copied += 1

        csv_path = d / CONVERSION_CSV
        rows = load_existing_csv(csv_path)

        for s in stems:
            before_hash, opacity_stripped = png_meta[s]
            row = rows.get(s, {})

            row["filename"] = s
            row["before_hash"] = before_hash
            row["ctxr_hash"] = ctxr_hashes[s]
            row["mipmaps"] = "false"
            row["origin_folder"] = origin_folder
            row["opacity_stripped"] = opacity_stripped

            rows[s] = row

        write_conversion_csv(csv_path, rows)

        log(f"  Deployed {copied} ctxr files -> {d}")
        log(f"  Updated -> {csv_path}")

    # Cleanup ctxr files from script folder
    delete_ctxrs(expected_ctxr_paths)

    log("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
