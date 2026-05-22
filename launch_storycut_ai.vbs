Option Explicit

Dim shell, fso, appDir, pythonwPath, mainPath, command, pythonw311Path

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw311Path = fso.BuildPath(appDir, ".venv311\Scripts\pythonw.exe")
pythonwPath = fso.BuildPath(appDir, ".venv\Scripts\pythonw.exe")
mainPath = fso.BuildPath(appDir, "main.py")

If fso.FileExists(pythonw311Path) Then
    pythonwPath = pythonw311Path
End If

If Not fso.FileExists(pythonwPath) Then
    MsgBox "Python virtual environment was not found." & vbCrLf & _
           "Expected: " & pythonwPath & vbCrLf & vbCrLf & _
           "Run setup first. Recommended: double-click setup_python311_env.cmd", _
           vbCritical, "StoryCut AI"
    WScript.Quit 1
End If

If Not fso.FileExists(mainPath) Then
    MsgBox "StoryCut AI main.py was not found." & vbCrLf & _
           "Expected: " & mainPath, vbCritical, "StoryCut AI"
    WScript.Quit 1
End If

shell.CurrentDirectory = appDir
command = """" & pythonwPath & """ """ & mainPath & """"

' pythonw.exe starts the PyQt app without opening a console window.
shell.Run command, 0, False
