' Launch NM Finance with no console window.
Set sh = CreateObject("WScript.Shell")
ps = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & _
     CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & _
     "\start_fiidesk.ps1"""
sh.Run ps, 0, False
