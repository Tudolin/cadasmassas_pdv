# PDV — Casa das Massas Pinheirinho

Caixa (ponto de venda) para casa de massas artesanais que vende quase tudo
por peso, com etiqueta impressa pela balança.

Roda como **processo Python nativo** no notebook da loja — sem Docker, sem
banco de dados servidor, sem framework de front-end. A tela abre no navegador
em `http://127.0.0.1:8777`.

```
┌──────────────┐   etiqueta 13 dígitos    ┌─────────────────────────────┐
│   Balança    │ ───────────────────────▶ │  Leitor USB (age como       │
│  (imprime)   │                          │  teclado: digita + Enter)   │
└──────────────┘                          └──────────────┬──────────────┘
                                                         │
                    ┌────────────────────────────────────▼──────────────┐
                    │  PDV (Flask + waitress, 127.0.0.1:8777)           │
                    │                                                   │
                    │  catálogo em MEMÓRIA ── leitura nunca espera rede │
                    │  venda → SQLite (fsync) → responde ao caixa       │
                    │            │                                      │
                    │            ├── thread: imprime cupom (ESC/POS)    │
                    │            └── thread: envia venda ao Upstash     │
                    └────────────────────────┬──────────────────────────┘
                                             │ HTTPS, em segundo plano
                    ┌────────────────────────▼──────────────────────────┐
                    │  Upstash Redis  ── catálogo:*  /  venda:*         │
                    │  (compartilhado com o precifier na Vercel)        │
                    └───────────────────────────────────────────────────┘
```

---

## Índice

1. [Começando em 5 minutos](#1-começando-em-5-minutos)
2. [Configurar o Upstash Redis (passo a passo)](#2-configurar-o-upstash-redis-passo-a-passo)
3. [Testar a conexão](#3-testar-a-conexão)
4. [Publicar o catálogo](#4-publicar-o-catálogo)
5. [Como o caixa funciona](#5-como-o-caixa-funciona)
6. [A etiqueta da balança](#6-a-etiqueta-da-balança)
7. [Impressão do cupom](#7-impressão-do-cupom)
8. [Nota fiscal](#8-nota-fiscal)
9. [Iniciar automaticamente com o Windows](#9-iniciar-automaticamente-com-o-windows)
10. [Estrutura do projeto](#10-estrutura-do-projeto)
11. [Desenvolvimento e testes](#11-desenvolvimento-e-testes)
12. [Problemas comuns](#12-problemas-comuns)
13. [Decisões de projeto](#13-decisões-de-projeto)

---

## 1. Começando em 5 minutos

Requisito: **Python 3.11 ou mais novo** ([python.org](https://www.python.org/downloads/windows/) —
marque "Add Python to PATH" na instalação).

```powershell
git clone https://github.com/Tudolin/cadasmassas_pdv.git
cd cadasmassas_pdv

python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# Carrega os 137 produtos da balança no cache local.
# Depois deste passo o caixa JÁ VENDE, sem nenhuma credencial de nuvem.
.\.venv\Scripts\python scripts\importar_catalogo_local.py

.\.venv\Scripts\python run.py
```

A tela abre sozinha no navegador. Passe um produto no leitor e ele entra no
carrinho.

O Upstash (seções 2 a 4) é o que liga o PDV ao **precifier**, para o preço por
kg vir de lá e as vendas subirem para a nuvem. Não é necessário para vender.

---

## 2. Configurar o Upstash Redis (passo a passo)

O mesmo banco Redis é usado por dois sistemas:

| Quem | O que faz |
|---|---|
| **precifier** (Next.js, Vercel) | dono do preço — **escreve** o catálogo |
| **PDV** (este projeto) | **lê** o catálogo, **escreve** só `venda:*` |

### 2.1 Se o precifier já está na Vercel (caso normal)

O banco já existe — você só precisa copiar duas variáveis.

1. Abra [vercel.com](https://vercel.com) e entre no projeto do precifier.
2. **Settings → Environment Variables**.
3. Copie o valor de:
   - `UPSTASH_REDIS_REST_URL` (algo como `https://xxxx-00000.upstash.io`)
   - `UPSTASH_REDIS_REST_TOKEN` (uma sequência longa)

   > Dependendo de quando a integração foi feita, os nomes podem ser
   > `KV_REST_API_URL` / `KV_REST_API_TOKEN`. O PDV aceita os dois — e também
   > `REDIS_REST_API_URL` / `REDIS_REST_API_TOKEN`.

4. No PDV, crie o arquivo `.env`:

   ```powershell
   copy .env.example .env
   notepad .env
   ```

5. Preencha e salve:

   ```env
   UPSTASH_REDIS_REST_URL=https://xxxx-00000.upstash.io
   UPSTASH_REDIS_REST_TOKEN=AxxxAAIncDE...
   ```

   Sem espaços em volta do `=`, sem aspas, tudo numa linha só.

### 2.2 Se ainda não existe banco nenhum

1. Crie a conta em [console.upstash.com](https://console.upstash.com) (o plano
   gratuito atende com folga: o PDV faz cerca de 1 requisição por minuto).
2. **Create Database**:
   - **Name**: `casadasmassas`
   - **Type**: Regional
   - **Region**: `sa-east-1` (São Paulo) — a mais próxima, menor latência
   - **Eviction**: **desligado**. Importante: com eviction ligado o Redis pode
     apagar chaves sozinho quando a memória enche, e isso apagaria vendas.
3. Abra o banco criado → aba **REST API** → copie `UPSTASH_REDIS_REST_URL` e
   `UPSTASH_REDIS_REST_TOKEN` para o `.env` (passo 4 acima).
4. Ligue o precifier no mesmo banco: na Vercel, **Storage → Connect Database**,
   ou cadastre as mesmas duas variáveis manualmente e **faça um novo deploy**
   (variável nova só vale no deploy seguinte).

### ⚠️ Use o token certo

O Upstash oferece dois tokens. O painel mostra também um **"Read-Only Token"**.

**Não use o read-only.** O PDV grava as vendas em `venda:{uuid}`; com token de
leitura o checkout funciona (a venda fica no SQLite), mas nada sobe para a
nuvem e a fila cresce para sempre. O script da seção 3 detecta isso.

### 2.3 O que fica gravado no Redis

| Chave | Quem escreve | Conteúdo |
|---|---|---|
| `produto:{plu}` | precifier / `publicar_catalogo.py` | `{nome, preco_kg, categoria, ativo}` |
| `produto_ean:{codigo}` | precifier / `publicar_catalogo.py` | `{nome, preco_fixo, categoria, ativo}` |
| `catalogo:versao` | precifier / `publicar_catalogo.py` | inteiro incremental |
| `catalogo:snapshot` | `publicar_catalogo.py` | atalho: o catálogo todo num JSON |
| `venda:{uuid}` | **PDV** | `{itens, total, forma_pagamento, timestamp, ...}` |

O PDV compara `catalogo:versao` a cada 60 s e só baixa o catálogo quando o
número muda. Quando `catalogo:snapshot` existe, uma sincronização custa **uma**
requisição em vez de 1 + N.

---

## 3. Testar a conexão

Antes de abrir a loja numa máquina nova, rode:

```powershell
.\.venv\Scripts\python scripts\testar_redis.py
```

O script confere seis coisas, na ordem em que costumam dar errado:

```
==============================================================
  TESTE DE CONEXAO - PDV Casa das Massas <-> Upstash Redis
==============================================================

1/6  Variaveis de ambiente
  [ok]   URL:   https://xxxx-00000.upstash.io
  [ok]   Token: AxxxAA...cDE1 (108 caracteres)

2/6  O servidor responde? (PING)
  [ok]   PONG em 187 ms

3/6  Latencia (5 idas e voltas)
  [ok]   media 164 ms (min 151 / max 203)

4/6  Permissao de escrita (o PDV grava venda:*)
  [ok]   gravou, leu e apagou `pdv:teste:conexao`

5/6  Catalogo publicado
  [ok]   catalogo:versao = 3
  [ok]   `catalogo:snapshot` presente: 126 por peso + 11 por unidade

6/6  Sanidade dos produtos
  [ok]   o PDV entenderia 126 produto(s) por peso (126 ativo(s)) e
         11 por unidade (11 ativo(s))

==============================================================
  RESULTADO: TUDO PRONTO PARA VENDER
==============================================================
```

Opções:

```powershell
# lista produto por produto, com preço
.\.venv\Scripts\python scripts\testar_redis.py --detalhado

# não testa gravação (se você só tem o token read-only em mãos)
.\.venv\Scripts\python scripts\testar_redis.py --sem-escrita
```

O código de saída é `0` quando está tudo pronto e `1` quando há problema — dá
para usar em script de manutenção.

Quando algo falha, o script já diz o que fazer. Exemplo real de token errado:

```
2/6  O servidor responde? (PING)
  [FALHA] HTTP 401: {"error":"Unauthorized"}
         O token foi recusado. Copie de novo do painel do Upstash
         (Database -> REST API -> UPSTASH_REDIS_REST_TOKEN) e confira
         se nao ficou espaco ou quebra de linha no .env.
```

### Testar por fora, sem o PDV

Se quiser conferir na mão (o Upstash responde a HTTP puro):

```powershell
$url   = "https://xxxx-00000.upstash.io"
$token = "AxxxAAIncDE..."

# PING
Invoke-RestMethod -Uri "$url/ping" -Headers @{ Authorization = "Bearer $token" }
# -> @{result=PONG}

# Ver a versão do catálogo
Invoke-RestMethod -Uri "$url/get/catalogo:versao" -Headers @{ Authorization = "Bearer $token" }

# Contar as vendas já enviadas
Invoke-RestMethod -Uri "$url/dbsize" -Headers @{ Authorization = "Bearer $token" }
```

---

## 4. Publicar o catálogo

### Por que este passo existe

O combinado é que o precifier seja a fonte de verdade e escreva
`produto:{plu}`. **Hoje ele ainda não faz isso**: ele grava
`precifier:pratos` (uma lista) e o objeto `Prato` **não tem campo de PLU nem
de código de barras** — não existe como ligar um prato do precifier a uma
etiqueta da balança.

Quem sabe o PLU de cada produto é a balança, e essa informação está na tabela
`produtos` do `pdv_database.db` (153 produtos, versionado neste repositório).

O script abaixo faz a ponte: lê o SQLite da balança e publica no Redis exatamente
o formato que o PDV espera.

```powershell
# 1. Ver o que seria publicado, sem gravar nada
.\.venv\Scripts\python scripts\publicar_catalogo.py --simular

# 2. Publicar
.\.venv\Scripts\python scripts\publicar_catalogo.py

# 3. Publicar e apagar do Redis os produtos que saíram da balança
.\.venv\Scripts\python scripts\publicar_catalogo.py --limpar-antigos
```

Saída típica:

```
  126 produto(s) por peso (PLU da balanca)
   11 produto(s) por unidade (EAN)

  15 produto(s) NAO publicado(s):
    - 2006700 MOLHO BOL CONG.: sem preco (R$ 0.00) - cadastre o preco antes de vender
    ...

  catalogo:versao = 4 (era 3)
```

> **Atenção aos "não publicados".** Hoje 15 dos 153 produtos estão com preço
> `0,00` na balança. Eles **não aparecem no caixa** — a leitura vai dizer
> "PLU tal não está no catálogo". Precisam de preço na balança (ou no
> precifier) antes de poderem ser vendidos.

Depois de publicar, o PDV pega a versão nova em até 60 s, ou na hora se você
clicar em **Operação → Atualizar catálogo** na tela do caixa.

### Quando o precifier assumir

No dia em que o precifier ganhar um campo de PLU por prato, basta ele passar a
gravar as mesmas chaves (`produto:{plu}`, `catalogo:versao`). **O PDV não muda
uma linha** — ele já lê esse formato. O `publicar_catalogo.py` deixa de ser
necessário e vira só ferramenta de carga inicial.

---

## 5. Como o caixa funciona

O campo de código de barras está **sempre em foco**. O leitor USB se comporta
como teclado: digita o código e dá Enter. Não é preciso clicar em nada.

### Atalhos

| Tecla | Ação |
|---|---|
| `Enter` | lê o código que está no campo |
| `F2` | buscar produto por nome (etiqueta ilegível ou ausente) |
| `F4` | informar peso na mão |
| `F5` `F6` `F7` `F8` | dinheiro / débito / crédito / pix |
| `F9` | finalizar a venda |
| `Ctrl+Del` | zerar o carrinho |
| `Esc` | fecha janela aberta e devolve o foco ao campo |

Em pagamento em dinheiro, `Enter` no campo "valor recebido" já finaliza — o
troco aparece em verde enquanto você digita e em vermelho se ainda não cobre
o total.

### O que acontece ao finalizar

```
1. valida (forma de pagamento, carrinho não vazio, recebido >= total)
2. GRAVA no SQLite local, com fsync  ← daqui em diante a venda existe
3. enfileira a impressão do cupom     (thread separada)
4. enfileira a nota fiscal, se pedida (thread separada)
5. limpa o carrinho e responde
```

Os passos 3 e 4 **não** seguram a resposta. Impressora sem papel, internet
caída ou Upstash fora do ar não travam o caixa: a venda está gravada, o cupom
fica salvo em `dados\cupons\` e a fila sobe tudo quando a conexão voltar.

A barra de cima mostra o estado: versão do catálogo, quantas vendas estão
pendentes de envio e qual impressora está em uso.

### Vender sem internet

Funciona, sem nenhuma configuração:

- o catálogo já está na memória (carregado do cache SQLite no boot);
- a venda é gravada localmente;
- a fila tenta reenviar com espera crescente (15 s, 30 s, 1 min... até 15 min)
  e um pouco de aleatoriedade, para as vendas não voltarem todas juntas quando
  a internet retorna;
- `venda:{uuid}` faz o reenvio ser idempotente: a mesma venda reenviada
  sobrescreve a mesma chave, nunca duplica faturamento.

---

## 6. A etiqueta da balança

```
    2  0148  00  0957   4
    │  │     │   │      │
    │  │     │   │      └── pos 13    dígito verificador EAN-13 (mod10)
    │  │     │   └───────── pos  9-12 preço em centavos → R$ 9,57
    │  │     └───────────── pos  6-8  reservado
    │  └─────────────────── pos  2-5  PLU do produto → 148
    └────────────────────── pos  1    prefixo "2" = item pesável
```

O **peso não vem na etiqueta** — só o valor final. O PDV descobre o peso
dividindo o valor pelo preço por kg do catálogo (`R$ 9,57 ÷ R$ 31,90/kg =
300 g`), e usa isso no cupom e na nota fiscal.

### Regras de leitura

| Entrada | Resultado |
|---|---|
| 13 dígitos, começa com `2`, mod10 **válido** | item por peso, valor da etiqueta |
| 13 dígitos, começa com `2`, mod10 **inválido** | **recusado** — não entra no carrinho |
| `2000000` | etiqueta genérica: o PDV pede o produto e o peso |
| qualquer outro código | busca exata no catálogo (EAN de prateleira) |

O dígito verificador é conferido **antes de qualquer coisa**. Uma etiqueta de
balança corrompida carrega um valor em dinheiro errado — recusar é mais seguro
do que adivinhar. Códigos de prateleira **não** passam por essa checagem: quem
decide se existem é o catálogo, e exigir mod10 esconderia produtos cadastrados
com código interno.

### ⚠️ Largura do campo de preço: 4 ou 5 dígitos

Vale ler com atenção, porque é dinheiro.

A especificação escrita diz que o preço ocupa as **posições 9–12 (4 dígitos)**,
o que limita a etiqueta a **R$ 99,99**. O PDV que roda na loja hoje
(`app.py`, `decodificar_codigo_barras`) lê `codigo[-6:-1]`, ou seja as
**posições 8–12 (5 dígitos)**, permitindo até **R$ 999,99**.

Nas 6 etiquetas reais conferidas a mão, a posição 8 é sempre `0` — então as
duas leituras dão **exatamente o mesmo valor**, e há teste travando essa
equivalência. A diferença aparece só numa etiqueta de R$ 100,00 ou mais, e aí
a leitura de 4 dígitos **erra R$ 100 para baixo, em silêncio**.

Como o catálogo tem itens a R$ 61,90/kg (2 kg = R$ 123,80), o padrão do PDV é
**5 dígitos**. Para voltar ao comportamento da especificação:

```env
PDV_DIGITOS_PRECO=4
```

Nesse modo, se uma etiqueta vier com a posição 8 diferente de `0`, a tela mostra
um aviso amarelo dizendo quanto foi descartado, em vez de errar calado.

Se a balança for reconfigurada algum dia, confira este ponto primeiro.

---

## 7. Impressão do cupom

O cupom sai por **ESC/POS RAW** pelo spooler do Windows (`win32print`), em 48
colunas (bobina de 80 mm). Para 58 mm, use `PDV_LARGURA_CUPOM=32`.

Ver as impressoras que o Windows enxerga, com o PDV aberto:

```
http://127.0.0.1:8777/api/impressoras
```

Depois, no `.env`:

```env
PDV_IMPRESSORA=Nome Exato Da Impressora
```

Vazio = impressora padrão do Windows.

**Todo cupom é salvo em `dados\cupons\cupom-000123-*.txt`**, deu certo a
impressão ou não. Para reimprimir, use **Operação → Reimprimir** na tela,
informando o número do cupom.

### Três correções em relação ao cupom antigo

O `app.py` que roda hoje tem três defeitos que foram corrigidos aqui:

1. **Acentuação.** O código antigo faz `.encode('utf-8')`. Impressora térmica
   não entende UTF-8: "CARTÃO DÉBITO" sai como `CARTÃƒO DÃ‰BITO`. Agora o PDV
   envia `ESC t 3` (página de código 860, português) e codifica em `cp860`.
2. **Ordem do corte.** O antigo manda cortar (`GS V A`) e **depois** os `\n`
   de avanço — o papel é cortado antes de o texto passar da lâmina, e o avanço
   sai no cupom seguinte. Agora o avanço vem antes do corte.
3. **Linhas maiores que a bobina.** A linha de item do cupom antigo somava 52
   caracteres numa bobina de 48, e a impressora quebrava sozinha no meio do
   valor. Agora o layout respeita a largura configurada.

---

## 8. Nota fiscal

**Desligada por padrão**, e vale explicar por quê.

O pedido era reaproveitar a lógica de `emisssao_nf.py` do repo `pdv-python`.
Ao abrir aquele arquivo:

- não é integração com API de NFC-e/SAT — é **Selenium dirigindo o Chrome** no
  emissor web da IOB;
- o login está com usuário e senha **vazios** (`send_keys("")`) e para num
  `input()` de terminal esperando alguém resolver o captcha;
- o fluxo está **incompleto**: preenche CPF, nome e quantidade e termina ali —
  nunca escolhe forma de pagamento nem envia a nota;
- os campos são achados por XPath com id gerado
  (`//*[@id="adf61b55-ecca-064d-b7b7-3f6c45eb77ea"]`), que muda a cada deploy
  do site da IOB.

Ou seja: **aquele script nunca emitiu uma nota de ponta a ponta**, e não há
como testá-lo daqui (precisa da credencial da loja e de um captcha humano).
Além disso, Chrome + chromedriver custam algumas centenas de MB de RAM — o
oposto do requisito de baixo consumo no notebook compartilhado.

O que foi entregue:

- a NF **nunca** roda no caminho do checkout — é enfileirada no SQLite
  (tabela `nota_fiscal`) e processada por uma thread, com backoff;
- o emissor é um **adaptador plugável** (`AdaptadorNF`, em
  `pdv/nota_fiscal.py`);
- o adaptador padrão (`arquivo`) grava o pedido em `dados\notas\*.json` — não
  transmite nada, e serve de formato de referência para o emissor definitivo;
- o adaptador `iob` porta o script original e **falha com mensagem explícita**
  no ponto do captcha, em vez de pendurar o processo para sempre.

```env
PDV_NF_HABILITADA=1
PDV_NF_TIPO=arquivo
```

**Recomendação:** trocar por uma API fiscal de verdade (Focus NFe, Nuvem
Fiscal, PlugNotas, eNotas). O contrato `AdaptadorNF` foi desenhado para essa
troca ser um arquivo novo, sem tocar no resto — implemente
`emitir(pedido) -> ResultadoNF` e registre em `construir_adaptador`.

---

## 9. Iniciar automaticamente com o Windows

Objetivo: o dono liga o notebook, faz login, e o caixa **já está na tela** —
sem abrir terminal, sem digitar comando, sem saber que existe Python ali.

Há três formas. A **A** é a recomendada e é a única que também atualiza o
código sozinha.

| | Atualiza (`git pull`) | Instala dep. nova | Sobe se travar | Sem piscar janela | Dificuldade |
|---|---|---|---|---|---|
| **A. Agendador (script)** | sim | sim | sim (3 tentativas) | **sim** | 1 comando |
| **B. Agendador (janela)** | sim | sim | sim | sim, se seguir o passo 5 | ~10 cliques |
| **C. Pasta Inicializar** | sim | sim | não | sim | copiar 1 atalho |

As três chamam o mesmo `iniciar_pdv.ps1`, então todas atualizam o código —
o que muda é o que o Windows faz se o PDV cair, e quanto de terminal você
precisa encarar.

#### Início 100% silencioso (padrão)

Nenhuma janela pisca na tela do operador. São duas peças:

- a tarefa chama **`wscript.exe`** com o [iniciar_pdv_silencioso.vbs](scripts/iniciar_pdv_silencioso.vbs),
  que roda o PowerShell com janela oculta. `powershell.exe -WindowStyle
  Hidden` **não** basta: o Windows cria o console e só depois esconde, e isso
  aparece como um retângulo azul piscando;
- o servidor sobe com **`pythonw.exe`** (o Python sem console) em vez de
  `python.exe`.

> **Em troca, não existe janela onde um erro apareça.** Por isso o script
> grava tudo em `dados\inicializacao.log` e a saída do servidor em
> `dados\servidor.err.log` — e, quando o PDV não sobe, ele **copia o
> traceback do Python para dentro do log de inicialização**. Esses dois
> arquivos são o lugar para olhar quando o caixa não abrir.
>
> Para depurar com o console visível:
> `.\scripts\instalar_tarefa.ps1 -Kiosk -MostrarConsole`

---

### 9.1 Forma A — Agendador de Tarefas pelo script (recomendada)

Abra o **PowerShell** na pasta do projeto e rode:

```powershell
cd C:\caminho\para\cadasmassas_pdv
.\scripts\instalar_tarefa.ps1 -Kiosk
```

> Se aparecer *"não pode ser carregado porque a execução de scripts foi
> desabilitada"*, rode assim (vale só para esta chamada, não muda a política
> da máquina):
>
> ```powershell
> powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_tarefa.ps1 -Kiosk
> ```

Saída esperada:

```
Tarefa 'PDV Casa das Massas' cadastrada.

Resumo:
  Gatilho .... logon de Dono (atraso de 20s)
  Comando .... powershell.exe -NoProfile -ExecutionPolicy Bypass -File "...\iniciar_pdv.ps1" -Kiosk
  Pasta ...... C:\caminho\para\cadasmassas_pdv
  Kiosk ...... sim
```

**Não precisa de administrador.** A tarefa roda com a conta do próprio dono,
sem elevação — de propósito: tarefa elevada no logon dispara o UAC, e um
prompt de UAC toda manhã é exatamente o tipo de coisa que faz o operador
começar a clicar em "não".

#### Opções

```powershell
.\scripts\instalar_tarefa.ps1 -Kiosk                      # tela cheia (recomendado)
.\scripts\instalar_tarefa.ps1                             # navegador normal, com abas
.\scripts\instalar_tarefa.ps1 -Janela                     # janela nativa (pip install pywebview)
.\scripts\instalar_tarefa.ps1 -Kiosk -AtrasoSegundos 45   # espera mais depois do logon
.\scripts\instalar_tarefa.ps1 -Kiosk -MostrarConsole      # console VISIVEL, para depurar
.\scripts\instalar_tarefa.ps1 -Remover                    # desinstala
```

O **atraso** (20 s por padrão) existe para o PDV não competir com OneDrive,
antivírus e o resto do que o Windows carrega no logon. Se o notebook for
lento, `-AtrasoSegundos 45` deixa a abertura mais confiável.

#### Testar sem reiniciar

```powershell
Start-ScheduledTask -TaskName 'PDV Casa das Massas'
```

Espere uns 5 segundos e confirme:

```powershell
Get-ScheduledTaskInfo -TaskName 'PDV Casa das Massas' |
    Select-Object LastRunTime, LastTaskResult
```

`LastTaskResult : 0` significa que rodou sem erro. E o log conta o que
aconteceu passo a passo:

```powershell
Get-Content dados\inicializacao.log -Tail 15
```

```
15:01:24 INFO  ================ inicializacao do PDV ================
15:01:24 INFO  raiz: C:\...\cadasmassas_pdv | porta: 8777
15:01:24 INFO  consultando o GitHub (git fetch)...
15:01:25 INFO  ja esta na ultima versao (995b6fe)
15:01:25 INFO  dependencias sem mudanca; pulando o pip
15:01:25 INFO  iniciando o PDV...
15:01:28 INFO  PDV respondendo
15:01:28 INFO  abrindo em kiosk: chrome.exe
15:01:28 INFO  inicializacao concluida
```

---

### 9.2 Forma B — Agendador de Tarefas pela janela

Para quem prefere clicar, ou para conferir o que o script fez.

1. Tecla **Windows**, digite `Agendador de Tarefas`, abra.
2. No menu à direita: **Criar Tarefa...** (não "Criar Tarefa Básica" — a
   básica não tem as opções de bateria e reinício).
3. Aba **Geral**:
   - **Nome**: `PDV Casa das Massas`
   - Marque **Executar somente quando o usuário estiver conectado**
   - **Não** marque "Executar com privilégios mais altos"
   - **Configurar para**: Windows 10 (serve para o 11)
4. Aba **Disparadores** → **Novo...**:
   - **Iniciar a tarefa**: `Ao fazer logon`
   - **Usuário específico**: a conta do dono
   - Marque **Atrasar tarefa por** e escolha/digite `20 segundos`
   - **OK**
5. Aba **Ações** → **Novo...**:
   - **Ação**: Iniciar um programa
   - **Programa/script**: `wscript.exe`
   - **Adicione argumentos** (numa linha só, com as aspas):
     ```
     "C:\caminho\para\cadasmassas_pdv\scripts\iniciar_pdv_silencioso.vbs" -Kiosk
     ```
   - **Iniciar em**: `C:\caminho\para\cadasmassas_pdv`
   - **OK**

   > Usar `wscript.exe` com o `.vbs` é o que evita a janela piscando. Se
   > preferir ver o console para depurar, troque por `powershell.exe` com os
   > argumentos
   > `-NoProfile -ExecutionPolicy Bypass -File "...\iniciar_pdv.ps1" -Kiosk`.
6. Aba **Condições**:
   - **Desmarque** "Iniciar a tarefa somente se o computador estiver na
     energia CA" — senão o caixa não abre com o notebook na bateria.
7. Aba **Configurações**:
   - Marque **Executar a tarefa assim que possível após uma inicialização
     agendada perdida**
   - Marque **Se a tarefa falhar, reiniciar a cada**: `1 minuto`, **até**:
     `3 vezes`
   - **Interromper a tarefa se for executada por mais de**: **desmarque**
     (o PDV fica de pé o dia inteiro; com essa opção marcada o Windows
     mataria o caixa em plena tarde)
8. **OK**. Botão direito na tarefa → **Executar** para testar.

---

### 9.3 Forma C — pasta Inicializar (a mais simples)

Não precisa de Agendador nenhum. Em troca, o Windows não reinicia o PDV se
ele cair.

1. **Windows + R**, digite `shell:startup`, Enter. Abre a pasta de
   inicialização do usuário.
2. Botão direito na pasta → **Novo → Atalho**.
3. Em **Local do item**, cole (ajustando o caminho):

   ```
   wscript.exe "C:\caminho\para\cadasmassas_pdv\scripts\iniciar_pdv_silencioso.vbs" -Kiosk
   ```

4. **Avançar**, nomeie `PDV Casa das Massas`, **Concluir**.
5. Botão direito no atalho → **Propriedades** → em **Iniciar em** coloque
   `C:\caminho\para\cadasmassas_pdv` → **OK**.

O `wscript.exe` é o que evita a janela azul do PowerShell piscando na cara do
operador. Para testar, dê duplo clique no atalho.

---

### 9.4 Importante: "no logon" não é "ao ligar"

As três formas disparam **quando alguém faz login**, não quando o notebook
liga. Se a máquina liga e para na tela de senha, o caixa **não abre** até
alguém entrar.

Isso é intencional: o PDV é uma tela para uma pessoa olhar, e antes do login
não existe sessão gráfica onde mostrar nada. Um serviço do Windows subiria
antes, mas rodaria sem tela — e aí ninguém vende.

Se o dono quiser o notebook abrindo o caixa sozinho ao ligar, o caminho é
configurar **logon automático do Windows** (`netplwiz`, ou a chave
`AutoAdminLogon`) e deixar a tarefa como está. Vale lembrar o custo: com
logon automático, quem abrir o notebook está dentro do Windows sem senha.
Numa máquina que fica no balcão e também é usada para outras coisas, essa é
uma decisão do dono — não uma configuração para deixar ligada por padrão.

---

### 9.5 O que o script faz a cada logon

`scripts\iniciar_pdv.ps1`:

1. **Já está rodando?** Se a porta responde, só abre a tela e sai — a tarefa
   disparando duas vezes não sobe dois servidores nem duplica venda.
2. **`git fetch`** e, se houver commit novo na `main`, `git pull --ff-only`.
3. **Cria o `.venv`** se não existir.
4. **`pip install`** apenas se o `requirements.txt` mudou (compara SHA256
   guardado em `dados\requirements.hash`).
5. **Importa o catálogo** para o cache local, se for a primeira execução.
6. **Sobe o PDV**, espera a porta responder e só então abre a tela.

Tudo que envolve rede falha para o lado seguro: se o GitHub não responder, o
PDV abre com o código que já está no disco. **A loja abrir no horário vale
mais do que estar na última versão.** O git roda com
`GIT_HTTP_LOW_SPEED_LIMIT`/`TIME` (desiste depois de 20 s parado) e
`GIT_TERMINAL_PROMPT=0`, para um repositório privado nunca abrir um prompt de
senha invisível que penduraria a tarefa para sempre.

O script **não** cancela o `pull` só porque há arquivo alterado localmente —
isso incluiria sempre `pdv_database.db` enquanto o PDV antigo (`app.py`)
estiver em uso, já que ele grava cada venda nesse arquivo versionado, e o
`pull` nunca rodaria na loja. Em vez disso ele deixa o próprio `git pull
--ff-only` decidir: se o commit remoto não mexe no arquivo alterado, o pull
segue normalmente; se mexe, o `git` recusa o merge (para não sobrescrever o
dado local) e o script registra o aviso no log, seguindo com o código que já
está no disco.

---

### 9.6 Ciclo de atualização no dia a dia

```
você:  git push origin main
         ↓
loja:  próximo logon → git pull → pip (se preciso) → PDV atualizado
```

Para aplicar sem esperar o próximo logon, na loja:

```powershell
Get-NetTCPConnection -LocalPort 8777 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
.\scripts\iniciar_pdv.ps1 -Kiosk
```

(Usar a porta para achar o processo, e não `Stop-Process -Name python`, evita
matar outro Python que o dono esteja usando no mesmo notebook.)

---

### 9.7 Modo kiosk: o que o operador vê

Com `-Kiosk`, o Chrome (ou Edge) abre em tela cheia, sem barra de endereço e
sem abas — o operador não navega para fora por acidente. O perfil é
**separado** (`dados\perfil-navegador`), então não mistura com a navegação
pessoal do dono nem herda extensão nenhuma.

- **Sair do kiosk**: `Alt + F4`
- **Voltar ao caixa depois de fechar**: duplo clique no atalho, ou
  `Start-ScheduledTask -TaskName 'PDV Casa das Massas'`
- Se Chrome e Edge não estiverem instalados, o script cai no navegador padrão
  e registra um aviso no log.

---

### 9.8 Desativar ou remover

```powershell
# Remover a tarefa
.\scripts\instalar_tarefa.ps1 -Remover

# Ou apenas desligar, mantendo cadastrada
Disable-ScheduledTask -TaskName 'PDV Casa das Massas'
Enable-ScheduledTask  -TaskName 'PDV Casa das Massas'
```

Na forma C, apague o atalho de `shell:startup`.

---

### 9.9 Não abriu no logon — o que olhar

**1. A tarefa rodou?**

```powershell
Get-ScheduledTaskInfo -TaskName 'PDV Casa das Massas' |
    Select-Object LastRunTime, LastTaskResult, NumberOfMissedRuns
```

- `LastRunTime` vazio → o gatilho não disparou. Confira, na aba
  **Disparadores**, se o usuário do gatilho é a conta que realmente faz
  login.
- `LastTaskResult : 0` → a tarefa rodou bem; o problema é depois dela, siga
  para o passo 2.
- `LastTaskResult : 267011` → nunca executou ainda.
- `LastTaskResult : 2147942401` ou `0x1` → o comando não rodou. Quase sempre
  caminho errado nos argumentos, ou faltou as aspas em volta do `-File`.

**2. O que o log diz?**

```powershell
Get-Content dados\inicializacao.log -Tail 40
```

O log nomeia o passo em que parou. Quando o servidor não sobe, ele **copia o
traceback do Python para dentro deste log** — não é preciso caçar em outro
arquivo:

```
15:42:56 INFO  processo iniciado (PID 8060)
15:42:56 ERRO  o PDV encerrou sozinho (codigo 1)
15:42:56 ERRO  --- ultimas linhas de servidor.err.log ---
15:42:56 ERRO      Traceback (most recent call last):
15:42:56 ERRO        File "...\run.py", line 25, in <module>
15:42:56 ERRO      ModuleNotFoundError: No module named 'flask'
15:42:56 ERRO  Detalhes completos em: ...\dados\servidor.err.log
```

Mensagens mais comuns:

- `nao achei ...\run.py` → **o repositório não tem o PDV novo.** Acontece
  quando o commit com a pasta `pdv/` e o `run.py` não foi enviado para a
  `main`. Confira com `git log --oneline -3` e `dir run.py`.
- `Python nao encontrado no PATH` → instale o Python 3.11+ marcando
  **"Add Python to PATH"**, ou crie o `.venv` uma vez à mão.
- `o PDV encerrou sozinho` → o traceback logo abaixo diz o motivo.
- `o PDV nao respondeu em 15s` → o processo está vivo mas não abriu a porta;
  veja `dados\servidor.err.log` e `dados\pdv.log`.
- `o local esta A FRENTE do GitHub` → há commit na loja que nunca subiu. O
  PDV abre normalmente com o código local.
- `historico divergente` → o repositório da loja e o do GitHub seguiram
  caminhos diferentes. O PDV abre com o código local; resolva à mão.
- `ha alteracoes locais nao comitadas; pull cancelado` → alguém editou
  arquivo na loja. O PDV abre com o código local; resolva quando puder.

**3. O log para numa linha e não continua?**

Se o log termina em `ja esta na ultima versao` (ou em qualquer linha) e nada
vem depois, o script morreu sem conseguir registrar o motivo. A partir da
versão atual isso não deveria mais acontecer: existe um `trap` que registra
`ERRO NAO TRATADO` com arquivo e linha antes de encerrar. Se você vê o log
parando sem esse `ERRO NAO TRATADO`, o script é antigo — atualize.

A causa mais comum era **venv sem as dependências**:

```powershell
.\.venv\Scripts\pip install -r requirements.txt
```

> **Cuidado ao copiar a pasta do projeto de uma máquina para outra.** Se
> `dados\` vier na cópia, ela traz o `requirements.hash` da máquina de origem
> — e o script conclui "dependências em dia" num venv que está vazio. Traz
> também o `pdv.db`, ou seja **o histórico de vendas da outra máquina**, que
> entraria no relatório de faturamento como se fosse da loja.
>
> Ao copiar o projeto, apague `dados\` e deixe o script recriar:
>
> ```powershell
> Remove-Item -Recurse -Force dados
> .\scripts\iniciar_pdv.ps1 -SemAtualizar
> ```

**4. Nada nos dois logs?**

Então o PowerShell nem chegou a executar o script. Rode o comando exato da
tarefa a mão, numa janela normal, para ver o erro na tela:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\caminho\para\cadasmassas_pdv\scripts\iniciar_pdv.ps1" -SemAtualizar
```

**5. Abriu o navegador mas a página não carrega**

O servidor não subiu. Veja `dados\pdv.log`. Se disser que a porta está em
uso, outro programa pegou a 8777 — troque `PDV_PORTA` no `.env` (o script lê
o `.env` e usa a mesma porta para esperar e para abrir a tela).

## 10. Estrutura do projeto

```
pdv/
  codigo_barras.py   ← parser da etiqueta. PURO: sem I/O, sem dependência
  dinheiro.py        ← centavos inteiros + formato brasileiro
  carrinho.py        ← regras do carrinho (Decimal/int, nada de float)
  catalogo.py        ← cache em memória + sincronização em segundo plano
  upstash.py         ← cliente REST do Redis (urllib, sem `requests`)
  db.py              ← esquema SQLite (catálogo + fila + NF)
  importador.py      ← lê a tabela `produtos` da balança
  fila.py            ← fila de vendas offline-first, com backoff
  recibo.py          ← monta o cupom em texto (puro, testável)
  impressao.py       ← ESC/POS via win32print (import tardio)
  nota_fiscal.py     ← adaptadores de NF, enfileirados
  config.py          ← variáveis de ambiente + leitor de .env
  web.py             ← rotas Flask
  templates/caixa.html
  static/caixa.css, caixa.js
scripts/
  testar_redis.py            ← diagnóstico da conexão (seção 3)
  publicar_catalogo.py       ← SQLite da balança → Redis
  importar_catalogo_local.py ← SQLite da balança → cache local
  iniciar_pdv.ps1            ← atualiza e inicia (chamado no logon)
  iniciar_pdv_silencioso.vbs ← lançador sem janela (wscript), usado pela tarefa
  instalar_tarefa.ps1        ← cadastra no Agendador de Tarefas
tests/                       ← 137 testes
run.py                       ← entrada: waitress + abre a tela
app.py                       ← PDV ANTIGO (Tkinter), mantido como plano B
```

### Onde ficam os dados da loja

```
dados\
  pdv.db                  banco local: catálogo em cache + fila de vendas
  pdv.log                 log do PDV
  inicializacao.log       log do script de logon (seção 9)
  servidor.err.log        stderr do servidor — onde o traceback aparece
  servidor.out.log        stdout do servidor
  requirements.hash       controle do "só instalar dependência se mudou"
  cupons\                 cópia em texto de todo cupom emitido
  notas\                  pedidos de nota fiscal (adaptador "arquivo")
  perfil-navegador\       perfil do Chrome em modo kiosk
```

Nada disso vai para o Git (`dados/` está no `.gitignore`) — é dado da loja,
não código.

> **Faça backup do `dados\pdv.db`.** É o arquivo que guarda o histórico de
> vendas e a fila do que ainda não subiu para a nuvem. Um `copy` para pendrive
> ou OneDrive uma vez por semana resolve.

### O PDV antigo continua no repositório

`app.py` (a interface Tkinter, com `dist\app.exe`) **não foi removido**. Ele é
o que a loja usa hoje e serve de plano B até o caixa novo ser validado no
balcão. As dependências dele estão em `requirements-legado.txt`:

```powershell
python -m venv .venv-legado
.\.venv-legado\Scripts\pip install -r requirements-legado.txt
.\.venv-legado\Scripts\python app.py
```

---

## 11. Desenvolvimento e testes

```powershell
.\.venv\Scripts\pip install -r requirements-dev.txt

.\.venv\Scripts\python -m pytest -q                    # todos
.\.venv\Scripts\python -m pytest tests\test_codigo_barras.py -v   # só o parser
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format .
```

Nenhum teste toca a rede nem a impressora — o que também prova que o PDV
funciona offline.

Cobertura por arquivo:

| Arquivo | O que garante |
|---|---|
| `test_codigo_barras.py` | as 6 etiquetas reais, mod10 inválido, código de prateleira, 4 vs 5 dígitos, ruído do leitor |
| `test_carrinho.py` | subtotal vindo da etiqueta, agrupamento de EAN, troco, ausência de erro de float |
| `test_caixa.py` | fluxo HTTP completo: ler → carrinho → checkout → cupom → persistência |
| `test_importador.py` | separação peso/unidade, limpeza de nome, categorias |
| `test_recibo.py` | layout do cupom dentro da largura |

Para subir o servidor em desenvolvimento:

```powershell
.\.venv\Scripts\python run.py --sem-navegador --log DEBUG
```

---

## 12. Problemas comuns

### O leitor digita o código na tela mas nada acontece

O foco saiu do campo. Aperte `Esc` — o PDV também devolve o foco sozinho ao
clicar em área neutra e ao voltar para a janela. Se persistir, confirme que o
leitor está configurado para enviar **Enter** (CR/LF) no fim da leitura.

### "PLU 148 não está no catálogo"

O catálogo está vazio ou desatualizado. Nesta ordem:

```powershell
.\.venv\Scripts\python scripts\testar_redis.py            # o Redis tem produtos?
.\.venv\Scripts\python scripts\publicar_catalogo.py       # publica
.\.venv\Scripts\python scripts\importar_catalogo_local.py # ou só local
```

Se o produto existe na balança mas não no PDV, veja se ele não caiu na lista
de **"não publicados"** por estar com preço `0,00`.

### A barra mostra "fila N pendente(s)" e o número só cresce

As vendas estão gravadas (não há risco de perda), mas não sobem. Quase sempre é
o **token read-only**:

```powershell
.\.venv\Scripts\python scripts\testar_redis.py
```

Olhe o passo **4/6 (permissão de escrita)**. Depois de corrigir o `.env`,
reinicie o PDV e clique em **Operação → Enviar vendas pendentes**.

### O cupom sai com caracteres estranhos nos acentos

Página de código da impressora. Tente, na ordem:

```env
PDV_CODEPAGE_CUPOM=cp860   # português (padrão)
PDV_CODEPAGE_CUPOM=cp850   # multilíngue
PDV_CODEPAGE_CUPOM=cp437   # EUA — perde os acentos, mas não embaralha
```

### O cupom não imprime

O cupom **está** salvo em `dados\cupons\`, então nada foi perdido. Confira o
indicador "impressora" na barra (ele mostra o erro ao passar o mouse) e:

```
http://127.0.0.1:8777/api/impressoras
```

Copie o nome **exato** para `PDV_IMPRESSORA` no `.env`.

### "porta 8777 já está em uso"

O PDV já está rodando — a mensagem é esperada e ele apenas abre a tela. Se não
estiver, algum outro programa pegou a porta: troque `PDV_PORTA` no `.env`.

### O PDV não abriu sozinho no logon

Primeiro comando a rodar:

```powershell
Get-ScheduledTaskInfo -TaskName 'PDV Casa das Massas' |
    Select-Object LastRunTime, LastTaskResult
Get-Content dados\inicializacao.log -Tail 40
```

O log nomeia o passo em que parou. A [seção 9.9](#99-não-abriu-no-logon--o-que-olhar)
traz o roteiro completo, incluindo o que cada `LastTaskResult` significa.

Vale conferir também o mais simples: a tarefa dispara **no logon**, não ao
ligar o notebook. Se a máquina está parada na tela de senha, nada roda ainda
(ver [9.4](#94-importante-no-logon-não-é-ao-ligar)).

### O caixa está lento

Verifique se não é a rede: **nenhuma** leitura de código deveria esperar
resposta de rede. Se a leitura está lenta, é bug — abra o log em `DEBUG`. A
sincronização do catálogo e o envio de vendas rodam em threads separadas e não
podem afetar a digitação.

---

## 13. Decisões de projeto

**Por que Python, e não Go/Rust/Node.** Foi avaliado — o pedido deixava a
escolha aberta por desempenho. No notebook da loja só existe **Python 3.13**
instalado (sem Node, sem Go), e o código a reaproveitar (impressão ESC/POS,
lógica de NF, 3 mil linhas do PDV atual) é todo Python. Um binário Go
economizaria uns 40 MB de RAM e custaria reescrever tudo, mais um toolchain a
manter numa máquina que não é servidor. O gargalo real do PDV é a etiqueta
sendo digitada pelo leitor, não a CPU. O boot medido é de **2,1 s** até a tela
pronta.

**Por que o dinheiro é `int` de centavos.** Total em `float` acumula erro
(`0,1 + 0,2 = 0,30000000000000004`). Centavos inteiros atravessam o sistema do
código de barras até o SQLite; `Decimal` aparece só na fronteira, quando o
operador digita um valor. Há teste somando 100 itens de 10 centavos e exigindo
exatamente R$ 10,00.

**Por que o subtotal do item pesado vem da etiqueta.** Recalcular
`preço_kg × peso` daria diferença de centavo em relação ao que está impresso —
e discussão no balcão. A etiqueta manda; o peso é derivado dela.

**Por que a tela não calcula nada.** Cada resposta traz o carrinho inteiro em
JSON e o navegador só desenha. Elimina a classe de bug mais chata de PDV: o
total da tela não bater com o total gravado.

**Por que gravar a venda antes de imprimir.** Gravação é o único passo cujo
fracasso significa perder dinheiro. Se ela falhar, o carrinho é **mantido** e o
operador tenta de novo. Assim nunca existe cupom impresso sem venda gravada.

**Por que `synchronous = FULL` no SQLite.** Um fsync por venda (poucos
milissegundos) em troca de não perder venda em queda de energia. Barato, e o
caixa não faz volume que justifique economizar aqui.

**Por que urllib em vez de `requests`.** A API REST do Upstash é um POST com um
array JSON. `urllib` da stdlib resolve, e cada dependência a menos é tempo de
boot e memória a menos num notebook compartilhado. Pela mesma razão não há
`python-dotenv` (15 linhas em `config.py`), nem SQLAlchemy, nem pandas.

**Por que o parser é um módulo puro.** `codigo_barras.py` não importa nada
além da stdlib e não faz I/O, então dá para cobrir 100% dos caminhos de
dinheiro com teste rápido. O CI tem um job que roda **só** esse arquivo, com
apenas o pytest instalado — se alguém fizer o parser importar Flask, o CI
quebra.

**Por que o servidor escuta só em 127.0.0.1.** O caixa é local. Expor na rede
da loja só criaria superfície de ataque sem nenhum ganho.

---

## Pendências conhecidas

Coisas que ficaram fora do escopo e valem registro:

1. **O precifier não publica PLU.** Enquanto isso, o
   `publicar_catalogo.py` faz a ponte a partir do SQLite da balança
   (seção 4). O ideal é o precifier ganhar um campo de código de balança por
   prato.
2. **15 produtos estão com preço `0,00`** na balança e não podem ser vendidos
   até serem precificados.
3. **Nota fiscal não emite de verdade** — ver seção 8. Precisa de uma API
   fiscal.
4. **Credencial exposta.** O arquivo `.env.example` do repo `precifier`
   contém uma URL e um token reais do Upstash em texto puro
   (bloco `DESTINO_URL` / `DESTINO_TOKEN`). Se esse arquivo está no
   GitHub, esse token deve ser considerado **vazado**: gere um novo no painel
   do Upstash e limpe o arquivo. Não tem relação com este PDV, mas é o mesmo
   banco.
