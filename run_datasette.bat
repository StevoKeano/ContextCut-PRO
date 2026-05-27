@echo off
echo Installing Datasette (if needed)...
pip install -q datasette
echo.
echo Launching Datasette on .contextcut_sessions.db
echo Open http://127.0.0.1:8001 in your browser
echo Press Ctrl+C to stop
echo.
datasette -i .contextcut_sessions.db --metadata datasette.yml --port 8001
