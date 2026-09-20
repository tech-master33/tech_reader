@echo off
rem ---------------------------------------------------------------------------
rem Build TechReader's native keyboard component (src\native).
rem
rem Produces:
rem   src\native\techreader_keyboard.dll   the keyboard hook DLL
rem   src\native\trk_keyboard_test.exe     the C self-test (run automatically)
rem
rem Uses gcc (MinGW-w64), which must be in PATH. The generated DLL is
rem self-contained (no libgcc runtime dependency).
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\..\src\native"

where gcc >nul 2>nul
if errorlevel 1 (
    echo ERROR: gcc not found in PATH. Install MinGW-w64 or add it to PATH.
    exit /b 1
)

echo Building techreader_keyboard.dll ...
gcc -O2 -Wall -Wextra -DTRK_KEYBOARD_BUILD -DUNICODE -D_UNICODE ^
    -shared -o techreader_keyboard.dll trk_keyboard.c ^
    -Wl,--subsystem,windows -lkernel32 -luser32 -ladvapi32 ^
    -static-libgcc
if errorlevel 1 (
    echo ERROR: DLL build failed.
    exit /b 1
)

echo Building trk_keyboard_test.exe ...
gcc -O2 -Wall -Wextra -DUNICODE -D_UNICODE ^
    -o trk_keyboard_test.exe test_sink.c techreader_keyboard.dll ^
    -static-libgcc
if errorlevel 1 (
    echo ERROR: test build failed.
    exit /b 1
)

echo.
echo Running self-test...
.\trk_keyboard_test.exe
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
    echo BUILD OK - self-test passed.
) else (
    echo BUILD OK - but self-test FAILED ^(code %RC%^).
)
exit /b %RC%
