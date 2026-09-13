<#
.SYNOPSIS
    Atualiza e inicia o PDV Casa das Massas.

.DESCRIPTION
    E o script que o Agendador de Tarefas do Windows chama no logon. Ele:

      1. confere se ha commit novo na main (sem quebrar se a internet caiu);
      2. faz `git pull` se houver;
      3. cria o venv se nao existir;
      4. reinstala dependencias SO SE requirements.txt mudou (comparando
         hash SHA256 guardado em dados\requirements.hash);
      5. importa o catalogo para o cache local na primeira execucao;
      6. inicia o PDV e abre a tela.

    Tudo o que envolve rede tem timeout e falha "para o lado seguro": se o
    GitHub nao responder, o PDV abre com o codigo que ja esta no disco. A
    loja abrindo no horario vale mais do que estar na ultima versao.

.PARAMETER Kiosk
    Abre o navegador em modo kiosk (tela cheia, sem barra de endereco).

.PARAMETER Janela
    Abre em janela nativa (pywebview) em vez de navegador.

.PARAMETER SemAtualizar
    Pula o `git fetch`/`git pull`. As dependencias CONTINUAM sendo conferidas
    (um venv sem Flask precisa ser corrigido de qualquer forma).

.EXAMPLE
    .\scripts\iniciar_pdv.ps1 -Kiosk
#>

[CmdletBinding()]
param(
    [switch]$Kiosk,
    [switch]$Janela,
    [switch]$SemAtualizar
)

$ErrorActionPreference = 'Stop'

# Raiz do repositorio = pasta acima de scripts\
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz

$PastaDados = Join-Path $Raiz 'dados'
$Log        = Join-Path $PastaDados 'inicializacao.log'
$Python     = Join-Path $Raiz '.venv\Scripts\python.exe'
$HashReq    = Join-Path $PastaDados 'requirements.hash'
$Porta      = 8777

if (-not (Test-Path $PastaDados)) {
    New-Item -ItemType Directory -Path $PastaDados -Force | Out-Null
}

function Escrever {
    param([string]$Mensagem, [string]$Nivel = 'INFO')
    $linha = "{0} {1,-5} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Nivel, $Mensagem
    Write-Host $linha
    Add-Content -Path $Log -Value $linha -Encoding utf8
}

function Ler-EnvPorta {
    # A porta pode ter sido trocada no .env; o script precisa saber a mesma.
    $env_arquivo = Join-Path $Raiz '.env'
    if (-not (Test-Path $env_arquivo)) { return $Porta }
    $linha = Select-String -Path $env_arquivo -Pattern '^\s*PDV_PORTA\s*=' -ErrorAction SilentlyContinue
    if (-not $linha) { return $Porta }
    $valor = ($linha.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if ($valor -match '^\d+$') { return [int]$valor }
    return $Porta
}

function Porta-EmUso {
    # O Test-NetConnection do Windows e lento (faz ICMP antes do TCP). Um
    # TcpClient direto responde em milissegundos, que e o que importa aqui:
    # esta funcao roda em laco esperando o servidor subir.
    param([int]$Numero)
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        return $cliente.ConnectAsync('127.0.0.1', $Numero).Wait(400)
    } catch {
        return $false
    } finally {
        $cliente.Dispose()
    }
}

function Invoke-Nativo {
    <#
        Roda um executavel (git, python, pip) e devolve o codigo de saida.

        POR QUE ISSO EXISTE -- leia antes de "simplificar" para `& exe 2>$null`:

        No PowerShell 5.1, redirecionar o stderr de um programa nativo faz o
        PowerShell embrulhar CADA linha de stderr num ErrorRecord
        (NativeCommandError). Com $ErrorActionPreference = 'Stop', isso vira
        um erro TERMINANTE -- e o script morre ali, sem escrever no log.

        Foi exatamente esse o bug que deixava a inicializacao parada logo
        depois da linha do git: `python -c "import flask"` falhava (venv sem
        os pacotes), escrevia o traceback no stderr redirecionado, e o script
        era encerrado em silencio.

        Aqui o ErrorActionPreference volta para 'Continue' durante a chamada,
        entao stderr de programa externo e apenas texto -- nao acidente.
    #>
    param(
        [Parameter(Mandatory)][string]$Executavel,
        [string[]]$Argumentos = @(),
        [switch]$Silencioso
    )

    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Silencioso) {
            & $Executavel @Argumentos 2>&1 | Out-Null
        } else {
            & $Executavel @Argumentos 2>&1 | ForEach-Object {
                if ("$_".Trim()) { Escrever "  $_" }
            }
        }
        if ($null -eq $LASTEXITCODE) { return 0 }
        return $LASTEXITCODE
    } catch {
        return 1
    } finally {
        $ErrorActionPreference = $anterior
    }
}

function Testar-Pacotes {
    # O venv tem o que o PDV precisa para subir?
    return (Invoke-Nativo -Executavel $Python `
            -Argumentos @('-c', 'import flask, waitress') -Silencioso) -eq 0
}

# Rede de seguranca: qualquer erro que ninguem tratou passa por aqui ANTES de
# o script morrer. Sem isto, uma falha inesperada (arquivo faltando, permissao,
# stderr de programa externo) encerrava a inicializacao sem deixar uma linha no
# log -- e o sintoma para quem estava na loja era "simplesmente nao abre".
trap {
    Escrever "ERRO NAO TRATADO: $($_.Exception.Message)" 'ERRO'
    $onde = "$($_.InvocationInfo.ScriptName):$($_.InvocationInfo.ScriptLineNumber)"
    Escrever "  em $onde -> $($_.InvocationInfo.Line.Trim())" 'ERRO'
    exit 1
}

Escrever '================ inicializacao do PDV ================'
$Porta = Ler-EnvPorta
Escrever "raiz: $Raiz | porta: $Porta"

# ---------------------------------------------------------------------------
# Ja esta rodando?
# ---------------------------------------------------------------------------
if (Porta-EmUso -Numero $Porta) {
    Escrever "a porta $Porta ja responde: o PDV esta de pe. Abrindo a tela." 'AVISO'
    Start-Process "http://127.0.0.1:$Porta/"
    exit 0
}

# ---------------------------------------------------------------------------
# 1-2. Atualizar o codigo
# ---------------------------------------------------------------------------
$requisitosMudaram = $false

if ($SemAtualizar) {
    Escrever 'atualizacao pulada (-SemAtualizar)'
} elseif (-not (Test-Path (Join-Path $Raiz '.git'))) {
    Escrever 'nao e um repositorio git; seguindo com o codigo local' 'AVISO'
} else {
    try {
        $git = (Get-Command git -ErrorAction Stop).Source

        # Hash do requirements ANTES do pull, para saber se ele mudou.
        $reqPath = Join-Path $Raiz 'requirements.txt'
        $hashAntes = if (Test-Path $reqPath) {
            (Get-FileHash $reqPath -Algorithm SHA256).Hash
        } else { '' }

        # Teto de tempo para o git nao pendurar a abertura da loja numa rede
        # ruim. Um `Start-Job` com timeout resolveria tambem, mas custa um
        # processo PowerShell inteiro no logon -- estas duas variaveis fazem o
        # proprio git desistir: menos de 1 KB/s por 20 s = aborta.
        $env:GIT_HTTP_LOW_SPEED_LIMIT = '1000'
        $env:GIT_HTTP_LOW_SPEED_TIME  = '20'
        # Nunca pedir senha: sem isto, um repo privado abriria um prompt e a
        # tarefa ficaria pendurada para sempre, invisivel.
        $env:GIT_TERMINAL_PROMPT = '0'

        Escrever 'consultando o GitHub (git fetch)...'
        $codigoFetch = Invoke-Nativo -Executavel $git `
            -Argumentos @('fetch', '--quiet', 'origin', 'main')

        if ($codigoFetch -ne 0) {
            Escrever "git fetch falhou (codigo $codigoFetch); seguindo com o codigo local" 'AVISO'
        } else {
            $local  = (& $git rev-parse HEAD).Trim()
            $remoto = (& $git rev-parse origin/main).Trim()
            $curto  = $local.Substring(0, 7)
            $curtoR = $remoto.Substring(0, 7)

            # HEAD diferente de origin/main NAO significa "tem versao nova":
            # pode ser o contrario -- o local a frente, com commit que ainda
            # nao subiu. Antes esta funcao dizia "commit novo: local -> remoto"
            # nos dois casos e tentava puxar, o que confundia o diagnostico.
            $atrasado = (Invoke-Nativo -Executavel $git -Silencioso `
                -Argumentos @('merge-base', '--is-ancestor', 'HEAD', 'origin/main')) -eq 0
            $adiantado = (Invoke-Nativo -Executavel $git -Silencioso `
                -Argumentos @('merge-base', '--is-ancestor', 'origin/main', 'HEAD')) -eq 0

            if ($local -eq $remoto) {
                Escrever "ja esta na ultima versao ($curto)"
            } elseif ($adiantado) {
                Escrever "o local esta A FRENTE do GitHub ($curto > $curtoR); nada a puxar" 'AVISO'
                Escrever 'Ha commit aqui que nunca foi enviado (git push).' 'AVISO'
            } elseif (-not $atrasado) {
                Escrever "historico divergente ($curto vs $curtoR); pull cancelado" 'AVISO'
                Escrever 'Resolva a mao: o codigo local foi mantido.' 'AVISO'
            } else {
                Escrever "versao nova no GitHub: $curto -> $curtoR"

                # NAO checar "git status --porcelain" antes de tentar: o
                # pdv_database.db e versionado (secao 4 do README) mas e
                # tambem o banco ao vivo do PDV antigo (app.py/app.exe), que
                # grava cada venda nele. Isso deixa o repositorio "sujo" o
                # dia inteiro em producao -- se o pull fosse cancelado por
                # causa disso, ele NUNCA rodaria na loja.
                #
                # `git pull --ff-only` e seguro sem essa checagem: o proprio
                # git recusa o merge (e devolve codigo != 0) se o commit
                # remoto tocar um arquivo com alteracao local, entao dado
                # nenhum e sobrescrito por acidente. So vira aviso no log.
                $codigoPull = Invoke-Nativo -Executavel $git `
                    -Argumentos @('pull', '--ff-only', '--quiet', 'origin', 'main')
                if ($codigoPull -eq 0) {
                    Escrever 'codigo atualizado'
                    $hashDepois = (Get-FileHash $reqPath -Algorithm SHA256).Hash
                    if ($hashAntes -ne $hashDepois) {
                        Escrever 'requirements.txt mudou no pull'
                        $requisitosMudaram = $true
                    }
                } else {
                    Escrever "git pull falhou (codigo $codigoPull); seguindo com o local" 'AVISO'
                    $sujo = & $git status --porcelain
                    if ($sujo) {
                        Escrever 'provavel causa: alteracoes locais que o pull sobrescreveria' 'AVISO'
                        Escrever ($sujo -join '; ') 'AVISO'
                    }
                }
            }
        }
    } catch {
        Escrever "nao deu para atualizar: $($_.Exception.Message)" 'AVISO'
    }
}

# ---------------------------------------------------------------------------
# 3. Ambiente virtual
# ---------------------------------------------------------------------------
if (-not (Test-Path $Python)) {
    Escrever 'criando o ambiente virtual (.venv)...'
    $sistema = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $sistema) {
        Escrever 'Python nao encontrado no PATH. Instale o Python 3.11+ e rode de novo.' 'ERRO'
        exit 1
    }
    $codigoVenv = Invoke-Nativo -Executavel $sistema `
        -Argumentos @('-m', 'venv', (Join-Path $Raiz '.venv'))
    if ($codigoVenv -ne 0) { Escrever 'falhou ao criar o venv' 'ERRO'; exit 1 }
    $requisitosMudaram = $true   # venv novo = instalar tudo
}

# ---------------------------------------------------------------------------
# 4. Dependencias, so se mudaram
# ---------------------------------------------------------------------------
$reqPath = Join-Path $Raiz 'requirements.txt'
if (-not (Test-Path $reqPath)) {
    # Sem esta checagem, o Get-FileHash abaixo estoura e o `trap` registra um
    # erro apontando para dentro do modulo do PowerShell -- tecnicamente
    # correto e praticamente inutil para quem esta na loja.
    Escrever "nao achei $reqPath" 'ERRO'
    Escrever 'O repositorio esta incompleto. Confira o que veio do git pull.' 'ERRO'
    exit 1
}
$hashAtual = (Get-FileHash $reqPath -Algorithm SHA256).Hash
$hashSalvo = if (Test-Path $HashReq) { (Get-Content $HashReq -Raw).Trim() } else { '' }

# O hash sozinho nao basta: ele diz que o requirements.txt nao mudou, nao que
# o venv tem os pacotes. Venv recriado a mao, instalacao interrompida no meio
# ou pasta copiada de outra maquina deixam o hash "em dia" com o ambiente
# vazio -- e o run.py morria com ModuleNotFoundError sem ninguem ver.
$faltaPacote = $false
if (Test-Path $Python) {
    if (-not (Testar-Pacotes)) {
        Escrever 'o venv existe mas falta Flask/waitress' 'AVISO'
        $faltaPacote = $true
    }
}

if ($requisitosMudaram -or $faltaPacote -or ($hashAtual -ne $hashSalvo)) {
    Escrever 'instalando dependencias...'
    # `python -m pip` em vez do launcher $Pip (.venv\Scripts\pip.exe): o
    # launcher e um .exe pequeno com o caminho do interprete gravado dentro
    # dele, e falha em silencio ("Fatal error in launcher") quando o
    # antivirus da loja o coloca em quarentena (comum com .exe dentro de
    # .venv\Scripts) ou quando o caminho do projeto e muito longo. Chamar o
    # modulo pip pelo proprio python.exe evita as duas causas.
    $codigoPip = Invoke-Nativo -Executavel $Python `
        -Argumentos @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', '-r', $reqPath)
    if ($codigoPip -eq 0 -and (Testar-Pacotes)) {
        Set-Content -Path $HashReq -Value $hashAtual -Encoding utf8
        Escrever 'dependencias em dia'
    } else {
        Escrever 'pip install falhou; tentando iniciar com o que ja esta instalado' 'AVISO'
    }
} else {
    Escrever 'dependencias sem mudanca; pulando o pip'
}

# ---------------------------------------------------------------------------
# 5. Catalogo local na primeira execucao
# ---------------------------------------------------------------------------
$bancoPdv = Join-Path $PastaDados 'pdv.db'
if (-not (Test-Path $bancoPdv)) {
    $bancoBalanca = Join-Path $Raiz 'pdv_database.db'
    if (Test-Path $bancoBalanca) {
        Escrever 'primeira execucao: importando o catalogo para o cache local...'
        Invoke-Nativo -Executavel $Python `
            -Argumentos @((Join-Path $Raiz 'scripts\importar_catalogo_local.py')) | Out-Null
    } else {
        Escrever 'sem cache local e sem pdv_database.db; o catalogo vira do Upstash' 'AVISO'
    }
}

# ---------------------------------------------------------------------------
# 6. Subir o PDV
# ---------------------------------------------------------------------------
$RunPy = Join-Path $Raiz 'run.py'

# Conferir ANTES de chamar o Python. Sem isto, `python run.py` com o arquivo
# ausente escreve "can't open file" no stderr -- que ia para o nada, porque a
# janela e oculta -- e o log ficava parado em "processo iniciado" para sempre.
if (-not (Test-Path $RunPy)) {
    Escrever "nao achei $RunPy" 'ERRO'
    Escrever 'O repositorio parece nao ter o PDV novo (pasta pdv\ e run.py).' 'ERRO'
    Escrever 'Confira se o commit com o PDV foi enviado para a main do GitHub.' 'ERRO'
    exit 1
}
if (-not (Test-Path (Join-Path $Raiz 'pdv\web.py'))) {
    Escrever "nao achei $Raiz\pdv\web.py (pacote do PDV incompleto)" 'ERRO'
    exit 1
}

$argumentos = @($RunPy, '--sem-navegador')
if ($Janela) { $argumentos = @($RunPy, '--janela') }

# `pythonw.exe` e o Python sem console. Com `python.exe` + `-WindowStyle
# Hidden` o Windows AINDA cria a janela de console e depois esconde, o que
# pisca na cara do operador no logon. O pythonw nao cria nenhuma.
# A saida continua sendo capturada porque ela vai para arquivo (abaixo).
$PythonServidor = Join-Path $Raiz '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $PythonServidor)) { $PythonServidor = $Python }

# A saida do servidor vai para arquivo. E o que permite descobrir POR QUE ele
# nao subiu: com -WindowStyle Hidden e sem redirecionar, um traceback do
# Python desaparece sem deixar rastro.
$SaidaOut = Join-Path $PastaDados 'servidor.out.log'
$SaidaErr = Join-Path $PastaDados 'servidor.err.log'

Escrever 'iniciando o PDV...'
$processo = Start-Process -FilePath $PythonServidor -ArgumentList $argumentos `
    -WorkingDirectory $Raiz -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $SaidaOut -RedirectStandardError $SaidaErr

Escrever "processo iniciado (PID $($processo.Id))"

function Mostrar-FalhaDoServidor {
    # Traz o erro do servidor para o log da inicializacao, que e onde a
    # pessoa vai olhar primeiro.
    $achouCausa = $false

    foreach ($arquivo in @($SaidaErr, $SaidaOut)) {
        if (-not (Test-Path $arquivo)) { continue }
        $linhas = @(Get-Content $arquivo -Tail 20 -ErrorAction SilentlyContinue |
            Where-Object { $_.Trim() })
        if ($linhas.Count -gt 0) {
            Escrever "--- ultimas linhas de $(Split-Path -Leaf $arquivo) ---" 'ERRO'
            $linhas | ForEach-Object { Escrever "    $_" 'ERRO' }
            $achouCausa = $true
        }
    }

    # O pdv.log e acumulado entre execucoes, entao a "cauda" dele quase sempre
    # e o sucesso de ontem -- ruido que esconde o erro de hoje. So vale olhar
    # quando o processo nao deixou nada no stderr.
    if (-not $achouCausa) {
        $pdvLog = Join-Path $PastaDados 'pdv.log'
        if (Test-Path $pdvLog) {
            Escrever '--- nada no stderr; ultimas linhas de pdv.log ---' 'ERRO'
            Get-Content $pdvLog -Tail 10 -ErrorAction SilentlyContinue |
                Where-Object { $_.Trim() } |
                ForEach-Object { Escrever "    $_" 'ERRO' }
        } else {
            Escrever 'o servidor nao gerou log nenhum.' 'ERRO'
        }
    }

    Escrever "Detalhes completos em: $SaidaErr" 'ERRO'
}

# Espera a porta responder antes de abrir a tela: abrir antes mostraria
# "nao foi possivel conectar" e o operador acharia que o sistema nao subiu.
$pronto = $false
foreach ($tentativa in 1..60) {
    if (Porta-EmUso -Numero $Porta) { $pronto = $true; break }

    # Se o processo morreu, nao ha motivo para esperar os 15 s inteiros: o
    # erro ja aconteceu e esta no arquivo.
    if ($processo.HasExited) {
        # WaitForExit alem do HasExited: no PowerShell 5.1 o ExitCode as vezes
        # sai vazio se lido antes de o objeto Process ser atualizado.
        $processo.WaitForExit(1000) | Out-Null
        $codigo = try { $processo.ExitCode } catch { $null }
        if ($null -eq $codigo) { $codigo = 'desconhecido' }

        Escrever "o PDV encerrou sozinho (codigo $codigo)" 'ERRO'
        Mostrar-FalhaDoServidor
        exit 1
    }

    Start-Sleep -Milliseconds 250
}

if (-not $pronto) {
    Escrever 'o PDV nao respondeu em 15s' 'ERRO'
    Mostrar-FalhaDoServidor
    exit 1
}

Escrever 'PDV respondendo'

if ($Janela) {
    Escrever 'interface em janela nativa (pywebview)'
    exit 0
}

$url = "http://127.0.0.1:$Porta/"

if ($Kiosk) {
    # Kiosk: tela cheia e sem barra de endereco, para o operador nao navegar
    # para fora por acidente. Sai com Alt+F4.
    $navegadores = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    )
    $navegador = $navegadores | Where-Object { Test-Path $_ } | Select-Object -First 1

    if ($navegador) {
        Escrever "abrindo em kiosk: $(Split-Path -Leaf $navegador)"
        # `--kiosk` NAO aceita valor: e um switch booleano. Passar
        # "--kiosk=$url" faz o Chromium engolir a URL como se fosse o VALOR
        # do switch, sobrando nenhuma URL na lista de argumentos posicionais
        # -- e o navegador abre em tela cheia na pagina inicial (Google), nao
        # no PDV. A URL tem que ser um argumento SEPARADO.
        Start-Process $navegador -ArgumentList @(
            '--kiosk',
            $url,
            '--no-first-run',
            '--disable-session-crashed-bubble',
            '--disable-infobars',
            # Perfil proprio: nao mistura com a navegacao pessoal do dono no
            # mesmo notebook, e nao herda extensao nenhuma.
            "--user-data-dir=$(Join-Path $PastaDados 'perfil-navegador')"
        )
    } else {
        Escrever 'Chrome/Edge nao encontrados; abrindo no navegador padrao' 'AVISO'
        Start-Process $url
    }
} else {
    Start-Process $url
}

Escrever 'inicializacao concluida'
exit 0
