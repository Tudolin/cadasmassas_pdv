<#
.SYNOPSIS
    Cadastra o PDV no Agendador de Tarefas do Windows (inicio no logon).

.DESCRIPTION
    Cria uma tarefa que roda `iniciar_pdv.ps1` quando o usuario faz logon.

    Escolhas importantes e por que:

    * Gatilho "no logon" (e nao "na inicializacao do sistema"): o PDV abre
      uma tela para o operador. Antes do logon nao existe sessao grafica
      para mostrar nada.
    * Sem privilegio de administrador: o PDV nao precisa, e tarefa elevada
      no logon dispara o UAC.
    * `-ExecutionPolicy Bypass` apenas nesta chamada: nao mexe na politica
      da maquina, so permite este script rodar.
    * A tarefa chama `wscript.exe` com o `iniciar_pdv_silencioso.vbs`, e nao
      o powershell.exe: assim NENHUMA janela aparece no logon. Com
      `powershell.exe -WindowStyle Hidden` o console e criado e so depois
      escondido, o que pisca na tela do operador.
      Como nao ha janela, o diagnostico vive todo em dados\inicializacao.log
      e dados\servidor.err.log. Para depurar com console visivel, use
      -MostrarConsole.
    * `RestartCount`: se o processo morrer, o Windows tenta de novo. Um caixa
      fora do ar e dinheiro parado.

.PARAMETER Kiosk
    A tarefa vai abrir o navegador em modo kiosk.

.PARAMETER Janela
    A tarefa vai abrir em janela nativa (pywebview).

.PARAMETER Remover
    Remove a tarefa em vez de criar.

.PARAMETER MostrarConsole
    Registra a tarefa chamando o powershell.exe direto, com a janela do
    console visivel. Por padrao a tarefa usa o wscript.exe com o
    `iniciar_pdv_silencioso.vbs`, que nao pisca janela nenhuma.
    Use isto para depurar: com o console visivel da para ver o erro na hora,
    sem precisar abrir os logs.

.PARAMETER AtrasoSegundos
    Espera, em segundos, antes de iniciar depois do logon (padrao 20). Serve
    para o PDV nao competir com o resto do que o Windows carrega no logon.

.EXAMPLE
    .\scripts\instalar_tarefa.ps1 -Kiosk
    .\scripts\instalar_tarefa.ps1 -Kiosk -AtrasoSegundos 45
    .\scripts\instalar_tarefa.ps1 -Kiosk -MostrarConsole
    .\scripts\instalar_tarefa.ps1 -Remover
#>

[CmdletBinding()]
param(
    [switch]$Kiosk,
    [switch]$Janela,
    [switch]$Remover,
    [switch]$MostrarConsole,
    [ValidateRange(0, 3600)]
    [int]$AtrasoSegundos = 20
)

$ErrorActionPreference = 'Stop'

$NomeTarefa = 'PDV Casa das Massas'
$Raiz       = Split-Path -Parent $PSScriptRoot
$Iniciador  = Join-Path $PSScriptRoot 'iniciar_pdv.ps1'

# ---------------------------------------------------------------------------
# Remover
# ---------------------------------------------------------------------------
if ($Remover) {
    $existente = Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue
    if ($existente) {
        Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false
        Write-Host "Tarefa '$NomeTarefa' removida." -ForegroundColor Green
    } else {
        Write-Host "Tarefa '$NomeTarefa' nao existe." -ForegroundColor Yellow
    }
    exit 0
}

# ---------------------------------------------------------------------------
# Conferir o ambiente antes de cadastrar
# ---------------------------------------------------------------------------
if (-not (Test-Path $Iniciador)) {
    Write-Error "Nao achei $Iniciador"
    exit 1
}

Write-Host "Raiz do projeto: $Raiz"

$python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'AVISO: o venv ainda nao existe.' -ForegroundColor Yellow
    Write-Host '       Nao e problema: o iniciar_pdv.ps1 cria na primeira execucao.'
}

# ---------------------------------------------------------------------------
# Montar a tarefa
# ---------------------------------------------------------------------------
$extras = @()
if ($Kiosk)  { $extras += '-Kiosk' }
if ($Janela) { $extras += '-Janela' }

if ($MostrarConsole) {
    # Modo depuracao: chama o PowerShell direto, janela visivel.
    $executavel = 'powershell.exe'
    $argumentos = @(
        '-NoProfile'                  # nao carrega o profile: mais rapido
        '-ExecutionPolicy', 'Bypass'  # so para esta chamada
        '-File', "`"$Iniciador`""
    ) + $extras
} else {
    # Padrao: wscript.exe roda o .vbs SEM criar console. `powershell.exe
    # -WindowStyle Hidden` nao serve aqui -- ele cria a janela e so depois
    # esconde, o que pisca na tela no logon.
    $silencioso = Join-Path $PSScriptRoot 'iniciar_pdv_silencioso.vbs'
    if (-not (Test-Path $silencioso)) {
        Write-Error "Nao achei $silencioso"
        exit 1
    }
    $executavel = 'wscript.exe'
    $argumentos = @("`"$silencioso`"") + $extras
}

$acao = New-ScheduledTaskAction `
    -Execute $executavel `
    -Argument ($argumentos -join ' ') `
    -WorkingDirectory $Raiz

$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# O Agendador de Tarefas guarda o atraso no XML como DURACAO ISO 8601
# ("PT20S"), nao como "00:00:20": passar HH:MM:SS aqui faz o
# Register-ScheduledTask falhar com "XML da tarefa contem um valor formatado
# incorretamente ou fora do intervalo" -- e a mensagem nao diz qual campo.
if ($AtrasoSegundos -gt 0) {
    $gatilho.Delay = "PT${AtrasoSegundos}S"
}

$config = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)   # 0 = sem limite: o PDV
                                                    # fica de pe o dia inteiro

# Sem -RunLevel Highest de proposito (ver descricao no topo).
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive

$descricao = 'Atualiza (git pull) e inicia o PDV da Casa das Massas no logon.'

$existente = Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue
if ($existente) {
    Write-Host "Tarefa '$NomeTarefa' ja existe; atualizando..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $NomeTarefa `
    -Action $acao `
    -Trigger $gatilho `
    -Settings $config `
    -Principal $principal `
    -Description $descricao | Out-Null

Write-Host ''
Write-Host "Tarefa '$NomeTarefa' cadastrada." -ForegroundColor Green
Write-Host ''
Write-Host 'Resumo:'
Write-Host "  Gatilho .... logon de $env:USERNAME (atraso de ${AtrasoSegundos}s)"
Write-Host "  Comando .... $executavel $($argumentos -join ' ')"
Write-Host "  Pasta ...... $Raiz"
Write-Host "  Kiosk ...... $(if ($Kiosk) { 'sim' } else { 'nao' })"
Write-Host "  Janela ..... $(if ($MostrarConsole) { 'console VISIVEL (modo depuracao)' } else { 'nenhuma (silencioso)' })"
Write-Host ''
Write-Host 'Teste agora, sem precisar reiniciar:'
Write-Host "  Start-ScheduledTask -TaskName '$NomeTarefa'" -ForegroundColor Cyan
Write-Host ''
Write-Host 'Conferir se rodou:'
Write-Host "  Get-ScheduledTaskInfo -TaskName '$NomeTarefa'" -ForegroundColor Cyan
Write-Host '  Get-Content dados\inicializacao.log -Tail 30' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Remover:'
Write-Host '  .\scripts\instalar_tarefa.ps1 -Remover' -ForegroundColor Cyan
