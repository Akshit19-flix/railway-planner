@echo off
echo Creating desktop shortcut...
set TARGET=%~dp0start.bat
set SHORTCUT=%USERPROFILE%\Desktop\Railways Planner.lnk
set ICON=%SystemRoot%\System32\SHELL32.dll

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut('%SHORTCUT%'); " ^
  "$s.TargetPath = '%TARGET%'; " ^
  "$s.WorkingDirectory = '%~dp0'; " ^
  "$s.Description = 'Indian Railways Availability Planner'; " ^
  "$s.IconLocation = '%ICON%,13'; " ^
  "$s.Save()"

echo Done! Shortcut created on your Desktop: "Railways Planner"
pause
