"""
Impressao termica ESC/POS no Windows, via spooler RAW (win32print).

Este modulo importa `win32print` DE FORMA TARDIA, dentro da funcao. Dois
motivos:

* os testes e o CI (Linux) importam `pdv.impressao` sem ter pywin32;
* o boot do PDV nao paga o custo de carregar pywin32 quando ninguem
  imprimiu nada ainda.

Correcoes em relacao ao codigo que roda hoje na loja (`app.py`,
`imprimir_windows_termica`):

1. **Codepage.** O cupom antigo faz `.encode('utf-8')`. Impressora termica
   nao entende UTF-8: "CARTÃO DÉBITO" sai como "CARTÃƒO DÃ‰BITO". Aqui
   mandamos `ESC t` selecionando a pagina de codigo 860 (portugues) e
   codificamos em cp860, com transliteracao para ASCII no que nao existir.

2. **Ordem do corte.** O cupom antigo manda `GS V A` (cortar) e SO DEPOIS
   os `\\n` de avanco -- ou seja, corta antes de o texto passar da lamina e
   o avanco sai no cupom seguinte. Aqui o avanco vem antes do corte.

3. **Alinhamento.** O antigo decidia centralizar procurando a substring
   "CASA DAS MASSAS" na linha. Aqui o texto ja vem centralizado por conta da
   largura conhecida (ver `recibo.py`) e a impressora fica sempre alinhada a
   esquerda -- o resultado nao depende mais do conteudo do texto.

A impressao NUNCA acontece na thread que responde ao caixa: quem chama e o
`GerenciadorImpressao`, que tem a sua propria worker.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = [
    "ErroImpressao",
    "GerenciadorImpressao",
    "impressora_padrao",
    "imprimir_linhas",
    "listar_impressoras",
    "salvar_cupom",
]

log = logging.getLogger(__name__)

# ---- comandos ESC/POS ----------------------------------------------------
_INICIALIZAR = b"\x1b\x40"  # ESC @  - reset
_CODEPAGE_860 = b"\x1b\x74\x03"  # ESC t 3 - pagina de codigo portugues
_ALINHAR_ESQUERDA = b"\x1b\x61\x00"  # ESC a 0
_AVANCO_FINAL = b"\n" * 4  # tira o cupom de baixo da lamina
_CORTAR_PARCIAL = b"\x1d\x56\x42\x00"  # GS V B 0 - corta com avanco

#: Acentos que o cp860 nao tem: caem para ASCII em vez de estourar.
_TRANSLITERACAO = str.maketrans(
    {
        "–": "-",
        "—": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
        " ": " ",
        "€": "EUR",
        "•": "*",
    }
)


class ErroImpressao(RuntimeError):
    """Nao deu para imprimir. O cupom ainda foi salvo em arquivo."""


def _codificar(linhas: list[str], codepage: str) -> bytes:
    texto = "\n".join(linha.translate(_TRANSLITERACAO) for linha in linhas) + "\n"
    # `replace` e proposital: um caractere exotico nao pode impedir a venda
    # de sair impressa.
    return texto.encode(codepage, errors="replace")


def listar_impressoras() -> list[str]:
    """Nomes das impressoras instaladas. Lista vazia fora do Windows."""
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError:
        return []

    return [
        impressora[2]
        for impressora in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        )
    ]


def impressora_padrao() -> str | None:
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


def imprimir_linhas(
    linhas: list[str],
    *,
    impressora: str = "",
    codepage: str = "cp860",
    titulo: str = "Cupom PDV",
) -> str:
    """
    Manda o cupom para a impressora em modo RAW.

    Devolve o nome da impressora usada. Levanta `ErroImpressao` em qualquer
    falha -- inclusive "pywin32 nao instalado" e "nenhuma impressora".
    """
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError as erro:
        raise ErroImpressao(
            "pywin32 nao esta instalado; impressao indisponivel."
        ) from erro

    nome = impressora or (impressora_padrao() or "")
    if not nome:
        raise ErroImpressao("Nenhuma impressora configurada no Windows.")

    dados = (
        _INICIALIZAR
        + _CODEPAGE_860
        + _ALINHAR_ESQUERDA
        + _codificar(linhas, codepage)
        + _AVANCO_FINAL
        + _CORTAR_PARCIAL
    )

    try:
        manipulador = win32print.OpenPrinter(nome)
    except Exception as erro:
        raise ErroImpressao(f"Nao foi possivel abrir '{nome}': {erro}") from erro

    try:
        trabalho = win32print.StartDocPrinter(manipulador, 1, (titulo, None, "RAW"))
        try:
            win32print.StartPagePrinter(manipulador)
            win32print.WritePrinter(manipulador, dados)
            win32print.EndPagePrinter(manipulador)
        finally:
            win32print.EndDocPrinter(manipulador)
        log.info("cupom enviado para '%s' (job %s)", nome, trabalho)
        return nome
    except Exception as erro:
        raise ErroImpressao(f"Falha ao imprimir em '{nome}': {erro}") from erro
    finally:
        win32print.ClosePrinter(manipulador)


def salvar_cupom(linhas: list[str], pasta: Path, cupom: int) -> Path:
    """
    Salva o cupom em texto. Roda SEMPRE, deu certo a impressao ou nao --
    e a rede de seguranca para reimprimir depois.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    caminho = pasta / f"cupom-{cupom:06d}-{marca}.txt"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


# --------------------------------------------------------------------------
# Worker de impressao
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Trabalho:
    linhas: list[str]
    cupom: int


class GerenciadorImpressao:
    """
    Fila de impressao em thread separada.

    O checkout enfileira e responde na hora. Impressora sem papel, offline
    ou lenta nao trava o caixa -- so aparece em `ultimo_erro`, e o cupom
    fica salvo em arquivo de qualquer forma.
    """

    def __init__(
        self,
        *,
        pasta_cupons: Path,
        impressora: str = "",
        codepage: str = "cp860",
        habilitado: bool = True,
    ) -> None:
        self._pasta = pasta_cupons
        self._impressora = impressora
        self._codepage = codepage
        self._habilitado = habilitado
        self._fila: queue.Queue[_Trabalho | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ultimo_erro: str | None = None
        self._impressos = 0

    def iniciar(self) -> None:
        self._thread = threading.Thread(
            target=self._laco, name="impressao", daemon=True
        )
        self._thread.start()

    def parar(self, *, timeout: float = 5.0) -> None:
        self._fila.put(None)  # sentinela de encerramento
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def enfileirar(self, linhas: list[str], cupom: int) -> None:
        self._fila.put(_Trabalho(linhas=list(linhas), cupom=cupom))

    def estado(self) -> dict[str, object]:
        return {
            "habilitado": self._habilitado,
            "impressora": self._impressora or (impressora_padrao() or ""),
            "na_fila": self._fila.qsize(),
            "impressos_nesta_sessao": self._impressos,
            "ultimo_erro": self._ultimo_erro,
        }

    def _laco(self) -> None:
        while True:
            trabalho = self._fila.get()
            if trabalho is None:
                return
            try:
                self._processar(trabalho)
            except Exception:
                log.exception("erro inesperado ao imprimir cupom")
            finally:
                self._fila.task_done()

    def _processar(self, trabalho: _Trabalho) -> None:
        # Arquivo primeiro: se a impressora falhar, o cupom ja existe.
        try:
            salvar_cupom(trabalho.linhas, self._pasta, trabalho.cupom)
        except OSError as erro:
            log.warning("nao deu para salvar copia do cupom: %s", erro)

        if not self._habilitado:
            return

        try:
            imprimir_linhas(
                trabalho.linhas,
                impressora=self._impressora,
                codepage=self._codepage,
                titulo=f"Cupom {trabalho.cupom:06d}",
            )
            self._impressos += 1
            self._ultimo_erro = None
        except ErroImpressao as erro:
            self._ultimo_erro = str(erro)
            log.warning("cupom %06d nao imprimiu: %s", trabalho.cupom, erro)
