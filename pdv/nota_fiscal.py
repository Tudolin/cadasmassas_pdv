"""
Emissao de nota fiscal -- opcional, enfileirada e fora do caminho da venda.

LEIA ANTES DE LIGAR ISSO
========================

O pedido original era "reaproveitar a logica de `emisssao_nf.py`" do repo
pdv-python. Vale registrar o que aquele arquivo realmente faz, porque muda o
desenho aqui:

* nao e integracao com API de NFC-e/SAT -- e **Selenium dirigindo o Chrome**
  no emissor web da IOB (`emissor2.iob.com.br`);
* o login esta com usuario e senha **vazios** (`send_keys("")`) e para num
  `input()` de terminal esperando o operador resolver o captcha a mao;
* o fluxo esta **incompleto**: preenche CPF, nome e quantidade do produto e
  termina ali -- nunca escolhe forma de pagamento nem envia a nota;
* os elementos sao achados por XPath com id gerado
  (`//*[@id="adf61b55-ecca-064d-b7b7-3f6c45eb77ea"]`), que muda a cada
  deploy do site da IOB.

Ou seja: aquele script nunca emitiu uma nota de ponta a ponta, e nao existe
como testa-lo daqui (precisa de credencial da loja + captcha humano).

Alem disso, Chrome + chromedriver custam algumas centenas de MB de RAM --
exatamente o que o requisito "baixo consumo no notebook do cliente" pede
para evitar. Por isso:

* a NF **nunca** roda na thread do checkout: ela e enfileirada no SQLite e
  processada por uma worker, com backoff;
* o emissor e um **adaptador plugavel**. O padrao (`AdaptadorArquivo`) grava
  o pedido em disco em JSON e nao instala nada. O adaptador da IOB fica em
  `AdaptadorIobSelenium`, desligado por padrao, e depende de `selenium`
  instalado a parte (ver requirements-nf.txt);
* nada disso liga sozinho: precisa de `PDV_NF_HABILITADA=1`.

O caminho recomendado a medio prazo e trocar o adaptador por uma API de
emissor fiscal (Focus NFe, Nuvem Fiscal, PlugNotas, eNotas...). O contrato
`AdaptadorNF` abaixo foi desenhado para essa troca ser um arquivo novo.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .db import Banco
from .dinheiro import formatar_peso

__all__ = [
    "AdaptadorArquivo",
    "AdaptadorIobSelenium",
    "AdaptadorNF",
    "EmissorNF",
    "ErroNF",
    "PedidoNF",
    "ResultadoNF",
]

log = logging.getLogger(__name__)

BACKOFF_BASE_S = 60
BACKOFF_TETO_S = 3600


class ErroNF(RuntimeError):
    """Falha ao emitir a nota. A venda continua valida e paga."""


@dataclass(frozen=True, slots=True)
class PedidoNF:
    """O que o emissor precisa saber sobre a venda."""

    venda_uuid: str
    cupom: int
    criado_em: str
    total_centavos: int
    forma_pagamento: str
    cpf: str | None
    itens: list[dict[str, Any]]

    def para_json(self) -> dict[str, Any]:
        return {
            "venda_uuid": self.venda_uuid,
            "cupom": self.cupom,
            "criado_em": self.criado_em,
            "total": self.total_centavos / 100,
            "forma_pagamento": self.forma_pagamento,
            "cpf": self.cpf,
            "itens": self.itens,
        }


@dataclass(frozen=True, slots=True)
class ResultadoNF:
    """Retorno de um adaptador."""

    sucesso: bool
    referencia: str = ""
    detalhe: str = ""


@runtime_checkable
class AdaptadorNF(Protocol):
    """
    Contrato de um emissor de nota.

    Implementar isto e tudo o que um emissor novo precisa fazer. Deve
    levantar `ErroNF` em falha temporaria (para a fila tentar de novo) e
    devolver `ResultadoNF(sucesso=False)` em falha definitiva (para a fila
    parar de tentar).
    """

    nome: str

    def emitir(self, pedido: PedidoNF) -> ResultadoNF: ...


class AdaptadorArquivo:
    """
    Adaptador padrao: grava o pedido em JSON numa pasta.

    Nao emite nota de verdade -- registra o que precisaria ser emitido, para
    o dono levar ao emissor da contabilidade. E o comportamento honesto
    enquanto nao existir integracao fiscal de verdade, e serve de referencia
    de formato para quem for escrever o adaptador definitivo.
    """

    nome = "arquivo"

    def __init__(self, pasta: Path) -> None:
        self._pasta = pasta

    def emitir(self, pedido: PedidoNF) -> ResultadoNF:
        self._pasta.mkdir(parents=True, exist_ok=True)
        caminho = self._pasta / f"nf-{pedido.cupom:06d}-{pedido.venda_uuid[:8]}.json"
        try:
            caminho.write_text(
                json.dumps(pedido.para_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as erro:
            raise ErroNF(f"nao deu para gravar {caminho}: {erro}") from erro

        return ResultadoNF(
            sucesso=True,
            referencia=caminho.name,
            detalhe="Pedido registrado em arquivo (nenhuma nota foi transmitida).",
        )


class AdaptadorIobSelenium:
    """
    Porte do `emisssao_nf.py` para o emissor web da IOB.

    **Nao funciona sem intervencao humana** e esta desligado por padrao. Os
    problemas sao herdados do script original e estao documentados no topo
    deste modulo: XPath com id volatil, captcha no login e fluxo que nao
    conclui a nota.

    Fica aqui porque o pedido foi explicitamente reaproveitar essa logica --
    mas o caminho recomendado e substituir por uma API fiscal.
    """

    nome = "iob-selenium"

    #: Herdados do script original. Vao quebrar num deploy da IOB.
    URL_LOGIN = (
        "https://sso.iob.com.br/signin/?response_type=code&scope=&"
        "client_id=c17d4225-9d57-401b-b4fd-32503121f55b&"
        "redirect_uri=https://emissor.iob.com.br&"
        "lblcontinue=Acessar%20Emissor"
    )
    URL_PDV = "https://emissor2.iob.com.br/notafiscal/pdv"
    XPATH_CPF = '//*[@id="adf61b55-ecca-064d-b7b7-3f6c45eb77ea"]'
    XPATH_PRODUTO = '//*[@id="47735c87-645c-ca08-5e94-ec9d41ded04b"]'
    XPATH_QUANTIDADE = '//*[@id="product_quantity"]'

    def __init__(self, usuario: str, senha: str, *, headless: bool = False) -> None:
        if not usuario or not senha:
            raise ErroNF(
                "Adaptador IOB exige PDV_NF_USUARIO e PDV_NF_SENHA. "
                "Sem credencial ele nao passa do login."
            )
        self._usuario = usuario
        self._senha = senha
        self._headless = headless

    def emitir(self, pedido: PedidoNF) -> ResultadoNF:
        try:
            from selenium import webdriver  # type: ignore[import-not-found]
            from selenium.webdriver.common.by import (
                By,  # type: ignore[import-not-found]
            )
        except ImportError as erro:
            raise ErroNF(
                "selenium nao esta instalado. "
                "Rode: pip install -r requirements-nf.txt"
            ) from erro

        opcoes = webdriver.ChromeOptions()
        if self._headless:
            # Aviso: o login da IOB tem captcha. Em headless ele nao passa.
            opcoes.add_argument("--headless=new")

        navegador = webdriver.Chrome(options=opcoes)
        try:
            navegador.implicitly_wait(10)
            navegador.get(self.URL_LOGIN)
            navegador.find_element(By.ID, "username").send_keys(self._usuario)
            navegador.find_element(By.ID, "password").send_keys(self._senha)

            # O original tinha um `input()` aqui esperando o captcha. Numa
            # thread de servidor isso travaria o processo para sempre, entao
            # falhamos explicitamente em vez de pendurar.
            raise ErroNF(
                "O login da IOB exige captcha resolvido por pessoa. "
                "Este adaptador nao consegue concluir sozinho -- emita a "
                "nota pelo site ou troque por um adaptador de API fiscal."
            )
        finally:
            navegador.quit()


class EmissorNF:
    """
    Fila de notas fiscais: persiste o pedido e processa em segundo plano.

    Mesmo desenho da fila de vendas -- o checkout so enfileira.
    """

    def __init__(
        self,
        banco: Banco,
        adaptador: AdaptadorNF | None,
        *,
        intervalo_s: int = 30,
        max_tentativas: int = 5,
    ) -> None:
        self._banco = banco
        self._adaptador = adaptador
        self._intervalo_s = max(10, intervalo_s)
        self._max_tentativas = max_tentativas
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._acordar = threading.Event()

    @property
    def habilitado(self) -> bool:
        return self._adaptador is not None

    def enfileirar(self, pedido: PedidoNF) -> int | None:
        """Registra o pedido. Devolve o id da fila, ou None se NF esta off."""
        if self._adaptador is None:
            return None

        conexao = self._banco.conexao()
        cursor = conexao.execute(
            "INSERT INTO nota_fiscal (venda_uuid, cpf, criado_em) VALUES (?, ?, ?)",
            (
                pedido.venda_uuid,
                pedido.cpf,
                datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            ),
        )
        self._acordar.set()
        return int(cursor.lastrowid or 0)

    def estado(self) -> dict[str, Any]:
        if self._adaptador is None:
            return {"habilitado": False, "adaptador": None}

        linha = (
            self._banco.conexao()
            .execute(
                "SELECT "
                "  COUNT(*) FILTER (WHERE estado = 'pendente')  AS pendentes, "
                "  COUNT(*) FILTER (WHERE estado = 'emitida')   AS emitidas, "
                "  COUNT(*) FILTER (WHERE estado = 'falhou')    AS falhas "
                "FROM nota_fiscal"
            )
            .fetchone()
        )
        return {
            "habilitado": True,
            "adaptador": self._adaptador.nome,
            "pendentes": linha["pendentes"],
            "emitidas": linha["emitidas"],
            "falhas": linha["falhas"],
        }

    def iniciar(self) -> None:
        if self._adaptador is None:
            return
        self._thread = threading.Thread(
            target=self._laco, name="nota-fiscal", daemon=True
        )
        self._thread.start()

    def parar(self, *, timeout: float = 3.0) -> None:
        self._parar.set()
        self._acordar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self._processar_pendentes()
            except Exception:
                log.exception("erro inesperado na fila de notas fiscais")
            self._acordar.wait(self._intervalo_s)
            self._acordar.clear()

    def _processar_pendentes(self) -> None:
        assert self._adaptador is not None

        linhas = (
            self._banco.conexao()
            .execute(
                "SELECT nf.id, nf.venda_uuid, nf.cpf, nf.tentativas, "
                "       v.cupom, v.criado_em, v.total_centavos, "
                "       v.forma_pagamento, v.payload "
                "FROM nota_fiscal nf JOIN venda v ON v.uuid = nf.venda_uuid "
                "WHERE nf.estado = 'pendente' AND nf.proxima_tentativa <= ? "
                "  AND nf.tentativas < ? "
                "ORDER BY nf.id LIMIT 5",
                (time.time(), self._max_tentativas),
            )
            .fetchall()
        )

        for linha in linhas:
            if self._parar.is_set():
                return
            self._emitir_uma(linha)

    def _emitir_uma(self, linha: Any) -> None:
        assert self._adaptador is not None

        try:
            payload = json.loads(linha["payload"])
        except json.JSONDecodeError as erro:
            self._finalizar(linha["id"], "falhou", erro=f"payload invalido: {erro}")
            return

        pedido = PedidoNF(
            venda_uuid=linha["venda_uuid"],
            cupom=linha["cupom"],
            criado_em=linha["criado_em"],
            total_centavos=linha["total_centavos"],
            forma_pagamento=linha["forma_pagamento"],
            cpf=linha["cpf"],
            itens=[
                {
                    "nome": item.get("nome"),
                    "codigo": item.get("codigo"),
                    # O emissor fiscal quer quantidade em kg para item pesado.
                    "quantidade": (
                        (item.get("peso_g") or 0) / 1000
                        if item.get("tipo") == "peso"
                        else item.get("quantidade")
                    ),
                    "unidade": "KG" if item.get("tipo") == "peso" else "UN",
                    "peso_texto": formatar_peso(item.get("peso_g")),
                    "valor_unitario": item.get("preco_unitario"),
                    "valor_total": item.get("subtotal"),
                }
                for item in payload.get("itens", [])
            ],
        )

        try:
            resultado = self._adaptador.emitir(pedido)
        except ErroNF as erro:
            self._marcar_falha(linha, str(erro))
            return
        except Exception as erro:
            self._marcar_falha(linha, f"erro inesperado: {erro}")
            return

        if resultado.sucesso:
            self._finalizar(
                linha["id"],
                "emitida",
                resultado=json.dumps(
                    {
                        "referencia": resultado.referencia,
                        "detalhe": resultado.detalhe,
                    },
                    ensure_ascii=False,
                ),
            )
            log.info("NF do cupom %s: %s", linha["cupom"], resultado.detalhe)
        else:
            self._finalizar(linha["id"], "falhou", erro=resultado.detalhe)

    def _marcar_falha(self, linha: Any, erro: str) -> None:
        tentativas = int(linha["tentativas"]) + 1
        espera = min(BACKOFF_BASE_S * 2 ** (tentativas - 1), BACKOFF_TETO_S)
        estado = "falhou" if tentativas >= self._max_tentativas else "pendente"

        self._banco.conexao().execute(
            "UPDATE nota_fiscal SET tentativas = ?, proxima_tentativa = ?, "
            "ultimo_erro = ?, estado = ? WHERE id = ?",
            (tentativas, time.time() + espera, erro[:500], estado, linha["id"]),
        )
        log.warning("NF do cupom %s falhou (%d): %s", linha["cupom"], tentativas, erro)

    def _finalizar(
        self,
        id_nf: int,
        estado: str,
        *,
        erro: str | None = None,
        resultado: str | None = None,
    ) -> None:
        self._banco.conexao().execute(
            "UPDATE nota_fiscal SET estado = ?, ultimo_erro = ?, resultado = ? "
            "WHERE id = ?",
            (estado, erro, resultado, id_nf),
        )


def construir_adaptador(
    *,
    habilitada: bool,
    pasta: Path,
    tipo: str = "arquivo",
    usuario: str = "",
    senha: str = "",
) -> AdaptadorNF | None:
    """Escolhe o adaptador conforme a configuracao. None = NF desligada."""
    if not habilitada:
        return None
    if tipo == "iob":
        return AdaptadorIobSelenium(usuario, senha)
    return AdaptadorArquivo(pasta)
