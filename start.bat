@echo off
setlocal
where uv >nul 2>nul
if errorlevel 1 (
  echo uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/
  exit /b 1
)
pushd "%~dp0"
if errorlevel 1 exit /b 1
uv sync --locked --extra web
if errorlevel 1 (
  popd
  exit /b 1
)
uv run --no-sync hdmi-web %*
set "hdmi_exit=%errorlevel%"
popd
exit /b %hdmi_exit%
