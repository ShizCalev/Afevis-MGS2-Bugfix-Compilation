from __future__ import annotations

import subprocess
import sys
from pathlib import Path


LNK_NAME = "0001 - Stage Files.py.lnk"


def pause_and_exit(code: int = 1) -> None:
    try:
        input("\nPress ENTER to exit...")
    except KeyboardInterrupt:
        pass
    raise SystemExit(code)


def ps_quote_single(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def run_shortcut_and_wait(lnk_path: Path) -> int:
    lnk_path = lnk_path.resolve()
    forced_wd = lnk_path.parent  # <-- THIS is the whole point
    lnk_ps = ps_quote_single(str(lnk_path))
    wd_ps = ps_quote_single(str(forced_wd))

    # Resolve .lnk via COM for TargetPath + Arguments.
    # Force WorkingDirectory to the shortcut's folder so relative paths behave.
    ps_script = (
        "$ErrorActionPreference='Stop';"
        "try {"
        f"$sc=(New-Object -ComObject WScript.Shell).CreateShortcut({lnk_ps});"
        "$tp=$sc.TargetPath;"
        "$al=$sc.Arguments;"
        f"$wd={wd_ps};"
        "if([string]::IsNullOrWhiteSpace($tp)){Write-Host '[FATAL] Shortcut has empty TargetPath'; exit 9001}"
        "if([string]::IsNullOrWhiteSpace($al)) {"
        "  $p=Start-Process -FilePath $tp -WorkingDirectory $wd -PassThru -Wait;"
        "} else {"
        "  $p=Start-Process -FilePath $tp -ArgumentList $al -WorkingDirectory $wd -PassThru -Wait;"
        "}"
        "exit $p.ExitCode"
        "} catch {"
        "Write-Host $_.Exception.Message;"
        "exit 9003"
        "}"
    )

    for exe in ("powershell", "pwsh"):
        try:
            r = subprocess.run(
                [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                check=False,
            )
            return r.returncode
        except FileNotFoundError:
            continue

    print("[FATAL] Could not find PowerShell (powershell or pwsh) on PATH.")
    return 9002


def main() -> None:
    root = Path(__file__).resolve().parent

    # Find shortcuts specifically under _win folders
    lnks = sorted(
        root.rglob(LNK_NAME),
        key=lambda p: str(p).lower(),
    )

    # If you want to be strict: only those where parent folder is actually named "_win"
    lnks = [p for p in lnks if p.parent.name.lower() == "_win"]

    if not lnks:
        print(f"[FATAL] No '{LNK_NAME}' shortcuts found under any _win folder beneath:")
        print(f"  {root}")
        pause_and_exit(1)

    print(f"[INFO] Found {len(lnks)} shortcut(s). Running sequentially.\n")

    for i, lnk in enumerate(lnks, start=1):
        print("=================================================")
        print(f"[{i}/{len(lnks)}] Running shortcut:")
        print(f"  {lnk}")
        print("Forced working directory:")
        print(f"  {lnk.parent}")
        print("=================================================")

        rc = run_shortcut_and_wait(lnk)
        if rc != 0:
            print(f"\n[FATAL] Shortcut execution failed (exit code {rc}):")
            print(f"  {lnk}")
            pause_and_exit(rc)

        print("")

    print("[OK] All shortcuts finished successfully.")
    pause_and_exit(0)


if __name__ == "__main__":
    main()
