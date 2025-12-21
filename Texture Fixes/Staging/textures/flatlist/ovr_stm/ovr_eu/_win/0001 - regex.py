import re
import shutil
from pathlib import Path

# ==========================================================
# CONFIG
# ==========================================================
REGEX_FILE = Path(r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes\no_mip_regex.txt")
ROOT = Path.cwd()
DEST = ROOT / "regex_match"
DEST.mkdir(exist_ok=True)


# ==========================================================
# LOAD REGEXES
# ==========================================================
def load_regexes(regex_file: Path):
    regexes = []
    with open(regex_file, "r", encoding="utf8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                regexes.append(re.compile(line, re.IGNORECASE))
            except re.error as e:
                print(f"Invalid regex skipped: {line} ({e})")
    return regexes


def matches_any_regex(name: str, regexes):
    for r in regexes:
        if r.search(name):
            return True
    return False


# ==========================================================
# MAIN
# ==========================================================
def main():
    regexes = load_regexes(REGEX_FILE)
    if not regexes:
        print("No valid regexes loaded.")
        return

    for path in ROOT.rglob("*.png"):
        # Skip files already inside the destination folder
        if DEST in path.parents:
            continue

        # *** changed here: match against the stem (no extension) ***
        if matches_any_regex(path.stem, regexes):
            dest = DEST / path.name
            try:
                shutil.move(str(path), dest)
                print(f"Moved: {path} -> {dest}")
            except Exception as e:
                print(f"Failed to move {path}: {e}")


if __name__ == "__main__":
    main()
