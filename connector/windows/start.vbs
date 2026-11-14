' DSC Bridge Connector - start hidden (no console window) with the Python inside this folder. Log: connector.log here.
Set sh = CreateObject("WScript.Shell")
here = Replace(WScript.ScriptFullName, WScript.ScriptName, "")
sh.CurrentDirectory = here
sh.Run Chr(34) & here & "python\pythonw.exe" & Chr(34) & " " & Chr(34) & here & "connector.py" & Chr(34), 0, False
