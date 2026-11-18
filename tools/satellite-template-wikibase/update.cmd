@echo off
rem Brings this site up to date with the current wikibase-static and publishes it.
rem
rem   update.cmd                        commit message "Rebuild with the current wikibase-static"
rem   update.cmd "Harvest 2026-11-01"   your own message
rem
rem It installs the package again (pip keeps a package of the same version, hence --force-reinstall --no-deps),
rem builds with --strict, and commits and pushes only if something changed. A failing step stops it; nothing is pushed then.
setlocal
set "MSG=%~1"
if "%MSG%"=="" set "MSG=Rebuild with the current wikibase-static"

pip install --upgrade --force-reinstall --no-deps -r requirements.txt
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
