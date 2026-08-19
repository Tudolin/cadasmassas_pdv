"""
Banco local SQLite: cache do catalogo + fila de vendas offline.

Duas responsabilidades, um arquivo so, de proposito:

* **Fila de vendas** -- a venda e gravada aqui ANTES de qualquer coisa
  (antes de imprimir, antes de subir para o Upstash). E o unico ponto do
  fluxo onde uma falha significa perder dinheiro, entao aqui o `synchronous`
  e `FULL`: um fsync por venda (uns milissegundos) em troca de nao perder
  venda em queda de energia.

* **Cache do catalogo** -- copia do que o Upstash devolveu na ultima
  sincronizacao. Existe para o caixa abrir instantaneamente e continuar
  vendendo com a internet caida; o catalogo que vale em tempo de venda
  esta na memoria (ver `catalogo.py`), nunca aqui.

Cada thread recebe a sua propria conexao (`sqlite3` nao aceita conexao
compartilhada entre threads sem serializar tudo).
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path

__all__ = ["Banco"]

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS catalogo_produto (
    plu               INTEGER PRIMARY KEY,
    prefixo           TEXT    NOT NULL,
    nome              TEXT    NOT NULL,
    preco_kg_centavos INTEGER NOT NULL,
    categoria         TEXT    NOT NULL DEFAULT '',
    ativo             INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_ean (
    codigo         TEXT    PRIMARY KEY,
    nome           TEXT    NOT NULL,
    preco_centavos INTEGER NOT NULL,
    categoria      TEXT    NOT NULL DEFAULT '',
    ativo          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- `cupom` e o numero que sai impresso; `uuid` e a chave em venda:{uuid}
-- no Upstash. Os dois precisam existir: o cupom o cliente ve, o uuid
-- garante que reenviar a mesma venda nao duplica nada.
CREATE TABLE IF NOT EXISTS venda (
    cupom             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid              TEXT    NOT NULL UNIQUE,
    criado_em         TEXT    NOT NULL,
    total_centavos    INTEGER NOT NULL,
    forma_pagamento   TEXT    NOT NULL,
    payload           TEXT    NOT NULL,
    sincronizado      INTEGER NOT NULL DEFAULT 0,
    tentativas        INTEGER NOT NULL DEFAULT 0,
    proxima_tentativa REAL    NOT NULL DEFAULT 0,
    ultimo_erro       TEXT
);

-- A fila so consulta "o que falta enviar e ja passou da hora". Este indice
-- parcial deixa a varredura proporcional ao tamanho da fila, nao ao
-- historico inteiro de vendas.
CREATE INDEX IF NOT EXISTS idx_venda_pendente
    ON venda (proxima_tentativa)
    WHERE sincronizado = 0;

CREATE INDEX IF NOT EXISTS idx_venda_criado_em ON venda (criado_em);

-- Pedidos de nota fiscal. Tabela separada da venda de proposito: emitir NF
-- e opcional, demorado e pode falhar varias vezes sem que isso diga nada
-- sobre a venda, que ja esta fechada e paga.
CREATE TABLE IF NOT EXISTS nota_fiscal (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    venda_uuid        TEXT    NOT NULL REFERENCES venda (uuid),
    cpf               TEXT,
    estado            TEXT    NOT NULL DEFAULT 'pendente',
    tentativas        INTEGER NOT NULL DEFAULT 0,
    proxima_tentativa REAL    NOT NULL DEFAULT 0,
    ultimo_erro       TEXT,
    resultado         TEXT,
    criado_em         TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nf_pendente
    ON nota_fiscal (proxima_tentativa)
    WHERE estado = 'pendente';
"""


class Banco:
    """Acesso ao SQLite local, com uma conexao por thread."""

    def __init__(self, caminho: Path) -> None:
        self._caminho = Path(caminho)
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Registro de todas as conexoes abertas, para o encerramento poder
        # fechar as das worker tambem. Sem isto, cada thread deixaria a sua
        # conexao para o coletor de lixo fechar "algum dia" -- o que gera
        # ResourceWarning e, pior, deixa arquivo -wal pendurado.
        self._abertas: list[sqlite3.Connection] = []
        self._trava = threading.Lock()
        self._criar_esquema()

    @property
    def caminho(self) -> Path:
        return self._caminho

    # ------------------------------------------------------------ conexoes

    def conexao(self) -> sqlite3.Connection:
        """Conexao desta thread, criada na primeira vez que for pedida."""
        conexao = getattr(self._local, "conexao", None)
        if conexao is None:
            conexao = sqlite3.connect(
                self._caminho,
                timeout=10.0,
                isolation_level=None,  # autocommit; o BEGIN e explicito
                # Cada thread usa exclusivamente a SUA conexao (garantido pelo
                # threading.local acima), entao a checagem do sqlite3 nao
                # acrescenta seguranca -- e ela impediria `fechar_tudo()` de
                # fechar, no encerramento, a conexao criada por uma worker.
                check_same_thread=False,
            )
            conexao.row_factory = sqlite3.Row
            # WAL: a thread da fila le e escreve sem bloquear o caixa.
            conexao.execute("PRAGMA journal_mode = WAL")
            # FULL: venda gravada e venda que sobrevive a queda de energia.
            conexao.execute("PRAGMA synchronous = FULL")
            conexao.execute("PRAGMA foreign_keys = ON")
            # 8 MB de cache: o catalogo inteiro cabe em memoria do SQLite.
            conexao.execute("PRAGMA cache_size = -8000")

            self._local.conexao = conexao
            with self._trava:
                self._abertas.append(conexao)
        return conexao

    def fechar_thread(self) -> None:
        """Fecha a conexao desta thread (usado no encerramento das worker)."""
        conexao = getattr(self._local, "conexao", None)
        if conexao is None:
            return
        self._local.conexao = None
        with self._trava:
            if conexao in self._abertas:
                self._abertas.remove(conexao)
        conexao.close()

    def fechar_tudo(self) -> None:
        """
        Fecha todas as conexoes abertas.

        Chamado no encerramento, DEPOIS de as threads de fundo terminarem.
        """
        with self._trava:
            conexoes, self._abertas = self._abertas, []
        for conexao in conexoes:
            # Encerrando: nao ha o que fazer com um erro de close().
            with contextlib.suppress(sqlite3.Error):
                conexao.close()
        self._local = threading.local()

    def __enter__(self) -> Banco:
        return self

    def __exit__(self, *_excecao: object) -> None:
        self.fechar_tudo()

    def _criar_esquema(self) -> None:
        conexao = self.conexao()
        conexao.executescript(_ESQUEMA)

    # ------------------------------------------------------------- helpers

    def transacao(self) -> sqlite3.Connection:
        """
        Abre uma transacao imediata e devolve a conexao para usar com `with`.

        `BEGIN IMMEDIATE` pega o lock de escrita na hora, em vez de descobrir
        no meio do commit que outra thread chegou primeiro.
        """
        conexao = self.conexao()
        conexao.execute("BEGIN IMMEDIATE")
        return conexao

    def meta(self, chave: str) -> str | None:
        linha = (
            self.conexao()
            .execute("SELECT valor FROM catalogo_meta WHERE chave = ?", (chave,))
            .fetchone()
        )
        return None if linha is None else linha["valor"]

    def gravar_meta(self, chave: str, valor: str) -> None:
        self.conexao().execute(
            "INSERT INTO catalogo_meta (chave, valor) VALUES (?, ?) "
            "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
            (chave, valor),
        )
