"""
Catalogo de produtos: cache em memoria + sincronizacao em segundo plano.

Regra que manda neste arquivo: **nenhuma leitura de codigo de barras pode
esperar rede**. O caixa consulta sempre um dicionario que ja esta na
memoria do processo. Quem conversa com o Upstash e uma thread separada,
que troca esse dicionario por um novo quando termina.

Ordem de carga no boot (por isso o caixa abre em segundos):

1. Le o cache do SQLite -> o caixa ja esta operante, mesmo sem internet.
2. Sobe a thread de sincronizacao -> compara `catalogo:versao` e, se mudou,
   baixa o catalogo novo e troca o snapshot.

A troca e uma unica atribuicao de atributo. Nenhum leitor ve um catalogo
pela metade e nenhum leitor pega lock -- o snapshot e imutavel.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .db import Banco
from .upstash import ClienteUpstash, ErroUpstash

__all__ = [
    "CHAVE_SNAPSHOT",
    "CHAVE_VERSAO",
    "PREFIXO_PRODUTO",
    "PREFIXO_PRODUTO_EAN",
    "Catalogo",
    "ProdutoPeso",
    "ProdutoUnidade",
    "Snapshot",
]

log = logging.getLogger(__name__)

CHAVE_VERSAO = "catalogo:versao"
#: Atalho opcional: o catalogo inteiro num unico valor JSON. Quando existe,
#: sincronizar custa 1 requisicao em vez de 1 + N. Ver scripts/publicar_catalogo.py.
CHAVE_SNAPSHOT = "catalogo:snapshot"
PREFIXO_PRODUTO = "produto:"
PREFIXO_PRODUTO_EAN = "produto_ean:"


def _centavos(valor: Any) -> int:
    """
    Converte preco em reais para centavos inteiros, sem erro de float.

    `Decimal(str(...))` e proposital: `Decimal(61.9)` carrega o lixo binario
    do float, `Decimal("61.9")` nao.
    """
    if valor is None:
        return 0
    try:
        reais = Decimal(str(valor).replace(",", "."))
    except (ArithmeticError, ValueError):
        return 0
    return int((reais * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalizar_busca(texto: str) -> str:
    """Minusculas e sem acento, para a busca manual por nome nao frustrar."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


@dataclass(frozen=True, slots=True)
class ProdutoPeso:
    """Produto vendido por peso, identificado pelo PLU da balanca."""

    plu: int
    nome: str
    preco_kg_centavos: int
    categoria: str = ""
    ativo: bool = True

    @property
    def prefixo(self) -> str:
        return f"2{self.plu:04d}00"

    @property
    def preco_kg(self) -> float:
        return self.preco_kg_centavos / 100.0


@dataclass(frozen=True, slots=True)
class ProdutoUnidade:
    """Produto de prateleira, vendido por unidade e lido por EAN."""

    codigo: str
    nome: str
    preco_centavos: int
    categoria: str = ""
    ativo: bool = True

    @property
    def preco(self) -> float:
        return self.preco_centavos / 100.0


@dataclass(frozen=True, slots=True)
class Snapshot:
    """
    Uma foto imutavel do catalogo.

    Imutavel para poder ser trocada por atribuicao simples: quem esta lendo
    continua com a foto antiga e coerente ate terminar.
    """

    versao: str = "0"
    por_plu: dict[int, ProdutoPeso] = field(default_factory=dict)
    por_ean: dict[str, ProdutoUnidade] = field(default_factory=dict)
    atualizado_em: str = ""
    origem: str = "vazio"

    @property
    def total(self) -> int:
        return len(self.por_plu) + len(self.por_ean)

    @property
    def vazio(self) -> bool:
        return self.total == 0


class Catalogo:
    """Cache em memoria com sincronizacao periodica."""

    def __init__(
        self,
        banco: Banco,
        cliente: ClienteUpstash | None,
        *,
        intervalo_s: int = 60,
    ) -> None:
        self._banco = banco
        self._cliente = cliente
        self._intervalo_s = max(5, intervalo_s)
        self._snapshot = Snapshot()
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._ultimo_erro: str | None = None
        self._ultima_tentativa: str | None = None
        # Protege apenas a ESCRITA do snapshot (uma sincronizacao por vez).
        # Leitura nao passa por aqui.
        self._trava_escrita = threading.Lock()

    # ------------------------------------------------------------- leitura

    @property
    def snapshot(self) -> Snapshot:
        return self._snapshot

    def buscar_por_plu(self, plu: int) -> ProdutoPeso | None:
        produto = self._snapshot.por_plu.get(plu)
        if produto is None or not produto.ativo:
            return None
        return produto

    def buscar_por_ean(self, codigo: str) -> ProdutoUnidade | None:
        produto = self._snapshot.por_ean.get(codigo)
        if produto is None or not produto.ativo:
            return None
        return produto

    def buscar_por_nome(self, termo: str, *, limite: int = 20) -> list[dict[str, Any]]:
        """
        Busca livre por nome, para quando a etiqueta nao le ou nao existe.

        Varredura linear sobre ~150 produtos: alguns microssegundos, nao
        vale indice invertido nenhum.
        """
        alvo = _normalizar_busca(termo.strip())
        if len(alvo) < 2:
            return []

        achados: list[dict[str, Any]] = []
        instantaneo = self._snapshot

        for produto in instantaneo.por_plu.values():
            if produto.ativo and alvo in _normalizar_busca(produto.nome):
                achados.append(
                    {
                        "tipo": "peso",
                        "plu": produto.plu,
                        "codigo": produto.prefixo,
                        "nome": produto.nome,
                        "preco_centavos": produto.preco_kg_centavos,
                        "unidade": "kg",
                        "categoria": produto.categoria,
                    }
                )
        for unidade in instantaneo.por_ean.values():
            if unidade.ativo and alvo in _normalizar_busca(unidade.nome):
                achados.append(
                    {
                        "tipo": "unidade",
                        "plu": None,
                        "codigo": unidade.codigo,
                        "nome": unidade.nome,
                        "preco_centavos": unidade.preco_centavos,
                        "unidade": "un",
                        "categoria": unidade.categoria,
                    }
                )

        achados.sort(key=lambda p: p["nome"])
        return achados[:limite]

    # ------------------------------------------------------------ diagnostico

    def estado(self) -> dict[str, Any]:
        instantaneo = self._snapshot
        return {
            "versao": instantaneo.versao,
            "produtos_peso": len(instantaneo.por_plu),
            "produtos_unidade": len(instantaneo.por_ean),
            "atualizado_em": instantaneo.atualizado_em,
            "origem": instantaneo.origem,
            "upstash_configurado": self._cliente is not None,
            "ultima_tentativa": self._ultima_tentativa,
            "ultimo_erro": self._ultimo_erro,
        }

    # --------------------------------------------------------- ciclo de vida

    def iniciar(self) -> None:
        """Carrega o cache local e sobe a thread de sincronizacao."""
        self._carregar_do_sqlite()

        if self._cliente is None:
            log.info(
                "Upstash nao configurado: o catalogo vai operar so com o "
                "cache local (%d produtos).",
                self._snapshot.total,
            )
            return

        self._thread = threading.Thread(
            target=self._laco,
            name="catalogo-sync",
            daemon=True,  # nao segura o encerramento do processo
        )
        self._thread.start()

    def parar(self, *, timeout: float = 3.0) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def sincronizar_agora(self, *, forcar: bool = False) -> bool:
        """
        Sincroniza na hora (usada pelo botao "Atualizar catalogo").

        Devolve True se o snapshot em memoria mudou.
        """
        if self._cliente is None:
            self._ultimo_erro = "Upstash nao configurado."
            return False
        return self._sincronizar(forcar=forcar)

    # ------------------------------------------------------------- interna

    def _laco(self) -> None:
        # Primeira sincronizacao imediata: se a internet estiver de pe, o
        # caixa comeca o dia com preco do dia.
        while not self._parar.is_set():
            try:
                self._sincronizar()
            except Exception:
                log.exception("erro inesperado na sincronizacao do catalogo")
            self._parar.wait(self._intervalo_s)

    def _sincronizar(self, *, forcar: bool = False) -> bool:
        assert self._cliente is not None

        with self._trava_escrita:
            self._ultima_tentativa = _agora()
            try:
                versao_remota = self._ler_versao_remota()

                if (
                    not forcar
                    and versao_remota is not None
                    and versao_remota == self._snapshot.versao
                    and not self._snapshot.vazio
                ):
                    self._ultimo_erro = None
                    return False  # nada mudou: economiza a viagem grande

                por_plu, por_ean, versao_efetiva = self._baixar(versao_remota)

                if not por_plu and not por_ean:
                    # Catalogo remoto vazio quase sempre e configuracao
                    # errada, nao "a loja nao tem produtos". Manter o cache
                    # antigo e mais util do que zerar o caixa.
                    self._ultimo_erro = (
                        "O catalogo remoto voltou vazio; mantendo o cache local."
                    )
                    log.warning(self._ultimo_erro)
                    return False

                novo = Snapshot(
                    versao=versao_efetiva,
                    por_plu=por_plu,
                    por_ean=por_ean,
                    atualizado_em=_agora(),
                    origem="upstash",
                )
                self._gravar_no_sqlite(novo)
                self._snapshot = novo  # <- a troca atomica
                self._ultimo_erro = None
                log.info(
                    "catalogo atualizado: versao %s, %d por peso, %d por unidade",
                    novo.versao,
                    len(novo.por_plu),
                    len(novo.por_ean),
                )
                return True

            except ErroUpstash as erro:
                self._ultimo_erro = str(erro)
                log.warning("falha ao sincronizar catalogo: %s", erro)
                return False

    def _ler_versao_remota(self) -> str | None:
        assert self._cliente is not None
        valor = self._cliente.get(CHAVE_VERSAO)
        return None if valor is None else str(valor).strip()

    def _baixar(
        self, versao_remota: str | None
    ) -> tuple[dict[int, ProdutoPeso], dict[str, ProdutoUnidade], str]:
        """
        Baixa o catalogo, preferindo o snapshot de chave unica.

        Duas formas suportadas:

        * `catalogo:snapshot` -- um JSON com tudo. 1 requisicao.
        * `produto:*` / `produto_ean:*` -- o formato descrito na
          especificacao. 1 SCAN + 1 pipeline de MGET.
        """
        assert self._cliente is not None

        bruto = self._cliente.get_json(CHAVE_SNAPSHOT)
        if isinstance(bruto, dict) and (bruto.get("produtos") or bruto.get("eans")):
            por_plu, por_ean = self._do_snapshot_unico(bruto)
            versao = str(bruto.get("versao") or versao_remota or "")
        else:
            por_plu, por_ean = self._das_chaves_individuais()
            versao = versao_remota or ""

        if not versao:
            # Sem `catalogo:versao`, a versao passa a ser a impressao digital
            # do proprio conteudo -- assim ainda detectamos mudanca sem
            # baixar tudo duas vezes por nada.
            versao = _impressao_digital(por_plu, por_ean)

        return por_plu, por_ean, versao

    def _do_snapshot_unico(
        self, bruto: dict[str, Any]
    ) -> tuple[dict[int, ProdutoPeso], dict[str, ProdutoUnidade]]:
        por_plu: dict[int, ProdutoPeso] = {}
        por_ean: dict[str, ProdutoUnidade] = {}

        for item in bruto.get("produtos") or []:
            if not isinstance(item, dict):
                continue
            produto = _montar_produto_peso(item.get("plu"), item)
            if produto is not None:
                por_plu[produto.plu] = produto

        for item in bruto.get("eans") or []:
            if not isinstance(item, dict):
                continue
            unidade = _montar_produto_unidade(item.get("codigo"), item)
            if unidade is not None:
                por_ean[unidade.codigo] = unidade

        return por_plu, por_ean

    def _das_chaves_individuais(
        self,
    ) -> tuple[dict[int, ProdutoPeso], dict[str, ProdutoUnidade]]:
        assert self._cliente is not None

        chaves_peso = self._cliente.scan_chaves(f"{PREFIXO_PRODUTO}*")
        chaves_ean = self._cliente.scan_chaves(f"{PREFIXO_PRODUTO_EAN}*")

        por_plu: dict[int, ProdutoPeso] = {}
        for chave, valor in self._mget(chaves_peso):
            produto = _montar_produto_peso(chave[len(PREFIXO_PRODUTO) :], valor)
            if produto is not None:
                por_plu[produto.plu] = produto

        por_ean: dict[str, ProdutoUnidade] = {}
        for chave, valor in self._mget(chaves_ean):
            unidade = _montar_produto_unidade(chave[len(PREFIXO_PRODUTO_EAN) :], valor)
            if unidade is not None:
                por_ean[unidade.codigo] = unidade

        return por_plu, por_ean

    def _mget(self, chaves: list[str]) -> Iterable[tuple[str, Any]]:
        """Busca varias chaves em lotes, cada lote numa unica requisicao."""
        assert self._cliente is not None
        LOTE = 100

        for inicio in range(0, len(chaves), LOTE):
            pedaco = chaves[inicio : inicio + LOTE]
            resultados = self._cliente.pipeline([["GET", c] for c in pedaco])
            for chave, bruto in zip(pedaco, resultados, strict=False):
                if bruto is None:
                    continue
                try:
                    yield chave, json.loads(bruto)
                except (json.JSONDecodeError, TypeError):
                    log.warning("valor de %s nao era JSON valido", chave)

    # ------------------------------------------------------ cache no SQLite

    def _carregar_do_sqlite(self) -> None:
        conexao = self._banco.conexao()

        por_plu = {
            linha["plu"]: ProdutoPeso(
                plu=linha["plu"],
                nome=linha["nome"],
                preco_kg_centavos=linha["preco_kg_centavos"],
                categoria=linha["categoria"],
                ativo=bool(linha["ativo"]),
            )
            for linha in conexao.execute("SELECT * FROM catalogo_produto")
        }
        por_ean = {
            linha["codigo"]: ProdutoUnidade(
                codigo=linha["codigo"],
                nome=linha["nome"],
                preco_centavos=linha["preco_centavos"],
                categoria=linha["categoria"],
                ativo=bool(linha["ativo"]),
            )
            for linha in conexao.execute("SELECT * FROM catalogo_ean")
        }

        self._snapshot = Snapshot(
            versao=self._banco.meta("versao") or "0",
            por_plu=por_plu,
            por_ean=por_ean,
            atualizado_em=self._banco.meta("atualizado_em") or "",
            origem="local" if (por_plu or por_ean) else "vazio",
        )
        log.info(
            "cache local carregado: %d por peso, %d por unidade (versao %s)",
            len(por_plu),
            len(por_ean),
            self._snapshot.versao,
        )

    def _gravar_no_sqlite(self, novo: Snapshot) -> None:
        conexao = self._banco.transacao()
        try:
            conexao.execute("DELETE FROM catalogo_produto")
            conexao.executemany(
                "INSERT INTO catalogo_produto "
                "(plu, prefixo, nome, preco_kg_centavos, categoria, ativo) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        p.plu,
                        p.prefixo,
                        p.nome,
                        p.preco_kg_centavos,
                        p.categoria,
                        int(p.ativo),
                    )
                    for p in novo.por_plu.values()
                ],
            )
            conexao.execute("DELETE FROM catalogo_ean")
            conexao.executemany(
                "INSERT INTO catalogo_ean "
                "(codigo, nome, preco_centavos, categoria, ativo) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (u.codigo, u.nome, u.preco_centavos, u.categoria, int(u.ativo))
                    for u in novo.por_ean.values()
                ],
            )
            conexao.execute(
                "INSERT INTO catalogo_meta (chave, valor) VALUES ('versao', ?) "
                "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
                (novo.versao,),
            )
            conexao.execute(
                "INSERT INTO catalogo_meta (chave, valor) "
                "VALUES ('atualizado_em', ?) "
                "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
                (novo.atualizado_em,),
            )
            conexao.execute("COMMIT")
        except Exception:
            conexao.execute("ROLLBACK")
            raise


# --------------------------------------------------------------------------
# Montagem a partir do JSON cru do Redis
# --------------------------------------------------------------------------


def _montar_produto_peso(chave_plu: Any, dados: Any) -> ProdutoPeso | None:
    """
    Monta um ProdutoPeso a partir de `produto:{plu}`.

    Tolerante de proposito: um produto mal cadastrado no precifier nao pode
    impedir os outros 150 de carregarem.
    """
    if not isinstance(dados, dict):
        return None
    try:
        plu = int(str(chave_plu).strip())
    except (TypeError, ValueError):
        return None
    if not 0 <= plu <= 9999:
        return None

    nome = str(dados.get("nome") or "").strip()
    if not nome:
        return None

    preco = _centavos(dados.get("preco_kg", dados.get("precoVenda")))
    if preco <= 0:
        log.warning("produto:%s (%s) sem preco por kg; ignorado", plu, nome)
        return None

    return ProdutoPeso(
        plu=plu,
        nome=nome,
        preco_kg_centavos=preco,
        categoria=str(dados.get("categoria") or ""),
        ativo=dados.get("ativo", True) is not False,
    )


def _montar_produto_unidade(chave: Any, dados: Any) -> ProdutoUnidade | None:
    if not isinstance(dados, dict):
        return None

    codigo = str(chave or "").strip()
    nome = str(dados.get("nome") or "").strip()
    if not codigo or not nome:
        return None

    preco = _centavos(dados.get("preco_fixo", dados.get("precoVenda")))
    if preco <= 0:
        log.warning("produto_ean:%s (%s) sem preco fixo; ignorado", codigo, nome)
        return None

    return ProdutoUnidade(
        codigo=codigo,
        nome=nome,
        preco_centavos=preco,
        categoria=str(dados.get("categoria") or ""),
        ativo=dados.get("ativo", True) is not False,
    )


def _impressao_digital(
    por_plu: dict[int, ProdutoPeso], por_ean: dict[str, ProdutoUnidade]
) -> str:
    """Hash curto e estavel do catalogo, usado quando falta catalogo:versao."""
    digestor = hashlib.blake2b(digest_size=8)
    for plu in sorted(por_plu):
        p = por_plu[plu]
        digestor.update(f"{plu}|{p.nome}|{p.preco_kg_centavos}|{p.ativo}".encode())
    for codigo in sorted(por_ean):
        u = por_ean[codigo]
        digestor.update(f"{codigo}|{u.nome}|{u.preco_centavos}|{u.ativo}".encode())
    return f"sha-{digestor.hexdigest()}"


def _agora() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")
