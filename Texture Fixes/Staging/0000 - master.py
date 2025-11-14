import subprocess
import time
from pathlib import Path


# ==========================================================
# HELPERS
# ==========================================================
def run_step(name: str, script: Path):
    print("\n" + "=" * 72)
    print(f"RUNNING: {name}")
    print("=" * 72)

    start = time.time()

    try:
        subprocess.run(["python", str(script)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: {name} FAILED")
        print(f"Script: {script}")
        raise SystemExit(e.returncode)

    elapsed = time.time() - start
    print(f"\n{name} completed in {elapsed:.1f} seconds.")
    print("=" * 72 + "\n")


def main():
    # Folder where THIS master script lives
    base = Path(__file__).parent.resolve()

    # Scripts live right here with the master script
    step1 = base / "0001 - pull in mc files.py"
    step2 = base / "0002 - pull in tri-dumped with alphas.py"
    step3 = base / "0003 - pull in tri-dumped opaque.py"
    step4 = base / "0004 - pull in pcsx2-dumped with alpha.py"

    run_step("0001 – Pull in MC files", step1)
    run_step("0002 – Pull in TRI (with alpha)", step2)
    run_step("0003 – Pull in TRI (opaque)", step3)
    run_step("0004 – Pull in PCSX2 (with alpha)", step4)

    print("\nALL FOUR PIPELINES COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    main()
