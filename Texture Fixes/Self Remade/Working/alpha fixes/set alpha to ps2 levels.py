import csv
import ast
from pathlib import Path
from PIL import Image

# ==========================================================
# CONFIG
# ==========================================================
CSV_PATH = Path(r"C:\Development\Git\MGS2-PS2-Textures\u - dumped from substance\pcsx2_confirmed_sha1_metadata.csv")
SCRIPT_DIR = Path.cwd()

# ==========================================================
# LOAD CSV
# ==========================================================
def load_metadata(csv_path):
    print(f"Loading CSV: {csv_path}")
    data = {}

    with open(csv_path, "r", encoding="utf8", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            name = row["texture_name"].strip().lower()

            # Parse something like "[128]"
            raw = row["pcsx2_alpha_levels"].strip()
            try:
                arr = ast.literal_eval(raw)
            except Exception:
                print(f"  ERROR parsing alpha list for {name}: {raw}")
                continue

            if not isinstance(arr, list) or len(arr) != 1:
                print(f"  ERROR: Expected a single-value alpha array for {name}, got {arr}")
                continue

            alpha_val = int(arr[0])

            data[name] = alpha_val

    print(f"Loaded {len(data)} constant-alpha entries.\n")
    return data

# ==========================================================
# CLEAN NAME (strip ONLY .png)
# ==========================================================
def base_name(filename: str) -> str:
    if filename.lower().endswith(".png"):
        return filename[:-4].lower()
    return filename.lower()

# ==========================================================
# APPLY CONSTANT ALPHA
# ==========================================================
def apply_alpha(path: Path, alpha_val: int):
    try:
        print(f"  Applying constant alpha {alpha_val} to {path.name}...")
        with Image.open(path) as img:
            img = img.convert("RGBA")

            r, g, b, _ = img.split()

            # Build full-image constant alpha channel
            a = Image.new("L", img.size, alpha_val)

            out = Image.merge("RGBA", (r, g, b, a))
            out.save(path)

        print(f"    ✓ Updated {path.name}")
    except Exception as e:
        print(f"    ERROR processing {path.name}: {e}")

# ==========================================================
# MAIN
# ==========================================================
def main():
    metadata = load_metadata(CSV_PATH)

    pngs = list(SCRIPT_DIR.glob("*.png"))
    print(f"Scanning folder: {SCRIPT_DIR}")
    print(f"Found {len(pngs)} PNGs.\n")

    for png in pngs:
        key = base_name(png.name)
        if key not in metadata:
            print(f"SKIP: {png.name} — '{key}' not in CSV")
            continue

        alpha_val = metadata[key]
        apply_alpha(png, alpha_val)

    print("\nDone. Press Enter to exit.")
    input()

if __name__ == "__main__":
    main()
