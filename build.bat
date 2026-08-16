@echo off
setlocal EnableDelayedExpansion
title Building EPUB to MP3

rem ===========================================================================
rem  One-click Windows build.
rem
rem  Needs, on THIS machine only:
rem    * Python 3.11, 3.12 or 3.13  (python.org installer, "Add to PATH" ticked)
rem    * Inno Setup 6              (jrsoftware.org/isdl.php) - for Setup.exe
rem
rem  The finished program needs neither. Output lands in dist\.
rem ===========================================================================

cd /d "%~dp0"
echo.
echo  ============================================================
echo   EPUB to MP3 - Windows build
echo  ============================================================
echo.

rem --- 1. Find a usable Python --------------------------------------------- #
set "PY="
for %%V in (3.12 3.11 3.13) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info < (3,14) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo  [X] No suitable Python found.
    echo.
    echo      Install Python 3.12 from https://www.python.org/downloads/
    echo      and tick "Add python.exe to PATH" during setup, then run this
    echo      script again.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%i"
echo  [1/6] Using Python %PYVER%   (%PY%)

rem --- 2. Check tkinter is present ------------------------------------------ #
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo  [X] This Python was installed without tkinter.
    echo      Re-run the python.org installer and enable "tcl/tk and IDLE".
    pause
    exit /b 1
)

rem --- 3. Build virtual environment ----------------------------------------- #
echo  [2/6] Preparing build environment...
if not exist ".buildenv\Scripts\python.exe" (
    %PY% -m venv .buildenv || goto :fail
)
set "VPY=.buildenv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check || goto :fail

echo  [3/6] Installing dependencies (a few hundred MB, please wait)...
"%VPY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :fail

rem --- 4. Sanity check the toolchain before the slow part -------------------- #
echo  [4/6] Verifying the speech engine imports...
"%VPY%" -c "import kokoro_onnx, onnxruntime, lameenc, mutagen, espeakng_loader, tkinter; print('      ok')" || goto :fail

rem --- 5. Freeze ------------------------------------------------------------- #
echo  [5/6] Building the executable (this takes a few minutes)...
if exist "dist\EpubToMP3" rmdir /s /q "dist\EpubToMP3"
"%VPY%" -m PyInstaller build\epub2mp3.spec --noconfirm --clean --distpath dist --workpath .buildwork || goto :fail

if not exist "dist\EpubToMP3\EpubToMP3.exe" (
    echo  [X] PyInstaller finished but EpubToMP3.exe is missing.
    goto :fail
)

rem --- 6. Installer ---------------------------------------------------------- #
echo  [6/6] Building Setup.exe...
set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) do if not defined ISCC if exist "%%~P" set "ISCC=%%~P"
if not defined ISCC (
    where iscc.exe >nul 2>&1 && for /f "tokens=*" %%i in ('where iscc.exe') do set "ISCC=%%i"
)

if not defined ISCC (
    echo.
    echo  [!] Inno Setup was not found, so no Setup.exe was produced.
    echo      Install it from https://jrsoftware.org/isdl.php and run this
    echo      script again - everything else is already built.
    echo.
    echo      In the meantime, the program is ready to run from:
    echo        dist\EpubToMP3\EpubToMP3.exe
    echo      You can zip that folder and it will run on any Windows 10/11 PC.
    goto :done
)

"%ISCC%" /Q "build\installer.iss" || goto :fail

:done
echo.
echo  ============================================================
echo   Build finished.
echo.
echo   Portable folder : dist\EpubToMP3\
for %%F in ("dist\EpubToMP3-*-Setup.exe") do echo   Installer       : %%F
echo.
echo   The first launch downloads a 330 MB voice model. After that
echo   the program works with no internet connection.
echo  ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo  [X] Build failed. The last message above says why.
echo.
echo      Common causes:
echo        * No internet connection while installing dependencies
echo        * Antivirus blocking PyInstaller from writing dist\
echo        * A previous build still running - close EpubToMP3.exe
echo.
pause
exit /b 1
