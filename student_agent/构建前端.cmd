@echo off
REM Build the Next.js student frontend and publish it into apps\static\app,
REM where the FastAPI server hosts it at http://127.0.0.1:8000/app
REM
REM Run this once before the first lesson, and again after any change
REM under frontend\src.  Double-click is fine.
setlocal
cd /d "%~dp0"

if not exist "frontend\package.json" (
  echo [x] frontend\package.json not found - is the frontend copied in?
  pause
  exit /b 1
)

cd /d "%~dp0frontend"

REM Only install when needed.  Re-running npm ci over a healthy tree is slow,
REM and a half-written node_modules makes "next build" fail with a confusing
REM internal error (Invariant: Expected workStore to be initialized) instead of
REM anything that points at the real cause.
if exist "node_modules\next\package.json" goto deps_ok

echo [1/3] installing frontend dependencies ...
call npm ci
if errorlevel 1 (
  echo.
  echo [x] npm ci failed.  Check your network, then try again.
  pause
  exit /b 1
)
goto build

:deps_ok
echo [1/3] dependencies already present - skipping npm ci

:build
echo.
echo [2/3] building static export ...
call npm run build
if errorlevel 1 (
  echo.
  echo [x] build failed - see the messages above.
  echo     If it complains about an internal Next.js invariant, the
  echo     node_modules tree is probably damaged.  Recover with:
  echo         cd frontend
  echo         rmdir /S /Q node_modules
  echo         npm ci
  pause
  exit /b 1
)

echo.
echo [3/3] publishing out\ to apps\static\app ...
cd /d "%~dp0"
if exist "apps\static\app" rmdir /S /Q "apps\static\app"
mkdir "apps\static\app"
xcopy /E /I /Y /Q "frontend\out" "apps\static\app" >nul
if errorlevel 1 (
  echo.
  echo [x] copy failed.
  pause
  exit /b 1
)

echo.
echo Done.  Now start the server and open the page:
echo     python apps\start.py
echo     http://127.0.0.1:8000/app
echo.
pause
