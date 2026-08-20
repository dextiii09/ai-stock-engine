Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)

Set WshShell = CreateObject("WScript.Shell")

' 1. Start the Backend engine silently
WshShell.Run "cmd.exe /c ""cd /d """ & ScriptDir & "\backend"" && set DB_ENABLED=true && ..\.venv\Scripts\python.exe main.py""", 0, false

' 2. Wait 3 seconds for the backend to initialize
WScript.Sleep 3000

' 3. Start the Frontend Vite server silently
WshShell.Run "cmd.exe /c ""cd /d """ & ScriptDir & "\frontend"" && npm run dev""", 0, false
