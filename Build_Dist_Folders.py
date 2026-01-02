from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


MAX_WORKERS = os.cpu_count() or 8

def find_git_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[ERROR] Failed to find git root via git: {exc}")
        sys.exit(1)

    root = result.stdout.strip()
    if not root:
        print("[ERROR] git rev-parse returned empty path")
        sys.exit(1)

    git_root = Path(root).resolve()
    print(f"[INFO] Git root: {git_root}")
    return git_root


def parse_bool(value: str) -> bool:
    if value is None:
        return False

    value = value.strip().lower()
    return value in {"1", "true", "yes", "y"}


def move_tree_all(origin: Path, dest: Path) -> None:
    for root, dirs, files in os.walk(origin):
        root_path = Path(root)
        rel_root = root_path.relative_to(origin)
        target_root = dest / rel_root
        target_root.mkdir(parents=True, exist_ok=True)

        for filename in files:
            src_file = root_path / filename
            dst_file = target_root / filename
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            shutil.move(str(src_file), str(dst_file))
            print(f"  [MOVE] {src_file} -> {dst_file}")


def move_tree_ctxr_only(origin: Path, dest: Path) -> None:
    moved_any = False
    for ctxr in origin.rglob("*.ctxr"):
        rel_path = ctxr.relative_to(origin)
        target = dest / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(ctxr), str(target))
        print(f"  [MOVE .ctxr] {ctxr} -> {target}")
        moved_any = True

    if not moved_any:
        print("  [INFO] No .ctxr files found to move.")


def prune_empty_dirs(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        return

    removed_any = False

    for current_root, dirs, files in os.walk(root, topdown=False):
        cur_path = Path(current_root)

        if not dirs and not files:
            try:
                os.rmdir(cur_path)
                print(f"  [RMDIR] {cur_path}")
                removed_any = True
            except OSError as exc:
                print(f"  [RMDIR FAIL] {cur_path}: {exc}")

    if not removed_any:
        print("  [INFO] No empty folders to remove under origin.")


def process_mapping(origin_abs: Path, dest_abs: Path, prune_non_ctxr: bool, idx: int) -> None:
    print(f"\n[MAP {idx}]")
    print(f"  Origin:          {origin_abs}")
    print(f"  Destination:     {dest_abs}")
    print(f"  prune_non_ctxr:  {prune_non_ctxr}")

    if not origin_abs.exists():
        print(f"[WARN] Origin does not exist, skipping: {origin_abs}")
        return

    # Single file case
    if origin_abs.is_file():
        dest_abs.parent.mkdir(parents=True, exist_ok=True)

        if prune_non_ctxr and origin_abs.suffix.lower() != ".ctxr":
            print(f"[SKIP] prune_non_ctxr enabled, skipping non .ctxr file: {origin_abs}")
            return

        shutil.move(str(origin_abs), str(dest_abs))
        print(f"[MOVE FILE] {origin_abs} -> {dest_abs}")
        return

    dest_abs.mkdir(parents=True, exist_ok=True)

    if prune_non_ctxr:
        print("[INFO] prune_non_ctxr = TRUE, moving only .ctxr files:")
        print(f"       {origin_abs} -> {dest_abs}")
        move_tree_ctxr_only(origin_abs, dest_abs)
    else:
        print("[INFO] Moving full tree:")
        print(f"       {origin_abs} -> {dest_abs}")
        move_tree_all(origin_abs, dest_abs)

    print(f"[INFO] Pruning empty folders under origin: {origin_abs}")
    prune_empty_dirs(origin_abs)


def main() -> None:
    git_root = find_git_root()
    csv_path = git_root / "Release_Structure.csv"

    if not csv_path.is_file():
        print(f"[ERROR] Release_Structure.csv not found at git root: {csv_path}")
        sys.exit(1)

    print(f"[INFO] Using mapping file: {csv_path}")

    mappings: list[tuple[int, Path, Path, bool]] = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"origin_path", "destination_path", "prune_non_ctxr"}
        if not required.issubset(set(reader.fieldnames or [])):
            print("[ERROR] CSV must have headers: origin_path,destination_path,prune_non_ctxr")
            sys.exit(1)

        for idx, row in enumerate(reader, start=1):
            origin_rel = (row.get("origin_path") or "").strip()
            dest_rel = (row.get("destination_path") or "").strip()
            prune_flag = parse_bool(row.get("prune_non_ctxr") or "")

            if not origin_rel or not dest_rel:
                print(f"[WARN] Row {idx} has empty origin or destination, skipping")
                continue

            if origin_rel.startswith("#"):
                continue

            origin_abs = (git_root / origin_rel).resolve()
            dest_abs = (git_root / dest_rel).resolve()

            mappings.append((idx, origin_abs, dest_abs, prune_flag))

    if not mappings:
        print("[INFO] No valid mappings found in CSV.")
        print("\n[INFO] Done.")
        return

    print(f"[INFO] Processing {len(mappings)} mappings with up to {MAX_WORKERS} worker threads.\n")

    def worker(mapping: tuple[int, Path, Path, bool]) -> None:
        idx, origin_abs, dest_abs, prune_flag = mapping
        process_mapping(origin_abs, dest_abs, prune_flag, idx)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, m) for m in mappings]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"[ERROR] Mapping task raised an exception: {exc}")

    print("\n[INFO] Done.")


if __name__ == "__main__":
    main()
