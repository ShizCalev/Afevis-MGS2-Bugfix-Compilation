import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from PIL import Image

# ==========================================================
# CONFIGURATION
# ==========================================================
ROOT_DIR = r"C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\Texture Fixes\mc textures\opaque"
THREADS = 12

# ==========================================================
# UTILITIES
# ==========================================================
print_lock = Lock()

def strip_alpha_in_place(path):
    """
    Remove alpha channel WITHOUT compositing.
    - RGBA: keep R,G,B as-is; drop A.
    - LA: replicate L into R,G,B; drop A.
    - P: convert to RGBA first (palette resolved), then drop A.
    """
    try:
        with Image.open(path) as im:
            mode = im.mode

            if mode == "RGBA":
                r, g, b, _ = im.split()
                rgb = Image.merge("RGB", (r, g, b))
                rgb.save(path, "PNG")
                with print_lock:
                    print(f"[alpha dropped] {path}")
                return "changed"

            elif mode == "LA":
                l, _ = im.split()
                rgb = Image.merge("RGB", (l, l, l))
                rgb.save(path, "PNG")
                with print_lock:
                    print(f"[alpha dropped] {path}")
                return "changed"

            elif mode == "P":
                # Resolve palette and possible tRNS to RGBA, then drop A
                im_rgba = im.convert("RGBA")
                r, g, b, _ = im_rgba.split()
                rgb = Image.merge("RGB", (r, g, b))
                rgb.save(path, "PNG")
                with print_lock:
                    print(f"[alpha dropped] {path}")
                return "changed"

            else:
                # No alpha present (RGB, L, etc.)
                return "skip"

    except Exception as e:
        with print_lock:
            print(f"[error] {path}: {e}")
        return "error"


def gather_pngs(root):
    out = []
    for r, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".png"):
                out.append(os.path.join(r, f))
    return out

# ==========================================================
# MAIN
# ==========================================================
def main():
    files = gather_pngs(ROOT_DIR)
    print(f"[+] Found {len(files)} PNG files under: {ROOT_DIR}")

    stats = {"changed": 0, "skip": 0, "error": 0}
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = [ex.submit(strip_alpha_in_place, p) for p in files]
        for fut in as_completed(futures):
            res = fut.result()
            if res in stats:
                stats[res] += 1

    print("\n[+] Done.")
    print(f"    Alpha removed: {stats['changed']}")
    print(f"    Already RGB : {stats['skip']}")
    print(f"    Errors      : {stats['error']}")

if __name__ == "__main__":
    main()
