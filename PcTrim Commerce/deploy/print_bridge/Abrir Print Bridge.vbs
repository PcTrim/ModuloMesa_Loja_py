' Inicia o Print Bridge sem janela de CMD (modo silencioso).
' Log: print_bridge.log nesta pasta. Diagnostico com janela: iniciar-print-bridge.bat
Option Explicit

Dim objShell, objFSO, wmi, processos, proc
Dim projectDir, pythonExe, pythonwExe, appFile, logFile
Dim appPathLower, cmdLower, runCmd, healthOk

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")

projectDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
pythonExe = projectDir & "\.venv\Scripts\python.exe"
pythonwExe = projectDir & "\.venv\Scripts\pythonw.exe"
appFile = projectDir & "\app.py"
logFile = projectDir & "\print_bridge.log"

If Not objFSO.FileExists(appFile) Then
    MsgBox "Arquivo app.py nao encontrado em:" & vbCrLf & appFile, vbCritical, "Print Bridge"
    WScript.Quit 1
End If

If Not objFSO.FileExists(pythonExe) Then
    MsgBox "Ambiente .venv nao encontrado." & vbCrLf & vbCrLf & _
           "Execute uma vez (com janela): iniciar-print-bridge.bat" & vbCrLf & _
           "Depois use este atalho para iniciar em silencio.", vbExclamation, "Print Bridge"
    WScript.Quit 1
End If

objShell.CurrentDirectory = projectDir

' Encerra instancias antigas do bridge neste pasta
appPathLower = LCase(appFile)
Set processos = wmi.ExecQuery("SELECT ProcessId, Name, CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'")

For Each proc In processos
    On Error Resume Next
    cmdLower = ""
    If Not IsNull(proc.CommandLine) Then
        cmdLower = LCase(proc.CommandLine)
    End If
    If InStr(cmdLower, appPathLower) > 0 Then
        proc.Terminate()
    End If
    On Error GoTo 0
Next

' Libera porta 9123 se ainda estiver em LISTENING
objShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr :9123 ^| findstr LISTENING') do @taskkill /F /PID %a 2>nul", 0, True
WScript.Sleep 700

' python.exe (nao pythonw) com saida no log; janela oculta (0)
runCmd = "cmd /c """ & Chr(34) & pythonExe & Chr(34) & " " & Chr(34) & appFile & Chr(34) & _
         " >> " & Chr(34) & logFile & Chr(34) & " 2>&1"""
objShell.Run runCmd, 0, False

' Aguarda health (ate ~8s)
healthOk = False
Dim i, http
For i = 1 To 16
    WScript.Sleep 500
    On Error Resume Next
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.Open "GET", "http://127.0.0.1:9123/health", False
    http.Send
    If Err.Number = 0 Then
        If http.Status = 200 Then
            If InStr(LCase(http.responseText), """ok"": true") > 0 Or InStr(LCase(http.responseText), """ok"":true") > 0 Then
                healthOk = True
            End If
        End If
    End If
    Err.Clear
    On Error GoTo 0
    If healthOk Then Exit For
Next

If Not healthOk Then
    MsgBox "Print Bridge iniciado, mas /health ainda nao respondeu." & vbCrLf & _
           "Confira o log:" & vbCrLf & logFile & vbCrLf & vbCrLf & _
           "Se preferir ver a janela: iniciar-print-bridge.bat", vbExclamation, "Print Bridge"
End If
