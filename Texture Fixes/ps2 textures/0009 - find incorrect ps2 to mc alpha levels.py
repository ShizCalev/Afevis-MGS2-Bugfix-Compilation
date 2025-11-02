import subprocess
import csv
import ast
import re
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# ==========================================================
# HELPERS
# ==========================================================
def get_git_root() -> Path:
    """Return the repository root by calling Git directly."""
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL)
        return Path(out.decode().strip())
    except Exception:
        raise RuntimeError("Failed to determine git repo root. Run this script inside a Git repository.")


def load_csv_to_dict(csv_path, key_col="texture_name"):
    """Load a CSV into a lowercase-keyed dictionary for case-insensitive lookups."""
    data = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row[key_col].strip().lower()] = row
    return data


def parse_alpha_list(value):
    """Parse the alpha-level column into integer lists."""
    if not value:
        return []
    try:
        vals = list(map(int, ast.literal_eval(value)))
        return [128 if v == 255 else v for v in vals]
    except Exception:
        return []


def to_int(value, default=0):
    """Safely convert a value to int, with default fallback."""
    try:
        return int(value)
    except Exception:
        return default


def inject_missing_tgas(opaque_dir: Path, ps2_data: dict) -> int:
    """Recursively find all TGA textures in OPAQUE folder and inject as default PS2 entries if missing."""
    added = 0
    tga_files = list(opaque_dir.rglob("*.tga"))
    existing_keys = set(ps2_data.keys())

    def check_and_build(path: Path):
        key = path.stem.strip().lower()
        if key not in existing_keys:
            return key, {
                "texture_name": path.stem.strip(),
                "pcsx2_alpha_levels": "[128]",
                "pcsx2_dumped_sha1": "",
                "pcsx2_resaved_sha1": "",
                "pcsx2_width": "",
                "pcsx2_height": "",
            }
        return None

    with ThreadPoolExecutor(max_workers=os.cpu_count() // 2 or 4) as ex:
        for fut in as_completed([ex.submit(check_and_build, p) for p in tga_files]):
            result = fut.result()
            if result:
                key, row = result
                ps2_data[key] = row
                added += 1
    return added


# ==========================================================
# MAIN
# ==========================================================
def main():
    repo_root = get_git_root()
    script_dir = Path(__file__).resolve().parent

    base_dir = repo_root / "external" / "MGS2-PS2-Textures" / "u - dumped from substance"
    ps2_csv = base_dir / "pcsx2_confirmed_sha1_metadata.csv"
    mc_csv = base_dir / "mgs2_mc_dimensions.csv"
    tri_csv = base_dir / "mgs2_ps2_dimensions.csv"
    opaque_dir = repo_root / "Texture Fixes" / "ps2 textures" / "OPAQUE"
    no_mip_regex_path = repo_root / "Texture Fixes" / "no_mip_regex.txt"
    log_path = script_dir / "alpha_level_mismatches.txt"

    ps2_data = load_csv_to_dict(ps2_csv)
    mc_data = load_csv_to_dict(mc_csv)
    tri_data = load_csv_to_dict(tri_csv)

    # ======================================================
    # INJECT MISSING PS2 TEXTURES FROM OPAQUE TGA FILES
    # ======================================================
    added_tgas = inject_missing_tgas(opaque_dir, ps2_data)
    print(f"Injected {added_tgas} new TGA entries from {opaque_dir}")

    # ======================================================
    # ALPHA COMPARISON LOGIC
    # ======================================================
    group1_exceeds, group1_below, group2_mismatch, group3_mismatch = [], [], [], []

    for tex_lower, ps2_row in ps2_data.items():
        tex = ps2_row["texture_name"].strip()
        ps2_alpha = parse_alpha_list(ps2_row.get("pcsx2_alpha_levels", ""))
        mc_row = mc_data.get(tex_lower)
        if not mc_row:
            continue
        mc_alpha = parse_alpha_list(mc_row.get("mc_alpha_levels", ""))
        if not ps2_alpha or not mc_alpha:
            continue

        ps2_unique = sorted(set(ps2_alpha))
        mc_unique = sorted(set(mc_alpha))

        # --- Group 1: Single-value PS2 alpha list ---
        if len(ps2_unique) == 1:
            base_val = ps2_unique[0]
            if base_val == 128:
                # Any value below 128 counts as BELOW
                if any(a < 128 for a in mc_unique):
                    group1_below.append((tex, base_val, mc_unique))
                elif any(a > 128 for a in mc_unique):
                    group1_exceeds.append((tex, base_val, mc_unique))
            else:
                if any(a > base_val for a in mc_unique):
                    group1_exceeds.append((tex, base_val, mc_unique))
                elif any(a < base_val for a in mc_unique):
                    group1_below.append((tex, base_val, mc_unique))

        # --- Group 2: Two distinct PS2 alpha values ---
        elif len(ps2_unique) == 2:
            if mc_unique != ps2_unique:
                group2_mismatch.append((tex, ps2_unique, mc_unique))

        # --- Group 3: Complex alpha lists ---
        else:
            if mc_unique != ps2_unique:
                group3_mismatch.append((tex, ps2_unique, mc_unique))

    # ======================================================
    # DIMENSION CHECKS
    # ======================================================
    def exceeds_bp(tex):
        mc_row = mc_data.get(tex.lower())
        tri_row = tri_data.get(tex.lower())
        if not mc_row or not tri_row:
            return False
        mc_w, mc_h = to_int(mc_row.get("mc_width")), to_int(mc_row.get("mc_height"))
        tri_w, tri_h = to_int(tri_row.get("tri_dumped_width_pow2")), to_int(tri_row.get("tri_dumped_height_pow2"))
        return mc_w > tri_w or mc_h > tri_h

    def is_pot(tex):
        tri_row = tri_data.get(tex.lower())
        if not tri_row:
            return False
        w, h = to_int(tri_row.get("tri_dumped_width")), to_int(tri_row.get("tri_dumped_height"))
        pw, ph = to_int(tri_row.get("tri_dumped_width_pow2")), to_int(tri_row.get("tri_dumped_height_pow2"))
        return w == pw and h == ph

    def split_bp(group):
        """Split a group into BP Remade vs OG PS2 based on dimension thresholds."""
        bp, nonbp = [], []
        for tex, ps2, mc in group:
            (bp if exceeds_bp(tex) else nonbp).append((tex, ps2, mc))
        return bp, nonbp

    bp1x, nbp1x = split_bp(group1_exceeds)
    bp1b, nbp1b = split_bp(group1_below)
    bp2, nbp2 = split_bp(group2_mismatch)
    bp3, nbp3 = split_bp(group3_mismatch)

    # ======================================================
    # SORTING (RESTORED)
    # ======================================================
    def sort_key(item):
        """Sort textures first by PS2 alpha level, then lexicographically by name."""
        tex, ps2, _ = item
        base_val = ps2[0] if isinstance(ps2, list) and ps2 else (ps2 if isinstance(ps2, int) else 0)
        return (base_val, tex.lower())

    for group in (bp1x, nbp1x, bp1b, nbp1b, bp2, nbp2, bp3, nbp3):
        group.sort(key=sort_key)

    # ======================================================
    # LOGGING
    # ======================================================
    with open(log_path, "w", encoding="utf-8") as f:
        def section(title, data):
            f.write(f"===== {title} (Count: {len(data)}) =====\n")
            if not data:
                f.write("None\n\n")
                return
            for tex, ps2, mc in data:
                ps2_str = str(ps2)
                f.write(f"{tex}\t\t\t\t\tPS2: {ps2_str}\t\t\t\t\tMC: {mc}\n")
            f.write("\n")

        # ---------------- BP REMADE SECTION ----------------
        total_bp = len(bp1x) + len(bp1b) + len(bp2) + len(bp3)
        f.write("###############################################################\n")
        f.write(f"########################  BP REMADE  (Total: {total_bp})  ##########################\n")
        f.write("###############################################################\n\n")
        section("GROUP 1 - Single Alpha Value (MC Exceeds)", bp1x)
        section("GROUP 1 - Single Alpha Value (MC Below)", bp1b)
        section("GROUP 2 - Two Alpha Values (Mismatch)", bp2)
        section("GROUP 3 - Complex Alpha Lists (Mismatch)", bp3)

        # ---------------- OG PS2 SECTION ----------------
        total_nonbp = len(nbp1x) + len(nbp1b) + len(nbp2) + len(nbp3)
        f.write("###############################################################\n")
        f.write(f"########################  OG PS2 FILES  (Total: {total_nonbp})  #########################\n")
        f.write("###############################################################\n\n")
        section("GROUP 1 - Single Alpha Value (MC Exceeds)", nbp1x)
        section("GROUP 1 - Single Alpha Value (MC Below)", nbp1b)
        section("GROUP 2 - Two Alpha Values (Mismatch)", nbp2)
        section("GROUP 3 - Complex Alpha Lists (Mismatch)", nbp3)

        # ======================================================
        # UNREFERENCED TEXTURES → REGEX → POT/NPOT
        # ======================================================
        tri_keys_lower = set(tri_data.keys())
        ps2_keys_lower = set(ps2_data.keys())
        unreferenced = sorted(
            [tri_data[k]["texture_name"].strip() for k in tri_keys_lower if k not in ps2_keys_lower],
            key=str.lower,
        )

        # Load regex patterns
        no_mip_patterns = []
        if no_mip_regex_path.exists():
            for line in open(no_mip_regex_path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#"):
                    no_mip_patterns.append(re.compile(line, re.IGNORECASE))

        def regex_split(group):
            matched, unmatched = [], []
            for tex in group:
                (matched if any(p.search(tex) for p in no_mip_patterns) else unmatched).append(tex)
            return matched, unmatched

        def pot_split(group):
            pot, npot = [], []
            for tex in group:
                (pot if is_pot(tex) else npot).append(tex)
            return pot, npot

        bp_unref = [t for t in unreferenced if exceeds_bp(t)]
        og_unref = [t for t in unreferenced if not exceeds_bp(t)]

        f.write("###############################################################\n")
        f.write("\n###################  NOT IN PCSX2 DUMP YET  (Count: {})  ################\n\n".format(len(unreferenced)))
        f.write("###############################################################\n")

        summary_counts = {}

        def log_hierarchy(title, group):
            matched, unmatched = regex_split(group)
            matched_pot, matched_npot = pot_split(matched)
            unmatched_pot, unmatched_npot = pot_split(unmatched)

            summary_counts[f"{title} | NEEDS MIPS STRIPPED - POT (NEED TO FIND)"] = len(matched_pot)
            summary_counts[f"{title} | NEEDS MIPS STRIPPED - NPOT (NEED TO FIND)"] = len(matched_npot)
            summary_counts[f"{title} | MIPS CORRECT - POT (LOW PRIORITY)"] = len(unmatched_pot)
            summary_counts[f"{title} | MIPS CORRECT - NPOT (NEED TO FIND)"] = len(unmatched_npot)

            f.write(f"===== {title} (Total: {len(group)}) =====\n\n")
            for lbl, lst in [
                ("NEEDS MIPS STRIPPED - Power of 2", matched_pot),
                ("NEEDS MIPS STRIPPED - NPOT", matched_npot),
                ("MIPS CORRECT - Power of 2 (LOW PRIORITY)", unmatched_pot),
                ("MIPS CORRECT - NPOT (NPOT)", unmatched_npot),
            ]:
                f.write(f"----- {lbl} (Count: {len(lst)}) -----\n")
                if lst:
                    for tex in sorted(lst, key=str.lower):
                        f.write(f"{tex}\n")
                else:
                    f.write("None\n")
                f.write("\n")

        log_hierarchy("BP REMADE", bp_unref)
        f.write("\n")
        log_hierarchy("OG PS2 FILES", og_unref)

        # ======================================================
        # SUMMARY TABLE
        # ======================================================
        total_mips_correct_pot = sum(v for k, v in summary_counts.items() if "MIPS CORRECT - POT (LOW PRIORITY)" in k)
        total_other = sum(v for v in summary_counts.values()) - total_mips_correct_pot
        og_left_to_find = sum(
            v for k, v in summary_counts.items()
            if k.startswith("OG PS2 FILES") and "MIPS CORRECT - POT (LOW PRIORITY)" not in k
        )

        f.write("\n###############################################################\n")
        f.write("########################  SUMMARY COUNTS FOR REMAINING UNDUMPED #########################\n")
        f.write("###############################################################\n\n")
        for k, v in summary_counts.items():
            f.write(f"{k}: {v}\n")
        f.write(f"\nTOTAL MIPS CORRECT (POT): {total_mips_correct_pot}\n")
        f.write(f"ALL OTHER CATEGORIES: {total_other}\n")
        f.write(f"COMBINED TOTAL: {total_mips_correct_pot + total_other}\n")
        f.write(f"OG PS2 LEFT TO FIND: {og_left_to_find}\n")

    # ======================================================
    # FINAL SUMMARY (Console)
    # ======================================================
    print(f"\nDone.\nRepo root: {repo_root}")
    print(f"Log written to: {log_path}")
    print(f"Unreferenced total: {len(unreferenced)} (BP+OG split by regex and POT)")
    print(f"MIPS CORRECT (POT / LOW PRIORITY): {total_mips_correct_pot}, LEFT TO DUMP: {total_other}")
    print(f"OG PS2 LEFT TO FIND: {og_left_to_find}")


if __name__ == "__main__":
    main()
