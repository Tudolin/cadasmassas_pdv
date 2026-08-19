' ===========================================================================
'  Inicia o PDV sem piscar janela nenhuma.
'
'  POR QUE ESTE ARQUIVO EXISTE
'  ---------------------------
'  Chamar `powershell.exe -WindowStyle Hidden` pela tarefa agendada AINDA
'  mostra o console por uma fracao de segundo: o Windows cria a janela e
'  so depois a esconde. No logon da loja isso aparece como um retangulo
'  azul piscando na tela -- feio, e o operador acha que algo deu errado.
'
'  O `wscript.exe` nao cria console nenhum. Ele chama o PowerShell com
'  modo de janela 0 (oculta) e nao espera pelo retorno, entao a
'  inicializacao e realmente invisivel.
'
'  CONSEQUENCIA IMPORTANTE
'  -----------------------
'  Sem janela, nao existe onde um erro aparecer. Por isso o
'  `iniciar_pdv.ps1` grava tudo em dados\inicializacao.log, e a saida do
'  servidor em dados\servidor.err.log. Quando o caixa nao abrir, esses
'  dois arquivos sao o unico lugar onde olhar.
'
'  USO
'  ---
'  Os argumentos sao repassados para o iniciar_pdv.ps1:
'
'      wscript.exe iniciar_pdv_silencioso.vbs -Kiosk
'      wscript.exe iniciar_pdv_silencioso.vbs -Kiosk -SemAtualizar
' ===========================================================================

Option Explicit

Dim shell, fso, pastaScripts, scriptPs1, argumentos, i, comando

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Caminho resolvido a partir da posicao DESTE arquivo, e nao do diretorio
' atual: a tarefa agendada pode iniciar em qualquer pasta.
pastaScripts = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPs1 = fso.BuildPath(pastaScripts, "iniciar_pdv.ps1")

If Not fso.FileExists(scriptPs1) Then
    ' Sem console para reclamar, resta a caixa de mensagem. Acontece so se
    ' alguem mover o .vbs para fora da pasta scripts\.
    MsgBox "Nao achei:" & vbCrLf & scriptPs1, 16, "PDV Casa das Massas"
    WScript.Quit 1
End If

' Repassa os argumentos recebidos (-Kiosk, -Janela, -SemAtualizar...).
argumentos = ""
For i = 0 To WScript.Arguments.Count - 1
    argumentos = argumentos & " " & WScript.Arguments(i)
Next

comando = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & _
          scriptPs1 & """" & argumentos

' 0 = janela oculta;  False = nao esperar o termino.
' Nao esperar importa: a tarefa agendada termina na hora, e o Agendador nao
' fica com a tarefa marcada como "Em execucao" o dia inteiro.
shell.Run comando, 0, False
