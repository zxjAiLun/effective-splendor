@echo off
rem Splendor Studio launcher.
rem
rem This is a convenience, not infrastructure: it types the two commands a person
rem would otherwise type by hand, and nothing else. Both processes get their own
rem visible window, so the log *is* the window and closing a window stops that
rem process. There is deliberately no pid file, no stop script, no hidden window,
rem no health probe and no restart logic.
rem
rem The /D switch gives each window its working directory, which avoids nesting a
rem `cd /d "..."` inside `cmd /k "..."` — cmd's quote handling around a nested
rem quote pair is the classic way these one-liners break.
rem
rem History: the previous version of this launcher started both processes hidden and
rem recorded their PIDs from PowerShell. An on-access antivirus flagged that shape
rem (its combination of a hidden launch, a handle written to disk, and network calls
rem in the same script) and locked the file. This version removes those patterns and
rem its command lines were smoke-tested, but note the honest limit: the launcher
rem itself has not been executed from a double-click outside the test harness, so no
rem claim is made that no antivirus will ever flag it.
setlocal
cd /d "%~dp0"

if not exist "%~dp0benchmarks\studio-1v1.registry.json" (
  echo Missing Studio registry: "%~dp0benchmarks\studio-1v1.registry.json"
  pause
  exit /b 1
)

cargo build -p splendor-cli
if errorlevel 1 (
  echo Rust build failed.
  pause
  exit /b 1
)

if not exist "%~dp0apps\replay-studio\node_modules" (
  pushd "%~dp0apps\replay-studio"
  call npm.cmd install
  if errorlevel 1 (
    popd
    echo npm install failed.
    pause
    exit /b 1
  )
  popd
)

start "Splendor Studio Host" /D "%~dp0" cmd /k cargo run -p splendor-cli --bin splendor -- studio-host --registry benchmarks/studio-1v1.registry.json --reviewer-registry benchmarks/studio-reviewers.registry.json --port 43120 --project-root .

start "Splendor Replay Studio" /D "%~dp0apps\replay-studio" cmd /k npm run dev -- --host 127.0.0.1 --port 4173

rem Give the Host a moment to bind before the browser arrives.
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:4173/league"
endlocal
