@echo off

REM Skip everything if CI env var exists
if defined CI (
    echo CI environment detected. Skipping update.
    goto :EOF
)

set "DEST=G:\Steam\steamapps\common\MGS2\plugins\MGS2-Community-Bugfix-Compilation.asi"
set "SRC=C:\Development\Git\Afevis-MGS2-Bugfix-Compilation\ASI Mod\x64\Release\MGS2-Community-Bugfix-Compilation.asi"

if exist "%DEST%" (
    echo Found existing ASI, updating...
    copy /Y "%SRC%" "%DEST%"
    echo Done.
) else (
    echo Target ASI not found. Nothing copied.
)

