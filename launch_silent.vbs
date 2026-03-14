Set WshShell = CreateObject("WScript.Shell")
Set WshEnv = WshShell.Environment("Process")
WshEnv("PATH") = "C:\Users\Public\node-v22.15.0-win-x64;" & WshEnv("PATH")
WshShell.CurrentDirectory = "c:\Users\ijsal\OneDrive\Documentos\OpenGravity\opengravity-app"
WshShell.Run "cmd /c npm run dev", 0, False
