import subprocess
import csv
import ast
from pathlib import Path

# ==========================================================
# HELPERS
# ==========================================================
def get_git_root() -> Path:
    """Use Git to determine the repository root."""
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL)
        return Path(out.decode().strip())
    except Exception:
        raise RuntimeError("Failed to determine git repo root. Run this script inside a Git repository.")


def load_csv_to_dict(csv_path, key_col="texture_name"):
    data = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row[key_col].strip()] = row
    return data


def parse_alpha_list(value):
    if not value:
        return []
    try:
        vals = list(map(int, ast.literal_eval(value)))
        # Treat 255 as equivalent to 128
        return [128 if v == 255 else v for v in vals]
    except Exception:
        return []


def to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


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
    log_path = script_dir / "alpha_level_mismatches.txt"

    ps2_data = load_csv_to_dict(ps2_csv)
    mc_data = load_csv_to_dict(mc_csv)
    tri_data = load_csv_to_dict(tri_csv)

    group1_exceeds, group1_below, group2_mismatch, group3_mismatch = [], [], [], []

    for tex, ps2_row in ps2_data.items():
        ps2_alpha = parse_alpha_list(ps2_row.get("pcsx2_alpha_levels", ""))
        mc_row = mc_data.get(tex)
        if not mc_row:
            continue
        mc_alpha = parse_alpha_list(mc_row.get("mc_alpha_levels", ""))
        if not ps2_alpha or not mc_alpha:
            continue

        ps2_unique = sorted(set(ps2_alpha))
        mc_unique = sorted(set(mc_alpha))

        # --- Group 1: single-value PS2 alpha list ---
        if len(ps2_unique) == 1:
            base_val = ps2_unique[0]
            if base_val == 128:
                # Special handling: any value <128 = BELOW
                if any(a < 128 for a in mc_unique):
                    group1_below.append((tex, base_val, mc_unique))
                elif any(a > 128 for a in mc_unique):
                    group1_exceeds.append((tex, base_val, mc_unique))
            else:
                if any(a > base_val for a in mc_unique):
                    group1_exceeds.append((tex, base_val, mc_unique))
                elif any(a < base_val for a in mc_unique):
                    group1_below.append((tex, base_val, mc_unique))

        # --- Group 2: two distinct PS2 alpha values ---
        elif len(ps2_unique) == 2:
            if mc_unique != ps2_unique:
                group2_mismatch.append((tex, ps2_unique, mc_unique))

        # --- Group 3: complex alpha lists ---
        else:
            if mc_unique != ps2_unique:
                group3_mismatch.append((tex, ps2_unique, mc_unique))

    # ======================================================
    # SPLIT INTO BP REMADE / NON-BP BASED ON DIMENSIONS
    # ======================================================
    def exceeds_bp(tex):
        mc_row = mc_data.get(tex)
        tri_row = tri_data.get(tex)
        if not mc_row or not tri_row:
            return False
        mc_w = to_int(mc_row.get("mc_width"))
        mc_h = to_int(mc_row.get("mc_height"))
        tri_w = to_int(tri_row.get("tri_dumped_width_pow2"))
        tri_h = to_int(tri_row.get("tri_dumped_height_pow2"))
        return mc_w > tri_w or mc_h > tri_h

    def split_bp(group):
        bp, nonbp = [], []
        for tex, ps2, mc in group:
            (bp if exceeds_bp(tex) else nonbp).append((tex, ps2, mc))
        return bp, nonbp

    bp1x, nbp1x = split_bp(group1_exceeds)
    bp1b, nbp1b = split_bp(group1_below)
    bp2, nbp2 = split_bp(group2_mismatch)
    bp3, nbp3 = split_bp(group3_mismatch)

    # ======================================================
    # SORTING + LOGGING
    # ======================================================
    def sort_key(item):
        tex, ps2, _ = item
        base_val = ps2[0] if isinstance(ps2, list) and ps2 else (ps2 if isinstance(ps2, int) else 0)
        return (base_val, tex.lower())

    for group in (bp1x, nbp1x, bp1b, nbp1b, bp2, nbp2, bp3, nbp3):
        group.sort(key=sort_key)

    with open(log_path, "w", encoding="utf-8") as f:
        def section(title, data):
            count = len(data)
            f.write(f"===== {title} (Count: {count}) =====\n")
            if not data:
                f.write("None\n\n")
                return
            for tex, ps2, mc in data:
                ps2_str = str(ps2)
                f.write(f"{tex}\t\t\t\t\tPS2: {ps2_str}\t\t\t\t\tMC: {mc}\n")
            f.write("\n")

        # BP REMADE SECTION
        total_bp = len(bp1x) + len(bp1b) + len(bp2) + len(bp3)
        f.write("###############################################################\n")
        f.write(f"########################  BP REMADE  (Total: {total_bp})  ##########################\n")
        f.write("###############################################################\n\n")
        section("GROUP 1 - Single Alpha Value (MC Exceeds)", bp1x)
        section("GROUP 1 - Single Alpha Value (MC Below)", bp1b)
        section("GROUP 2 - Two Alpha Values (Mismatch)", bp2)
        section("GROUP 3 - Complex Alpha Lists (Mismatch)", bp3)

        # NON-BP SECTION
        total_nonbp = len(nbp1x) + len(nbp1b) + len(nbp2) + len(nbp3)
        f.write("###############################################################\n")
        f.write(f"########################  OG PS2 FILES  (Total: {total_nonbp})  #########################\n")
        f.write("###############################################################\n\n")
        section("GROUP 1 - Single Alpha Value (MC Exceeds)", nbp1x)
        section("GROUP 1 - Single Alpha Value (MC Below)", nbp1b)
        section("GROUP 2 - Two Alpha Values (Mismatch)", nbp2)
        section("GROUP 3 - Complex Alpha Lists (Mismatch)", nbp3)

        # UNREFERENCED TEXTURES
        unreferenced = sorted([tex for tex in tri_data.keys() if tex not in ps2_data], key=str.lower)
        total_unref = len(unreferenced)
        f.write("###############################################################\n")
        f.write(f"###################  NOT IN PCSX2 DUMP YET  (Count: {total_unref})  ################\n")
        f.write("###############################################################\n\n")
        if not unreferenced:
            f.write("None\n")
        else:
            for tex in unreferenced:
                f.write(f"{tex}\n")

    # ======================================================
    # SUMMARY
    # ======================================================
    print(f"Done.\nRepo root: {repo_root}")
    print(f"Log written to: {log_path}")
    print(f"BP Remade totals -> G1X:{len(bp1x)} G1B:{len(bp1b)} G2:{len(bp2)} G3:{len(bp3)} (Total {total_bp})")
    print(f"Non-BP totals    -> G1X:{len(nbp1x)} G1B:{len(nbp1b)} G2:{len(nbp2)} G3:{len(nbp3)} (Total {total_nonbp})")
    print(f"Unreferenced PS2 textures: {total_unref}")


if __name__ == "__main__":
    main()
