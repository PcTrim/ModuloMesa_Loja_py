' Inicializa o sistema sem mostrar janela de CMD
' Apos iniciar, confira na pasta do script o ficheiro ultimo_arranque_loja.txt (caminho real do app.py)
' Ou no browser: http://127.0.0.1:2001/onde-esta-o-servidor
Option Explicit

Dim objShell, objFSO, wmi, processos, proc
Dim projectDir, pythonExe, appFile, urlLogin, appPathLower, cmdLower, runCmd

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")

projectDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
pythonExe = projectDir & "\.venv\Scripts\pythonw.exe"
appFile = projectDir & "\app.py"
urlLogin = "http://127.0.0.1:2001/login"

If Not objFSO.FileExists(pythonExe) Then
    MsgBox "Python do ambiente virtual nao encontrado em:" & vbCrLf & pythonExe, vbCritical, "Erro"
    WScript.Quit 1
End If

If Not objFSO.FileExists(appFile) Then
    MsgBox "Arquivo app.py nao encontrado em:" & vbCrLf & appFile, vbCritical, "Erro"
    WScript.Quit 1
End If

objShell.CurrentDirectory = projectDir

' Encerra instancias antigas do app para evitar duplicidade
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

' Encerra QUALQUER processo em LISTENING na porta 2001 (ex.: python.exe global com app.py noutra pasta)
objShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr :2001 ^| findstr LISTENING') do @taskkill /F /PID %a 2>nul", 0, True

' Pequena espera para liberar a porta antes de iniciar novamente
WScript.Sleep 700

' Inicia o Flask em modo oculto
runCmd = Chr(34) & pythonExe & Chr(34) & " " & Chr(34) & appFile & Chr(34)
objShell.Run runCmd, 0, False

' Aguarda o servidor subir e abre o login
WScript.Sleep 3000
objShell.Run urlLogin, 0, False