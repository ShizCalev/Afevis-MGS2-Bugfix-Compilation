# verify_delete_and_prune_csv.py

from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from PIL import Image

STAGING_FOLDER = Path.cwd()
REQUIRED_SUBPATH = r"Afevis-MGS2-Bugfix-Compilation\Texture Fixes"
FOLDERS_TXT = "folders to process.txt"
CONVERSION_CSV = "conversion_hashes.csv"
ERROR_LOG_PATH = "conversion_error_log.txt"


# ==========================================================
# PARAM EXPORT CONFIG
# ==========================================================
PARAM_FOLDER = Path(r"J:\Mega\Games\MG Master Collection\Self made mods\Tooling\CTXR File Conversion\mgs2-param")
NVTT_EXPORT_EXE = Path(r"C:\Program Files\NVIDIA Corporation\NVIDIA Texture Tools\nvtt_export.exe")

DPF_DEFAULT = Path(r"J:\Mega\Games\MG Master Collection\Self made mods\Tooling\CTXR File Conversion\mgs_kaiser.dpf")
DPF_NOMIPS = Path(r"J:\Mega\Games\MG Master Collection\Self made mods\Tooling\CTXR File Conversion\mgs_nomips.dpf")

CTXR_TOOL_EXE = Path(r"J:\Mega\Games\MG Master Collection\Self made mods\Tooling\CTXR File Conversion\mgs2-param\CtxrTool.exe")
CTXR_TOOL_SUCCESS_LINE = "Running CtxrTool v1.3: Visit https://github.com/Jayveer/CtxrTool for updates:"

NO_MIP_REGEX_PATH = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes\no_mip_regex.txt")
MANUAL_UI_TEXTURES_PATH = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes\ps2 textures\manual_ui_textures.txt")


CSV_FLUSH_SECONDS = 5.0

PRINT_LOCK = Lock()


def log(msg: str):
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


def read_folder_list(txt_path: Path) -> list[Path]:
    if not txt_path.is_file():
        raise FileNotFoundError(f'Missing "{FOLDERS_TXT}" at {txt_path}')

    folders: list[Path] = []
    for raw in txt_path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        folders.append(Path(line))
    return folders


def validate_paths_or_die(folders: list[Path]) -> None:
    required_lower = REQUIRED_SUBPATH.lower()
    bad: list[Path] = []

    for f in folders:
        if required_lower not in str(f).lower():
            bad.append(f)

    if not bad:
        return

    log("[FATAL] One or more paths are outside the allowed root!")
    log(f"[FATAL] Required subpath: {REQUIRED_SUBPATH}\n")
    for p in bad:
        log(f"  INVALID: {p}")
    raise RuntimeError("Path validation failed")


def list_image_files_non_recursive(folder: Path) -> list[Path]:
    if not folder.is_dir():
        log(f"[WARN] Not a directory: {folder}")
        return []

    out: list[Path] = []
    try:
        for p in folder.iterdir():
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            if suf == ".png" or suf == ".tga":
                out.append(p)
    except Exception as e:
        log(f"[WARN] Failed scanning {folder}: {e}")
        return []

    out.sort(key=lambda x: x.name.lower())
    return out


def gather_image_files_non_recursive(folders: list[Path]) -> list[Path]:
    image_files: list[Path] = []
    for folder in folders:
        image_files.extend(list_image_files_non_recursive(folder))
    image_files.sort(key=lambda p: p.name.lower())
    return image_files


# ==========================================================
# NO-MIP / UI FILTERS
# ==========================================================
def load_no_mip_regexes_or_die(path: Path) -> list[re.Pattern]:
    if not path.is_file():
        raise RuntimeError(f"no_mip_regex.txt not found: {path}")

    patterns: list[re.Pattern] = []
    for raw in path.read_text(encoding="utf8").splitlines():
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
    for raw in path.read_text(encoding="utf8").splitlines():
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


def should_opacity_be_stripped_from_path(path_str: str) -> bool:
    return "opaque" in (path_str or "").lower()


# ==========================================================
# ERROR LOG HELPERS
# ==========================================================
def write_error_log_or_die(path: Path, failed_images: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = sorted({p.name.lower() for p in failed_images})
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf8")


def remove_error_log_if_exists(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        pass


# ==========================================================
# CSV HELPERS
# ==========================================================
def bool_from_csv(val: str) -> bool:
    v = (val or "").strip().lower()
    return v in ("1", "true", "yes", "y", "t")


def bool_to_csv(val: bool) -> str:
    return "true" if val else "false"


def ensure_csv_header_has_columns(header: list[str], needed_cols: list[str]) -> list[str]:
    existing_lower = [h.lower() for h in header]
    out = list(header)
    for col in needed_cols:
        if col.lower() not in existing_lower:
            out.append(col)
            existing_lower.append(col.lower())
    return out


def sort_rows_by_filename(rows: list[dict[str, str]]) -> None:
    rows.sort(key=lambda r: ((r.get("filename") or r.get("Filename") or r.get("FILENAME") or "").strip().lower()))


def write_conversion_csv_atomic(csv_path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    sort_rows_by_filename(rows)
    tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    tmp.replace(csv_path)


def append_conversion_csv_rows(csv_path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    if not csv_path.is_file():
        raise RuntimeError(f"CSV does not exist for append: {csv_path}")

    with csv_path.open("a", encoding="utf8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        for row in rows:
            w.writerow(row)


# ==========================================================
# ORIGIN HELPERS
# ==========================================================
def origin_relative_to_required_subpath_or_die(image_path: Path) -> str:
    required_lower = REQUIRED_SUBPATH.lower()
    full_str = str(image_path)

    lower = full_str.lower()
    idx = lower.find(required_lower)
    if idx < 0:
        raise RuntimeError(f'Image path does not contain REQUIRED_SUBPATH "{REQUIRED_SUBPATH}": {image_path}')

    rel = full_str[idx + len(REQUIRED_SUBPATH):]
    rel = rel.lstrip(r"\/")

    rel_folder = str(Path(rel).parent)
    rel_folder = rel_folder.replace("/", "\\").strip("\\")
    return rel_folder


# ==========================================================
# LOAD / MAP CSV
# mapping entry: (before_hash, ctxr_hash, used_nomips_bool, origin_folder_string, opacity_stripped_bool)
# NOTE: CSV mipmaps column means "has mipmaps". Internally we track "used_nomips".
# ==========================================================
def load_conversion_csv_unique_or_die(
    csv_path: Path,
) -> tuple[dict[str, tuple[str, str, bool, str, bool]], list[dict[str, str]], list[str]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f'Missing "{CONVERSION_CSV}" at {csv_path}')

    with csv_path.open("r", encoding="utf8", newline="") as f:
        rdr = csv.DictReader(f)
        if rdr.fieldnames is None:
            raise RuntimeError(f"{CONVERSION_CSV} has no header row")

        required = ["filename", "before_hash", "ctxr_hash", "mipmaps", "origin_folder", "opacity_stripped"]
        header_lower = [h.strip().lower() for h in rdr.fieldnames]
        for col in required:
            if col not in header_lower:
                raise RuntimeError(f'{CONVERSION_CSV} missing required column "{col}"')

        header = rdr.fieldnames

        rows: list[dict[str, str]] = []
        mapping: dict[str, tuple[str, str, bool, str, bool]] = {}
        duplicates: list[str] = []

        for row in rdr:
            filename = (row.get("filename") or row.get("Filename") or row.get("FILENAME") or "").strip()
            before_hash = (row.get("before_hash") or row.get("Before_hash") or row.get("BEFORE_HASH") or "").strip().lower()
            ctxr_hash = (row.get("ctxr_hash") or row.get("Ctxr_hash") or row.get("CTXR_HASH") or "").strip().lower()

            mipmaps_raw = (row.get("mipmaps") or row.get("Mipmaps") or row.get("MIPMAPS") or "").strip()
            origin_folder = (row.get("origin_folder") or row.get("Origin_folder") or row.get("ORIGIN_FOLDER") or "").strip()

            opacity_raw = (row.get("opacity_stripped") or row.get("Opacity_stripped") or row.get("OPACITY_STRIPPED") or "").strip()

            if not filename:
                continue

            name = filename.lower()
            if name in mapping:
                duplicates.append(filename)
            else:
                has_mipmaps = bool_from_csv(mipmaps_raw)
                used_nomips = not has_mipmaps
                opacity_stripped = bool_from_csv(opacity_raw)
                mapping[name] = (before_hash, ctxr_hash, used_nomips, origin_folder, opacity_stripped)

            rows.append(row)

        if duplicates:
            log("[FATAL] conversion_hashes.csv contains duplicate filename rows.")
            for d in sorted(set([x.lower() for x in duplicates])):
                log(f"  DUPLICATE: {d}")
            raise RuntimeError("conversion_hashes.csv filenames must be unique")

    log(f"[INFO] Loaded {len(mapping)} unique entries from {CONVERSION_CSV}\n")
    return mapping, rows, header


# ==========================================================
# IMAGE HASH + ORIGIN + OPACITY STRIPPED EXPECTATION (UNIQUENESS ENFORCED)
# ==========================================================
def hash_images_unique_or_die(
    image_files: list[Path],
    workers: int,
) -> tuple[dict[str, str], dict[str, str], dict[str, bool]]:
    if not image_files:
        log("[WARN] No .png or .tga files found in listed folders.")
        return {}, {}, {}

    log(f"[INFO] Hashing {len(image_files)} png/tga files\n")

    hashes_by_name: dict[str, set[str]] = {}
    origin_by_name: dict[str, set[str]] = {}
    opacity_expected_by_name: dict[str, set[bool]] = {}

    def worker(path: Path) -> tuple[str, str, str, bool]:
        stem = path.stem.lower()
        digest = sha1_file(path)
        origin = origin_relative_to_required_subpath_or_die(path)
        opacity_expected = should_opacity_be_stripped_from_path(str(path))
        return (stem, digest, origin, opacity_expected)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, p) for p in image_files]
        for fut in as_completed(futures):
            name, digest, origin, opacity_expected = fut.result()

            s = hashes_by_name.get(name)
            if s is None:
                s = set()
                hashes_by_name[name] = s
            s.add(digest)

            o = origin_by_name.get(name)
            if o is None:
                o = set()
                origin_by_name[name] = o
            o.add(origin)

            oe = opacity_expected_by_name.get(name)
            if oe is None:
                oe = set()
                opacity_expected_by_name[name] = oe
            oe.add(opacity_expected)

    bad_hash: list[tuple[str, list[str]]] = []
    bad_origin: list[tuple[str, list[str]]] = []
    bad_opacity: list[str] = []

    out_hash: dict[str, str] = {}
    out_origin: dict[str, str] = {}
    out_opacity_expected: dict[str, bool] = {}

    for name, digests in hashes_by_name.items():
        if len(digests) > 1:
            bad_hash.append((name, sorted(digests)))
            continue
        out_hash[name] = next(iter(digests))

    for name, origins in origin_by_name.items():
        if len(origins) > 1:
            bad_origin.append((name, sorted(origins)))
            continue
        out_origin[name] = next(iter(origins))

    for name, vals in opacity_expected_by_name.items():
        if len(vals) > 1:
            bad_opacity.append(name)
            continue
        out_opacity_expected[name] = next(iter(vals))

    if bad_hash:
        log("[FATAL] The same filename appeared with multiple different image hashes.")
        for name, digests in sorted(bad_hash, key=lambda x: x[0]):
            log(f"  {name}:")
            for d in digests:
                log(f"    {d}")
        raise RuntimeError("Duplicate image filenames with multiple hashes")

    if bad_origin:
        log("[FATAL] The same filename appeared in multiple different origin folders.")
        for name, origins in sorted(bad_origin, key=lambda x: x[0]):
            log(f"  {name}:")
            for o in origins:
                log(f"    {o}")
        raise RuntimeError("Duplicate image filenames across multiple folders")

    if bad_opacity:
        log("[FATAL] The same filename appeared with conflicting opacity_stripped expectations.")
        for n in sorted(bad_opacity):
            log(f"  {n}")
        raise RuntimeError("Duplicate image filenames with conflicting opaque detection")

    log(f"[INFO] Collected {len(out_hash)} unique image names (stems)\n")
    return out_hash, out_origin, out_opacity_expected


# ==========================================================
# PARAM EXPORT HELPERS
# ==========================================================
def delete_param_outputs_or_die(param_dir: Path) -> None:
    if not param_dir.is_dir():
        raise RuntimeError(f"Param folder does not exist or is not a directory: {param_dir}")

    deleted = 0
    failed = 0

    for p in sorted(param_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf != ".dds" and suf != ".ctxr":
            continue

        try:
            p.unlink()
            deleted += 1
            log(f"[PARAM DEL] {p.name}")
        except Exception as e:
            failed += 1
            log(f"[PARAM FAIL] {p.name} (delete error: {e})")

    log(f"[PARAM] Deleted {deleted} file(s) in param folder")
    if failed:
        raise RuntimeError(f"Failed deleting {failed} file(s) in param folder")

def delete_tmp_rgb_outputs_or_die(tmp_dir: Path) -> None:
    if not tmp_dir.exists():
        return

    if not tmp_dir.is_dir():
        raise RuntimeError(f"Temp RGB folder exists but is not a directory: {tmp_dir}")

    deleted = 0
    failed = 0

    for p in sorted(tmp_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".png":
            continue

        try:
            p.unlink()
            deleted += 1
            log(f"[TMP RGB DEL] {p.name}")
        except Exception as e:
            failed += 1
            log(f"[TMP RGB FAIL] {p.name} (delete error: {e})")

    if deleted:
        log(f"[TMP RGB] Deleted {deleted} file(s)")
    if failed:
        raise RuntimeError(f"Failed deleting {failed} temp RGB file(s) in {tmp_dir}")


def make_temp_rgb_only_copy_or_die(src: Path, tmp_dir: Path) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # stems are enforced unique earlier, so this is safe even under threads
    tmp_path = tmp_dir / f"{src.stem.lower()}__rgb_tmp.png"

    with Image.open(src) as im:
        rgba = im.convert("RGBA")
        r, g, b, _a = rgba.split()
        rgb = Image.merge("RGB", (r, g, b))
        rgb.save(tmp_path, format="PNG", optimize=False)

    if not tmp_path.is_file():
        raise RuntimeError(f"Failed creating RGB-only temp copy: {tmp_path}")

    return tmp_path


def run_nvtt_exports_or_die(
    image_files: list[Path],
    conversion_map: dict[str, tuple[str, str, bool, str, bool]],
    image_hash_by_name: dict[str, str],
    image_origin_by_name: dict[str, str],
    image_used_nomips_by_name: dict[str, bool],
    image_opacity_expected_by_name: dict[str, bool],
    workers: int,
    no_mip_regexes: list[re.Pattern],
    manual_ui_textures: set[str],
    conversion_csv_path: Path,
    conversion_rows: list[dict[str, str]],
    conversion_header: list[str],
) -> None:
    if not NVTT_EXPORT_EXE.is_file():
        raise RuntimeError(f"nvtt_export.exe not found: {NVTT_EXPORT_EXE}")
    if not DPF_DEFAULT.is_file():
        raise RuntimeError(f"Default DPF not found: {DPF_DEFAULT}")
    if not DPF_NOMIPS.is_file():
        raise RuntimeError(f"No-mips DPF not found: {DPF_NOMIPS}")
    if not PARAM_FOLDER.is_dir():
        raise RuntimeError(f"Param folder not found: {PARAM_FOLDER}")
    if not CTXR_TOOL_EXE.is_file():
        raise RuntimeError(f"CtxrTool.exe not found: {CTXR_TOOL_EXE}")

    missing: list[Path] = []
    for img in image_files:
        name = img.stem.lower()
        if name not in conversion_map:
            missing.append(img)

    if not missing:
        log("[PARAM] No images missing from conversion_hashes.csv. Nothing to export.")
        remove_error_log_if_exists(ERROR_LOG_PATH)
        return

    needed_cols = ["filename", "before_hash", "ctxr_hash", "mipmaps", "origin_folder", "opacity_stripped"]
    conversion_header = ensure_csv_header_has_columns(list(conversion_header), needed_cols)

    log(f"[PARAM] Exporting {len(missing)} missing image(s) via nvtt_export + CtxrTool\n")

    os.chdir(str(PARAM_FOLDER))

    tmp_rgb_dir = PARAM_FOLDER / "_tmp_rgb_only"

    def worker(img_path: Path) -> tuple[Path, bool, str, str, str, bool, str, bool]:
        stem_lower = img_path.stem.lower()
        out_dds = PARAM_FOLDER / f"{stem_lower}.dds"
        out_ctxr = PARAM_FOLDER / f"{stem_lower}.ctxr"

        tmp_rgb_path: Path | None = None

        def cleanup_param_ctxr():
            try:
                if out_ctxr.is_file():
                    out_ctxr.unlink()
            except Exception:
                pass

        def cleanup_tmp_rgb():
            nonlocal tmp_rgb_path
            if tmp_rgb_path is None:
                return
            try:
                if tmp_rgb_path.is_file():
                    tmp_rgb_path.unlink()
            except Exception:
                pass
            tmp_rgb_path = None

        used_nomips = should_use_nomips(stem_lower, no_mip_regexes, manual_ui_textures)
        dpf_to_use = DPF_NOMIPS if used_nomips else DPF_DEFAULT

        before_hash = image_hash_by_name.get(stem_lower, "").lower()
        if not before_hash:
            return (img_path, False, "Missing before_hash for image (unexpected)", "", "", used_nomips, "", False)

        origin_folder = image_origin_by_name.get(stem_lower, "")
        if not origin_folder:
            return (img_path, False, "Missing origin_folder for image (unexpected)", before_hash, "", used_nomips, "", False)

        opacity_expected = image_opacity_expected_by_name.get(stem_lower, False)

        # If origin_folder includes "opaque", create a temporary RGB-only copy for nvtt
        nvtt_input_path = img_path
        if should_opacity_be_stripped_from_path(origin_folder):
            try:
                tmp_rgb_path = make_temp_rgb_only_copy_or_die(img_path, tmp_rgb_dir)
                nvtt_input_path = tmp_rgb_path
            except Exception as e:
                cleanup_tmp_rgb()
                cleanup_param_ctxr()
                return (img_path, False, f"Failed creating RGB-only temp copy: {e}", before_hash, "", used_nomips, origin_folder, opacity_expected)

        nvtt_args = [
            str(NVTT_EXPORT_EXE),
            "-p",
            str(dpf_to_use),
            "-o",
            str(out_dds),
            str(nvtt_input_path),
        ]

        try:
            nvtt = subprocess.run(
                nvtt_args,
                cwd=str(PARAM_FOLDER),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf8",
                errors="replace",
            )
        except Exception as e:
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            return (img_path, False, f"nvtt_export exception: {e}", before_hash, "", used_nomips, origin_folder, opacity_expected)

        if nvtt.returncode != 0:
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            out = (nvtt.stdout or "").rstrip()
            msg = f"nvtt_export failed (rc={nvtt.returncode})"
            if out:
                msg += "\n" + out
            return (img_path, False, msg, before_hash, "", used_nomips, origin_folder, opacity_expected)

        if not out_dds.is_file():
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            return (img_path, False, f"nvtt_export reported success but DDS was not created: {out_dds}", before_hash, "", used_nomips, origin_folder, opacity_expected)

        ctxr_args = [str(CTXR_TOOL_EXE), str(out_dds)]

        try:
            ctxr = subprocess.run(
                ctxr_args,
                cwd=str(PARAM_FOLDER),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf8",
                errors="replace",
            )
        except Exception as e:
            try:
                out_dds.unlink()
            except Exception:
                pass
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            return (img_path, False, f"CtxrTool exception: {e}", before_hash, "", used_nomips, origin_folder, opacity_expected)

        ctxr_out = (ctxr.stdout or "").strip()
        ctxr_ok = (ctxr_out == CTXR_TOOL_SUCCESS_LINE)

        try:
            out_dds.unlink()
        except Exception as e:
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            msg = "DDS delete failed"
            if ctxr_ok:
                msg += f": {e}"
            return (img_path, False, msg, before_hash, "", used_nomips, origin_folder, opacity_expected)

        if not ctxr_ok:
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            msg = "CtxrTool failed (unexpected output)"
            if ctxr_out:
                msg += "\n" + ctxr_out
            return (img_path, False, msg, before_hash, "", used_nomips, origin_folder, opacity_expected)

        if not out_ctxr.is_file():
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            return (img_path, False, f"CtxrTool reported success but CTXR was not created: {out_ctxr}", before_hash, "", used_nomips, origin_folder, opacity_expected)

        try:
            ctxr_hash = sha1_file(out_ctxr).lower()
        except Exception as e:
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            return (img_path, False, f"Failed hashing produced CTXR: {e}", before_hash, "", used_nomips, origin_folder, opacity_expected)

        # Copy CTXR to staging, verify hash, then delete param CTXR (cross-drive safe)
        staging_ctxr = STAGING_FOLDER / out_ctxr.name
        try:
            if staging_ctxr.exists():
                staging_ctxr.unlink()

            shutil.copy2(out_ctxr, staging_ctxr)

            if not staging_ctxr.is_file():
                cleanup_tmp_rgb()
                cleanup_param_ctxr()
                return (img_path, False, "Copy reported success but staged CTXR does not exist", before_hash, ctxr_hash, used_nomips, origin_folder, opacity_expected)

            try:
                dst_hash = sha1_file(staging_ctxr).lower()
                if dst_hash != ctxr_hash:
                    cleanup_tmp_rgb()
                    cleanup_param_ctxr()
                    return (
                        img_path,
                        False,
                        f"Staged CTXR hash mismatch (src={ctxr_hash} dst={dst_hash})",
                        before_hash,
                        ctxr_hash,
                        used_nomips,
                        origin_folder,
                        opacity_expected,
                    )
            except Exception as e:
                cleanup_tmp_rgb()
                cleanup_param_ctxr()
                return (img_path, False, f"Failed verifying staged CTXR hash: {e}", before_hash, ctxr_hash, used_nomips, origin_folder, opacity_expected)

            try:
                out_ctxr.unlink()
            except Exception as e:
                cleanup_tmp_rgb()
                cleanup_param_ctxr()
                return (img_path, False, f"Failed deleting param CTXR after copy: {e}", before_hash, ctxr_hash, used_nomips, origin_folder, opacity_expected)

        except Exception as e:
            cleanup_tmp_rgb()
            cleanup_param_ctxr()
            return (img_path, False, f"Failed copying CTXR to staging: {e}", before_hash, ctxr_hash, used_nomips, origin_folder, opacity_expected)

        cleanup_tmp_rgb()
        return (img_path, True, "", before_hash, ctxr_hash, used_nomips, origin_folder, opacity_expected)

    ok = 0
    fail = 0
    failed_images: list[Path] = []

    pending_rows: list[dict[str, str]] = []
    last_flush = time.monotonic()

    def flush_pending_rows() -> None:
        nonlocal last_flush, pending_rows

        if not pending_rows:
            last_flush = time.monotonic()
            return

        append_conversion_csv_rows(conversion_csv_path, conversion_header, pending_rows)

        conversion_rows.extend(pending_rows)
        for r in pending_rows:
            name = (r.get("filename") or "").strip().lower()
            has_mipmaps = bool_from_csv(r.get("mipmaps", ""))
            used_nomips = not has_mipmaps
            opacity_stripped = bool_from_csv(r.get("opacity_stripped", ""))
            conversion_map[name] = (
                (r.get("before_hash") or "").lower(),
                (r.get("ctxr_hash") or "").lower(),
                used_nomips,
                (r.get("origin_folder") or ""),
                opacity_stripped,
            )

        log(f"[CSV] Appended {len(pending_rows)} row(s)")
        pending_rows = []
        last_flush = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, p) for p in missing]
        for fut in as_completed(futures):
            img_path, success, details, before_hash, ctxr_hash, used_nomips, origin_folder, opacity_expected = fut.result()

            if success:
                ok += 1
                log(f"[PARAM OK] {img_path}")

                filename = img_path.stem.lower()
                has_mipmaps = not used_nomips

                pending_rows.append(
                    {
                        "filename": filename,
                        "before_hash": before_hash,
                        "ctxr_hash": ctxr_hash,
                        "mipmaps": bool_to_csv(has_mipmaps),
                        "origin_folder": origin_folder,
                        "opacity_stripped": bool_to_csv(opacity_expected),
                    }
                )
            else:
                fail += 1
                failed_images.append(img_path)
                log(f"[PARAM FAIL] {img_path}")
                if details.strip():
                    log(details.rstrip())

            now = time.monotonic()
            if now - last_flush >= CSV_FLUSH_SECONDS:
                flush_pending_rows()

    flush_pending_rows()

    log(f"\n[PARAM RESULT] OK: {ok}")
    log(f"[PARAM RESULT] FAIL: {fail}")

    if fail:
        write_error_log_or_die(ERROR_LOG_PATH, failed_images)
        raise RuntimeError("One or more nvtt_export/CtxrTool jobs failed")
    else:
        remove_error_log_if_exists(ERROR_LOG_PATH)

    # Final guarantee: sorted on disk (single atomic rewrite)
    write_conversion_csv_atomic(conversion_csv_path, conversion_header, conversion_rows)
    log("[CSV] Final alphabetical normalization complete")


# ==========================================================
# PRUNE: CSV entries that have no staged CTXR file
# ==========================================================
def prune_csv_entries_missing_staged_ctxr(
    conversion_csv_path: Path,
    conversion_header: list[str],
    conversion_rows: list[dict[str, str]],
    conversion_map: dict[str, tuple[str, str, bool, str, bool]],
) -> int:
    staged_ctxr_stems: set[str] = set()
    for p in STAGING_FOLDER.iterdir():
        if p.is_file() and p.suffix.lower() == ".ctxr":
            staged_ctxr_stems.add(p.stem.lower())

    if not staged_ctxr_stems:
        removed = len(conversion_rows)
        if removed:
            conversion_rows[:] = []
            conversion_map.clear()
            write_conversion_csv_atomic(conversion_csv_path, conversion_header, conversion_rows)
            log(f"[CSV] Removed {removed} row(s): no staged CTXR files exist")
        return removed

    pruned_rows: list[dict[str, str]] = []
    removed = 0

    for row in conversion_rows:
        filename = (row.get("filename") or row.get("Filename") or row.get("FILENAME") or "").strip().lower()
        if not filename:
            continue

        if filename not in staged_ctxr_stems:
            removed += 1
            continue

        pruned_rows.append(row)

    if removed:
        conversion_rows[:] = pruned_rows

        for k in list(conversion_map.keys()):
            if k not in staged_ctxr_stems:
                del conversion_map[k]

        write_conversion_csv_atomic(conversion_csv_path, conversion_header, conversion_rows)
        log(f"[CSV] Removed {removed} row(s): listed in CSV but missing staged CTXR")

    return removed


def main() -> int:
    folders_txt = STAGING_FOLDER / FOLDERS_TXT
    conversion_csv = STAGING_FOLDER / CONVERSION_CSV

    try:
        folders = read_folder_list(folders_txt)
        if not folders:
            log("[ERROR] No folders listed")
            return pause_and_exit(1)

        validate_paths_or_die(folders)

        workers = max(1, min(32, (os.cpu_count() or 8) * 2))

        no_mip_regexes = load_no_mip_regexes_or_die(NO_MIP_REGEX_PATH)
        manual_ui_textures = load_manual_ui_textures_or_die(MANUAL_UI_TEXTURES_PATH)

        image_files = gather_image_files_non_recursive(folders)
        image_hash_by_name, image_origin_by_name, image_opacity_expected_by_name = hash_images_unique_or_die(image_files, workers)

        image_used_nomips_by_name: dict[str, bool] = {}
        for img in image_files:
            stem_lower = img.stem.lower()
            if stem_lower not in image_used_nomips_by_name:
                image_used_nomips_by_name[stem_lower] = should_use_nomips(stem_lower, no_mip_regexes, manual_ui_textures)

        conversion_map, conversion_rows, conversion_header = load_conversion_csv_unique_or_die(conversion_csv)
        if not conversion_header:
            conversion_header = ["filename", "before_hash", "ctxr_hash", "mipmaps", "origin_folder", "opacity_stripped"]

        needed_cols = ["filename", "before_hash", "ctxr_hash", "mipmaps", "origin_folder", "opacity_stripped"]
        conversion_header = ensure_csv_header_has_columns(list(conversion_header), needed_cols)

        # Ensure file header matches if columns were added (rewrite once if needed)
        with conversion_csv.open("r", encoding="utf8", newline="") as f:
            rdr = csv.reader(f)
            first = next(rdr, None)
        if first is None:
            raise RuntimeError(f"{CONVERSION_CSV} is empty or unreadable")
        file_header_lower = [h.strip().lower() for h in first]
        if any(col.lower() not in file_header_lower for col in needed_cols):
            write_conversion_csv_atomic(conversion_csv, conversion_header, conversion_rows)
            log(f"[CSV] Rewrote {CONVERSION_CSV} to add missing columns")

        ctxr_files = sorted(
            [p for p in STAGING_FOLDER.iterdir() if p.is_file() and p.suffix.lower() == ".ctxr"],
            key=lambda p: p.name.lower(),
        )

        def hash_ctxr(path: Path) -> tuple[Path, str]:
            return (path, sha1_file(path))

        ctxr_hash_by_path: dict[Path, str] = {}
        if ctxr_files:
            log(f"[INFO] Hashing {len(ctxr_files)} ctxr files\n")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(hash_ctxr, p) for p in ctxr_files]
                for fut in as_completed(futures):
                    p, digest = fut.result()
                    ctxr_hash_by_path[p] = digest

        # ==========================================================
        # EARLY PRUNE: if image exists and CSV metadata differs
        # (before_hash OR used_nomips OR origin_folder OR opacity_stripped)
        # then remove from CSV and delete staged CTXR if present.
        # ==========================================================
        early_mismatch_names: set[str] = set()

        for name, (csv_before, _csv_ctxr, csv_used_nomips, csv_origin, csv_opacity_stripped) in conversion_map.items():
            img_before = image_hash_by_name.get(name)
            img_origin = image_origin_by_name.get(name)
            img_used_nomips = image_used_nomips_by_name.get(name)
            img_opacity_expected = image_opacity_expected_by_name.get(name)

            if img_before is None or img_origin is None or img_used_nomips is None or img_opacity_expected is None:
                continue

            origin_ok = (str(csv_origin).strip().lower() == str(img_origin).strip().lower())
            mip_ok = (csv_used_nomips == img_used_nomips)
            before_ok = (csv_before == (img_before or "").lower())
            opacity_ok = (csv_opacity_stripped == img_opacity_expected)

            if not (origin_ok and mip_ok and before_ok and opacity_ok):
                early_mismatch_names.add(name)

        delete_failures = 0
        if early_mismatch_names and ctxr_files:
            for ctxr in ctxr_files:
                name = ctxr.stem.lower()
                if name not in early_mismatch_names:
                    continue
                digest = ctxr_hash_by_path.get(ctxr, "")
                try:
                    ctxr.unlink()
                    log(f"[DEL META-MISMATCH] {digest}  {ctxr.name}")
                except Exception as e:
                    log(f"[FAIL META-MISMATCH] {digest}  {ctxr.name} (delete error: {e})")
                    delete_failures += 1

        if early_mismatch_names:
            pruned_rows: list[dict[str, str]] = []
            removed = 0

            for row in conversion_rows:
                filename = (row.get("filename") or row.get("Filename") or row.get("FILENAME") or "").strip().lower()
                if filename and filename in early_mismatch_names:
                    removed += 1
                    continue
                pruned_rows.append(row)

            if removed:
                conversion_rows[:] = pruned_rows

                for k in list(conversion_map.keys()):
                    if k in early_mismatch_names:
                        del conversion_map[k]

                write_conversion_csv_atomic(conversion_csv, conversion_header, conversion_rows)
                log(f"[CSV] Removed {removed} row(s) from {CONVERSION_CSV} due to metadata changes")

        if delete_failures:
            return pause_and_exit(1)

        # Refresh ctxr list after meta mismatch deletes
        ctxr_files = sorted(
            [p for p in STAGING_FOLDER.iterdir() if p.is_file() and p.suffix.lower() == ".ctxr"],
            key=lambda p: p.name.lower(),
        )

        # ==========================================================
        # PRUNE: if listed in CSV but no staged CTXR exists, remove from CSV
        # ==========================================================
        prune_csv_entries_missing_staged_ctxr(conversion_csv, conversion_header, conversion_rows, conversion_map)

        # Refresh again after CSV prune
        ctxr_files = sorted(
            [p for p in STAGING_FOLDER.iterdir() if p.is_file() and p.suffix.lower() == ".ctxr"],
            key=lambda p: p.name.lower(),
        )

        ctxr_hash_by_path = {}
        if ctxr_files:
            log(f"[INFO] Hashing {len(ctxr_files)} ctxr files\n")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(hash_ctxr, p) for p in ctxr_files]
                for fut in as_completed(futures):
                    p, digest = fut.result()
                    ctxr_hash_by_path[p] = digest

        if not ctxr_files:
            log("[INFO] No .ctxr files found in staging folder.")

            log("\n[PARAM] Starting param export stage\n")
            delete_param_outputs_or_die(PARAM_FOLDER)
            delete_tmp_rgb_outputs_or_die(PARAM_FOLDER / "_tmp_rgb_only")
            run_nvtt_exports_or_die(
                image_files=image_files,
                conversion_map=conversion_map,
                image_hash_by_name=image_hash_by_name,
                image_origin_by_name=image_origin_by_name,
                image_used_nomips_by_name=image_used_nomips_by_name,
                image_opacity_expected_by_name=image_opacity_expected_by_name,
                workers=workers,
                no_mip_regexes=no_mip_regexes,
                manual_ui_textures=manual_ui_textures,
                conversion_csv_path=conversion_csv,
                conversion_rows=conversion_rows,
                conversion_header=conversion_header,
            )
            return 0

        # ==========================================================
        # If a non-orphan staged CTXR has no CSV entry, delete it.
        # It will be treated as "missing" and regenerated/added later.
        # ==========================================================
        deleted_missing_csv = 0
        delete_failures = 0

        for ctxr in ctxr_files:
            name = ctxr.stem.lower()
            if name not in image_hash_by_name:
                continue  # orphan handling happens elsewhere

            if name in conversion_map:
                continue

            try:
                ctxr.unlink()
                deleted_missing_csv += 1
            except Exception as e:
                log(f"[FAIL MISSING CSV] {ctxr.name} (delete error: {e})")
                delete_failures += 1

        if deleted_missing_csv:
            log(f"[INFO] Deleted {deleted_missing_csv} staged CTXR file(s) that were missing CSV entries")

        if delete_failures:
            return pause_and_exit(1)

        # Refresh ctxr_files + ctxr hashes after deletions
        ctxr_files = sorted(
            [p for p in STAGING_FOLDER.iterdir() if p.is_file() and p.suffix.lower() == ".ctxr"],
            key=lambda p: p.name.lower(),
        )

        ctxr_hash_by_path = {}
        if ctxr_files:
            log(f"[INFO] Hashing {len(ctxr_files)} ctxr files\n")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(hash_ctxr, p) for p in ctxr_files]
                for fut in as_completed(futures):
                    p, digest = fut.result()
                    ctxr_hash_by_path[p] = digest

        # ==========================================================
        # Decide actions (orphans, mismatches, keeps)
        # Mismatch includes before_hash, ctxr_hash, used_nomips, origin_folder, opacity_stripped
        # ==========================================================
        orphans: list[Path] = []
        mismatches: list[Path] = []
        keeps: list[Path] = []
        mismatched_names: set[str] = set()

        for ctxr in ctxr_files:
            name = ctxr.stem.lower()
            ctxr_digest = ctxr_hash_by_path[ctxr].lower()

            img_digest = image_hash_by_name.get(name)
            if img_digest is None:
                orphans.append(ctxr)
                continue

            expected_before, expected_ctxr, expected_used_nomips, expected_origin, expected_opacity_stripped = conversion_map[name]

            current_origin = image_origin_by_name.get(name, "")
            current_used_nomips = image_used_nomips_by_name.get(name, False)
            current_opacity_expected = image_opacity_expected_by_name.get(name, False)

            before_ok = (expected_before == (img_digest or "").lower())
            ctxr_ok = (expected_ctxr == (ctxr_digest or "").lower())
            mip_ok = (expected_used_nomips == current_used_nomips)
            origin_ok = (str(expected_origin).strip().lower() == str(current_origin).strip().lower())
            opacity_ok = (expected_opacity_stripped == current_opacity_expected)

            if before_ok and ctxr_ok and mip_ok and origin_ok and opacity_ok:
                keeps.append(ctxr)
            else:
                mismatches.append(ctxr)
                mismatched_names.add(name)

        deleted_orphans = 0
        deleted_mismatches = 0
        delete_failures = 0

        if keeps:
            for ctxr in keeps:
                log(f"[KEEP] {ctxr_hash_by_path[ctxr]}  {ctxr.name}")

        for ctxr in orphans:
            digest = ctxr_hash_by_path[ctxr]
            try:
                ctxr.unlink()
                log(f"[DEL ORPHAN] {digest}  {ctxr.name}")
                deleted_orphans += 1
            except Exception as e:
                log(f"[FAIL ORPHAN] {digest}  {ctxr.name} (delete error: {e})")
                delete_failures += 1

        for ctxr in mismatches:
            name = ctxr.stem.lower()
            ctxr_digest = (ctxr_hash_by_path[ctxr] or "").lower()

            img_digest = (image_hash_by_name.get(name) or "").lower()
            current_origin = image_origin_by_name.get(name, "")
            current_used_nomips = image_used_nomips_by_name.get(name, False)
            current_opacity_expected = image_opacity_expected_by_name.get(name, False)

            expected_before, expected_ctxr, expected_used_nomips, expected_origin, expected_opacity_stripped = conversion_map[name]

            try:
                ctxr.unlink()
                log(f"[DEL MISMATCH] {ctxr_digest}  {ctxr.name}")
                log(f"  expected_before={expected_before} actual_image={img_digest}")
                log(f"  expected_ctxr  ={expected_ctxr} actual_ctxr ={ctxr_digest}")
                log(
                    f"  expected_mipmaps={bool_to_csv(not expected_used_nomips)} "
                    f"actual_mipmaps={bool_to_csv(not current_used_nomips)}"
                )
                log(f"  expected_origin={expected_origin} actual_origin={current_origin}")
                log(
                    f"  expected_opacity_stripped={bool_to_csv(expected_opacity_stripped)} "
                    f"actual_opacity_stripped={bool_to_csv(current_opacity_expected)}"
                )
                deleted_mismatches += 1
            except Exception as e:
                log(f"[FAIL MISMATCH] {ctxr_digest}  {ctxr.name} (delete error: {e})")
                delete_failures += 1

        if mismatched_names:
            pruned_rows: list[dict[str, str]] = []
            removed = 0

            for row in conversion_rows:
                filename = (row.get("filename") or row.get("Filename") or row.get("FILENAME") or "").strip().lower()
                if filename and filename in mismatched_names:
                    removed += 1
                    continue
                pruned_rows.append(row)

            if removed > 0:
                conversion_rows[:] = pruned_rows

                for k in list(conversion_map.keys()):
                    if k in mismatched_names:
                        del conversion_map[k]

                write_conversion_csv_atomic(conversion_csv, conversion_header, conversion_rows)
                log(f"[CSV] Removed {removed} row(s) from {CONVERSION_CSV} due to mismatches")

        log("")
        log(f"[RESULT] Keep: {len(keeps)}")
        log(f"[RESULT] Deleted orphans: {deleted_orphans} (out of {len(orphans)})")
        log(f"[RESULT] Deleted mismatches: {deleted_mismatches} (out of {len(mismatches)})")
        if delete_failures:
            log(f"[RESULT] Delete failures: {delete_failures}")

        if delete_failures:
            return pause_and_exit(1)

        log("\n[PARAM] Starting param export stage\n")
        delete_param_outputs_or_die(PARAM_FOLDER)
        delete_tmp_rgb_outputs_or_die(PARAM_FOLDER / "_tmp_rgb_only")
        run_nvtt_exports_or_die(
            image_files=image_files,
            conversion_map=conversion_map,
            image_hash_by_name=image_hash_by_name,
            image_origin_by_name=image_origin_by_name,
            image_used_nomips_by_name=image_used_nomips_by_name,
            image_opacity_expected_by_name=image_opacity_expected_by_name,
            workers=workers,
            no_mip_regexes=no_mip_regexes,
            manual_ui_textures=manual_ui_textures,
            conversion_csv_path=conversion_csv,
            conversion_rows=conversion_rows,
            conversion_header=conversion_header,
        )

        return 0

    except Exception as e:
        log(f"[FATAL] {e}")
        return pause_and_exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
