' Script para criar atalho na Área de Trabalho
' Este arquivo cria um atalho que abre o Sistema de Pedidos - Novaloja

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
strDesktop = objShell.SpecialFolders("Desktop")
strLink = strDesktop & "\Sistema de Pedidos.lnk"

projectDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
customIcon = projectDir & "\static\img\logo.ico"

Set objLink = objShell.CreateShortcut(strLink)
objLink.TargetPath = projectDir & "\Abrir Sistema.vbs"
objLink.WorkingDirectory = projectDir
objLink.Description = "Clique para abrir o Sistema de Pedidos sem janela de CMD"

' Usa icone personalizado se existir; caso contrario usa um icone moderno do Windows
If objFSO.FileExists(customIcon) Then
	objLink.IconLocation = customIcon & ",0"
Else
	objLink.IconLocation = "C:\Windows\System32\imageres.dll,102"
End If

objLink.Save

' Exibe mensagem de sucesso
MsgBox "Atalho 'Sistema de Pedidos' criado na Área de Trabalho com sucesso!", vbInformation, "Sucesso"
