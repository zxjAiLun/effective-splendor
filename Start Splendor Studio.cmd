@echo off
setlocal
cd /d "%~dp0"
set "REGISTRY=%~dp0benchmarks\studio-1v1.registry.json"
set "LOGROOT=%~dp0local-artifacts\studio-host"
if not exist "%REGISTRY%" (
  echo Missing Studio registry: "%REGISTRY%"
  pause
  exit /b 1
)
if not exist "%LOGROOT%" mkdir "%LOGROOT%"

cargo build -p splendor-cli
if errorlevel 1 (
  echo Rust build failed.
  pause
  exit /b 1
)

powershell.exe -NoProfile -Command "try {$h=Invoke-RestMethod 'http://127.0.0.1:43120/health' -TimeoutSec 1;if($h.mode -eq 'studio_host'){exit 0}}catch{};exit 1"
if errorlevel 1 powershell.exe -NoProfile -Command "Start-Process -FilePath '%~dp0target\debug\splendor.exe' -ArgumentList @('studio-host','--registry','%REGISTRY%','--port','43120') -WorkingDirectory '%~dp0' -WindowStyle Hidden -RedirectStandardOutput '%LOGROOT%\host.stdout.log' -RedirectStandardError '%LOGROOT%\host.stderr.log'"

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

powershell.exe -NoProfile -Command "try {$r=Invoke-WebRequest 'http://127.0.0.1:4173/play' -UseBasicParsing -TimeoutSec 2;if($r.StatusCode -eq 200){exit 0}}catch{};exit 1"
if errorlevel 1 powershell.exe -NoProfile -Command "Start-Process -FilePath (Get-Command npm.cmd).Source -ArgumentList @('run','dev','--','--host','127.0.0.1','--port','4173') -WorkingDirectory '%~dp0apps\replay-studio' -WindowStyle Hidden -RedirectStandardOutput '%LOGROOT%\ui.stdout.log' -RedirectStandardError '%LOGROOT%\ui.stderr.log'"

powershell.exe -NoProfile -Command "$ready=$false;for($i=0;$i -lt 120;$i++){try{$h=Invoke-RestMethod 'http://127.0.0.1:43120/health' -TimeoutSec 1;$u=Invoke-WebRequest 'http://127.0.0.1:4173/play' -UseBasicParsing -TimeoutSec 2;if($h.mode -eq 'studio_host' -and $u.StatusCode -eq 200){$ready=$true;break}}catch{};Start-Sleep -Milliseconds 500};if(-not $ready){exit 1}"
if errorlevel 1 (
  echo Studio did not become ready. Inspect "%LOGROOT%".
  pause
  exit /b 1
)
if /I not "%~1"=="--no-browser" start "" "http://127.0.0.1:4173/play"
endlocal
