@echo off
echo Starting Indian Railways Availability Planner...
echo.
echo Opening browser at:  http://localhost:8501
echo Press Ctrl+C to stop.
echo.
start "" "http://localhost:8501"
echo.|python -m streamlit run "%~dp0app.py" --server.headless true --server.port 8501
pause
