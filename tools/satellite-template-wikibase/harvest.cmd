@echo off
rem Reads the source Wikibase again, builds and publishes the site.
rem
rem   harvest.cmd                       commit message "Harvest"
rem   harvest.cmd "Harvest 2026-11-18"  your own message
rem
rem It installs the package again (pip keeps a package of the same version, hence --force-reinstall --no-deps),
rem harvests (only what changed at the source), builds with --strict, and commits and pushes only if something changed. A failing step stops it; nothing is pushed then.
setlocal
set "MSG=%~1"
if "%MSG%"=="" set "MSG=Harvest"

pip install --upgrade --force-reinstall --no-deps -r requirements.txt
if errorlevel 1 goto failed
python main.py harvest
if errorlevel 1 goto failed
python main.py --strict
if errorlevel 1 goto failed
git add -A
git diff --cached --quiet
if not errorlevel 1 goto nothing
git commit -m "%MSG%"
if errorlevel 1 goto failed
git push
if errorlevel 1 goto failed
echo.
echo Done: built, committed and pushed.
exit /b 0

:nothing
echo.
echo Nothing changed, nothing to commit.
exit /b 0

:failed
echo.
echo Stopped: a step failed, nothing was pushed.
exit /b 1
