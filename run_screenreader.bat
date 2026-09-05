@echo off
setlocal
cd /d "%~dp0"
title TechReader launcher

echo TechReader launcher
echo.

rem ----- choose the interpreter: use .venv if present, otherwise a system Python 3.10 - 3.14 -----
set "PYBASE="
if exist ".venv\Scripts\python.exe" (
    echo Using the .venv virtual environment.
    set "PYBASE=.venv\Scripts\python.exe"
    set "PYEXE=.venv\Scripts\python.exe"
    set "PYWEXE=.venv\Scripts\pythonw.exe"
    if not exist ".venv\Scripts\pythonw.exe" set "PYWEXE=.venv\Scripts\python.exe"
    goto :versioncheck
)

set "PYBASE="
where py >nul 2>nul && set "PYBASE=py -3"
if not defined PYBASE where python >nul 2>nul && set "PYBASE=python"
if not defined PYBASE goto :nopython

rem ----- resolve the matching pythonw.exe so no console window appears -----
for /f "delims=" %%E in ('%PYBASE% -c "import sys; print(sys.executable)"') do set "PYEXE=%%E"
if not exist "%PYEXE%" goto :noexe
set "PYWEXE=%PYEXE:\python.exe=\pythonw.exe%"
if not exist "%PYWEXE%" set "PYWEXE=%PYEXE%"

:versioncheck
%PYBASE% -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)"
if errorlevel 1 goto :badversion

rem ----- check each dependency; ask to install whatever is missing -----
:checkdeps
set "MISSING="
%PYBASE% -c "import importlib.util as u; ms=[p for m,p in {'wx':'wxPython','comtypes':'comtypes','keyboard':'keyboard','pythoncom':'pywin32'}.items() if u.find_spec(m) is None]; open('missing_deps.txt','w').write(' '.join(ms))" >nul 2>nul
set /p MISSING=<missing_deps.txt
if exist missing_deps.txt del missing_deps.txt
if not defined MISSING goto :ready

echo.
echo Missing TechReader dependencies: %MISSING%
set /p ANSWER=Install them now? (Y/N): 
if /i not "%ANSWER%"=="Y" goto :cancelled
echo Installing %MISSING%...
%PYBASE% -m pip install %MISSING%
if errorlevel 1 goto :installfailed
echo Dependencies installed. Verifying...
goto :checkdeps

rem ----- all good: launch windowless and log to screenreader.log -----
:ready
echo Using: %PYEXE%
echo Starting TechReader...
"%PYWEXE%" "%~dp0src\main.py" > "%~dp0screenreader.log" 2>&1
echo Started. Output is written to screenreader.log.
rem small pause so the message is readable before the window closes
ping -n 3 127.0.0.1 >nul
exit /b 0

:nopython
echo.
echo Python was not found on this system.
echo Install Python 3.10 - 3.14 from https://www.python.org/downloads/ and run this again.
pause
exit /b 1

:badversion
echo.
echo TechReader needs Python 3.10 to 3.14.
echo The interpreter found is:
%PYBASE% --version
pause
exit /b 1

:noexe
echo.
echo Could not resolve the Python executable path.
pause
exit /b 1

:cancelled
echo.
echo TechReader dependencies were not installed and are required to run.
pause
exit /b 1

:installfailed
echo.
echo Dependency installation failed (see the pip output above).
echo You can try installing manually:
echo     %PYBASE% -m pip install %MISSING%
echo If you get a permissions error, install for your user only:
echo     %PYBASE% -m pip install --user %MISSING%
pause
exit /b 1
