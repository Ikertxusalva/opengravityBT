Set WshShell = CreateObject("WScript.Shell")
Set WshEnv = WshShell.Environment("Process")
WshEnv("PATH") = "C:\Users\Public\node-v22.15.0-win-x64;" & WshEnv("PATH")
WshEnv("HL_TESTNET_PRIVATE_KEY") = "0xbca839ea4293b419e36ecc0f50f61af15bdb8242e6feb4fa05288c615d64aa94"

' Kill orphaned processes that block port 8888
WshShell.Run "cmd /c taskkill /F /IM electron.exe >nul 2>&1", 0, True
WshShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr "":8888"" ^| findstr ""LISTENING""') do taskkill /F /PID %a >nul 2>&1", 0, True

WScript.Sleep 1000

' Launch OpenGravity
WshShell.CurrentDirectory = "c:\Users\ijsal\OneDrive\Documentos\OpenGravity\opengravity-app"
WshShell.Run "npm.cmd run dev", 1, False
