"""
Fila de vendas offline-first.

O contrato do checkout e curto: **grava no SQLite e responde**. Nem rede,
nem impressora, nem nota fiscal entram no caminho da resposta. Se a internet
da loja cair no meio do movimento, o caixa continua vendendo e a fila vai
esvaziando sozinha quando a conexao voltar.

    finalizar()  ->  INSERT (fsync)  ->  responde ao caixa
                                    \
                                     +-> thread de envio -> Upstash
                                         (backoff exponencial + jitter)

A chave no Redis e `venda:{uuid}`, com o uuid gerado no momento da venda.
Reenviar a mesma venda e portanto idempotente: um `SET` na mesma chave
sobrescreve com o mesmo conteudo, nunca duplica faturamento.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .carrinho import ItemCarrinho
from .db import Banco
from .upstash import ClienteUpstash, ErroUpstash

__all__ = ["FilaVendas", "VendaGravada"]

log = logging.getLogger(__name__)

#: Backoff: 15s, 30s, 1min, 2min... com teto de 15min. O teto existe para a
#: fila nao "dormir" horas depois de uma queda longa de internet.
BACKOFF_BASE_S = 15
BACKOFF_TETO_S = 900
#: Quantas vendas enviar por rodada. Lote pequeno mantem a thread curta e
#: nao segura o lock de escrita do SQLite por muito tempo.
LOTE_ENVIO = 20


@dataclass(frozen=True, slots=True)
class VendaGravada:
    """O que o checkout devolve para a tela depois de gravar."""

    cupom: int
    uuid: str
    criado_em: str
    total_centavos: int
    forma_pagamento: str
    recebido_centavos: int | None
    troco_centavos: int | None
    itens: list[ItemCarrinho]
    cpf: str | None = None

    def para_redis(self) -> dict[str, Any]:
        """
        Formato gravado em `venda:{uuid}`.

        Segue o modelo compartilhado (itens, total, forma_pagamento,
        timestamp, sincronizado) e acrescenta os campos que o precifier pode
        querer para relatorio. `total` vai em reais porque e o que o modelo
        combinado especifica; `total_centavos` acompanha para quem preferir
        o inteiro exato.
        """
        return {
            "itens": [
                {
                    "codigo": item.codigo,
                    "nome": item.nome,
                    "tipo": item.tipo,
                    "plu": item.plu,
                    "quantidade": item.quantidade,
                    "peso_g": item.peso_g,
                    "preco_unitario": item.preco_unitario_centavos / 100,
                    "subtotal": item.subtotal_centavos / 100,
                }
                for item in self.itens
            ],
            "total": self.total_centavos / 100,
            "total_centavos": self.total_centavos,
            "forma_pagamento": self.forma_pagamento,
            "timestamp": self.criado_em,
            "sincronizado": True,
            "cupom": self.cupom,
            "cpf": self.cpf,
            "origem": "pdv-casa-das-massas",
        }


class FilaVendas:
    """Grava vendas localmente e sincroniza em segundo plano."""

    def __init__(
        self,
        banco: Banco,
        cliente: ClienteUpstash | None,
        *,
        intervalo_s: int = 15,
        max_tentativas: int = 0,
    ) -> None:
        self._banco = banco
        self._cliente = cliente
        self._intervalo_s = max(5, intervalo_s)
        self._max_tentativas = max_tentativas  # 0 = sem limite
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._acordar = threading.Event()
        self._ultimo_erro: str | None = None
        self._enviadas = 0

    # -------------------------------------------------------------- gravacao

    def gravar(
        self,
        *,
        itens: list[ItemCarrinho],
        total_centavos: int,
        forma_pagamento: str,
        recebido_centavos: int | None = None,
        troco_centavos: int | None = None,
        cpf: str | None = None,
    ) -> VendaGravada:
        """
        Grava a venda no SQLite e devolve o numero do cupom.

        E o unico ponto do checkout que pode falhar de forma fatal -- e falha
        antes de imprimir, entao nao existe cupom impresso sem venda gravada.
        """
        identificador = str(uuid.uuid4())
        criado_em = datetime.now(UTC).astimezone().isoformat(timespec="seconds")

        venda_parcial = VendaGravada(
            cupom=0,
            uuid=identificador,
            criado_em=criado_em,
            total_centavos=total_centavos,
            forma_pagamento=forma_pagamento,
            recebido_centavos=recebido_centavos,
            troco_centavos=troco_centavos,
            itens=list(itens),
            cpf=cpf,
        )

        conexao = self._banco.transacao()
        try:
            cursor = conexao.execute(
                "INSERT INTO venda "
                "(uuid, criado_em, total_centavos, forma_pagamento, payload, "
                " proxima_tentativa) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (
                    identificador,
                    criado_em,
                    total_centavos,
                    forma_pagamento,
                    json.dumps(_payload_local(venda_parcial), ensure_ascii=False),
                ),
            )
            cupom = int(cursor.lastrowid or 0)
            conexao.execute("COMMIT")
        except Exception:
            conexao.execute("ROLLBACK")
            raise

        venda = VendaGravada(
            cupom=cupom,
            uuid=identificador,
            criado_em=criado_em,
            total_centavos=total_centavos,
            forma_pagamento=forma_pagamento,
            recebido_centavos=recebido_centavos,
            troco_centavos=troco_centavos,
            itens=list(itens),
            cpf=cpf,
        )
        # O cupom so existe depois do INSERT, entao o payload e reescrito uma
        # vez com o numero definitivo. Fora da transacao de proposito: a
        # venda ja esta duravel, isto e enfeite para o Redis.
        self._banco.conexao().execute(
            "UPDATE venda SET payload = ? WHERE uuid = ?",
            (json.dumps(_payload_local(venda), ensure_ascii=False), identificador),
        )

        # Acorda a thread de envio: se houver internet, a venda sobe em
        # menos de um segundo em vez de esperar o proximo ciclo.
        self._acordar.set()
        return venda

    # ------------------------------------------------------------ diagnostico

    def estado(self) -> dict[str, Any]:
        linha = (
            self._banco.conexao()
            .execute(
                "SELECT "
                "  COUNT(*) FILTER (WHERE sincronizado = 0) AS pendentes, "
                "  COUNT(*) FILTER (WHERE sincronizado = 1) AS enviadas, "
                "  COUNT(*) AS total "
                "FROM venda"
            )
            .fetchone()
        )
        return {
            "pendentes": linha["pendentes"],
            "enviadas": linha["enviadas"],
            "total": linha["total"],
            "enviadas_nesta_sessao": self._enviadas,
            "upstash_configurado": self._cliente is not None,
            "ultimo_erro": self._ultimo_erro,
        }

    def vendas_do_dia(self) -> dict[str, Any]:
        """Fechamento simples do dia, por forma de pagamento."""
        hoje = datetime.now().astimezone().strftime("%Y-%m-%d")
        linhas = (
            self._banco.conexao()
            .execute(
                "SELECT forma_pagamento, COUNT(*) AS qtd, "
                "       SUM(total_centavos) AS soma "
                "FROM venda WHERE substr(criado_em, 1, 10) = ? "
                "GROUP BY forma_pagamento",
                (hoje,),
            )
            .fetchall()
        )

        por_forma = {
            linha["forma_pagamento"]: {
                "quantidade": linha["qtd"],
                "total_centavos": linha["soma"] or 0,
            }
            for linha in linhas
        }
        return {
            "data": hoje,
            "por_forma": por_forma,
            "quantidade": sum(f["quantidade"] for f in por_forma.values()),
            "total_centavos": sum(f["total_centavos"] for f in por_forma.values()),
        }

    # --------------------------------------------------------- ciclo de vida

    def iniciar(self) -> None:
        if self._cliente is None:
            log.info("Upstash nao configurado: as vendas ficam so no SQLite local.")
            return
        self._thread = threading.Thread(
            target=self._laco, name="fila-vendas", daemon=True
        )
        self._thread.start()

    def parar(self, *, timeout: float = 3.0) -> None:
        self._parar.set()
        self._acordar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def sincronizar_agora(self) -> int:
        """Envia o que estiver pendente e devolve quantas subiram."""
        if self._cliente is None:
            return 0
        return self._enviar_pendentes()

    # -------------------------------------------------------------- interna

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self._enviar_pendentes()
            except Exception:
                log.exception("erro inesperado na fila de vendas")

            # Acorda no intervalo OU assim que uma venda nova for gravada.
            self._acordar.wait(self._intervalo_s)
            self._acordar.clear()

    def _enviar_pendentes(self) -> int:
        assert self._cliente is not None

        agora = time.time()
        limite = "AND tentativas < :max" if self._max_tentativas > 0 else ""
        linhas = (
            self._banco.conexao()
            .execute(
                f"SELECT cupom, uuid, payload, tentativas FROM venda "
                f"WHERE sincronizado = 0 AND proxima_tentativa <= :agora {limite} "
                f"ORDER BY cupom LIMIT :lote",
                {"agora": agora, "lote": LOTE_ENVIO, "max": self._max_tentativas},
            )
            .fetchall()
        )

        enviadas = 0
        for linha in linhas:
            if self._parar.is_set():
                break
            if self._enviar_uma(linha):
                enviadas += 1
            else:
                # Rede caiu: nao insiste nas outras agora, todas vao falhar
                # igual e cada tentativa gasta um timeout.
                break

        if enviadas:
            self._enviados_soma(enviadas)
        return enviadas

    def _enviar_uma(self, linha: sqlite3.Row) -> bool:
        assert self._cliente is not None

        try:
            self._cliente.comando("SET", f"venda:{linha['uuid']}", linha["payload"])
        except ErroUpstash as erro:
            self._marcar_falha(linha, str(erro))
            return False

        self._banco.conexao().execute(
            "UPDATE venda SET sincronizado = 1, ultimo_erro = NULL WHERE uuid = ?",
            (linha["uuid"],),
        )
        log.info("venda %s (cupom %s) sincronizada", linha["uuid"], linha["cupom"])
        return True

    def _marcar_falha(self, linha: sqlite3.Row, erro: str) -> None:
        tentativas = int(linha["tentativas"]) + 1
        espera = min(BACKOFF_BASE_S * 2 ** (tentativas - 1), BACKOFF_TETO_S)
        # Jitter: se varias vendas falharem juntas, elas nao voltam todas no
        # mesmo instante quando a internet voltar.
        espera += random.uniform(0, espera * 0.25)

        self._banco.conexao().execute(
            "UPDATE venda SET tentativas = ?, proxima_tentativa = ?, "
            "ultimo_erro = ? WHERE uuid = ?",
            (tentativas, time.time() + espera, erro[:500], linha["uuid"]),
        )
        self._ultimo_erro = erro
        log.warning(
            "venda %s falhou (tentativa %d); nova tentativa em %.0fs: %s",
            linha["uuid"],
            tentativas,
            espera,
            erro,
        )

    def _enviados_soma(self, quantidade: int) -> None:
        self._enviadas += quantidade
        self._ultimo_erro = None


def _payload_local(venda: VendaGravada) -> dict[str, Any]:
    """O que fica no SQLite: o payload do Redis + o que so interessa aqui."""
    dados = venda.para_redis()
    dados["recebido_centavos"] = venda.recebido_centavos
    dados["troco_centavos"] = venda.troco_centavos
    dados["uuid"] = venda.uuid
    return dados
