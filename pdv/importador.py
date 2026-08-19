"""
Importacao do catalogo da balanca (SQLite `produtos`) para o PDV.

Serve dois destinos, com a mesma leitura:

* `scripts/importar_catalogo_local.py` -> grava no cache SQLite do PDV,
  para o caixa funcionar sem nenhuma configuracao de rede;
* `scripts/publicar_catalogo.py` -> grava no Upstash, no formato
  `produto:{plu}` / `produto_ean:{codigo}`.

Fica em `pdv/` e nao em `scripts/` porque tem regra de negocio de verdade
(o que e produto por peso, como o nome e limpo, como a categoria e
adivinhada) e portanto precisa de teste.

Formato de origem (`pdv_database.db`, tabela `produtos`):

    codigo_barras TEXT PRIMARY KEY   -- "2014800" (PLU) ou EAN de fabricante
    nome          TEXT               -- "FETUTINE", "6COXINHA PQ."
    preco         REAL               -- por kg (peso) ou por unidade
    validade      TEXT               -- "4D" (nao usado pelo PDV)
    codigo_sistema INTEGER           -- o mesmo PLU, em inteiro
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .catalogo import ProdutoPeso, ProdutoUnidade, _centavos
from .db import Banco

__all__ = [
    "ResultadoImportacao",
    "classificar",
    "gravar_no_cache_local",
    "ler_sqlite_balanca",
    "limpar_nome",
]

#: Etiqueta generica "PRODUTO POR KG": pedido de peso, nao produto.
CODIGO_GENERICO = "2000000"

#: Categoria por palavra no nome. Mesma ordem do CATEGORIAS_SUGERIDAS do
#: precifier (a primeira que casar vence), para os dois classificarem igual.
#: "Congelados" vem antes de "Massas" de proposito.
CATEGORIAS: list[tuple[str, tuple[str, ...]]] = [
    ("Congelados", ("CONG.", "CONG ", "CONGELAD")),
    ("Bebidas", ("COCA", "FANTA", "GUARANA", "AGUA", "CERVEJA", "SUCO", "LIMONADA")),
    (
        "Salgados",
        (
            "COXINHA",
            "KIBE",
            "ESFIHA",
            "RISOLES",
            "PASTEL",
            "CROQUETE",
            "BOLINHA",
            "DOGUINHO",
        ),
    ),
    ("Lasanhas", ("LASANHA",)),
    ("Molhos", ("MOLHO",)),
    (
        "Carnes",
        (
            "COSTELA",
            "ALCATRA",
            "PERNIL",
            "LOMBO",
            "PICANHA",
            "POSTA",
            "CHESTER",
            "FRANGO ASSADO",
            "COXA DESOS",
        ),
    ),
    (
        "Doces",
        (
            "PUDIM",
            "TORTA DE",
            "NEGA MALUCA",
            "CUQUE",
            "FORMIGUEIRO",
            "BANOFE",
            "MORANGOFE",
            "FAROFA DOCE",
        ),
    ),
    (
        "Massas recheadas",
        (
            "CAPELET",
            "RAVIOLI",
            "CANELONE",
            "RONDELI",
            "ROND.",
            "CONCHA",
            "CONCHILIONE",
            "TORTEI",
            "PIEROG",
            "CALZO",
        ),
    ),
    (
        "Massas",
        (
            "MACARRAO",
            "ESPAGUETE",
            "FETUTINE",
            "TALHARIM",
            "MASSA",
            "NHOQUE",
            "SOPA CAPELETI",
        ),
    ),
    (
        "Rotisseria",
        (
            "EMPADAO",
            "PANQUECA",
            "SALPICAO",
            "FRICASSE",
            "RISOTO",
            "ARROZ",
            "MAIONESE",
            "FAROFA",
            "STROGONOFF",
            "ATUM",
        ),
    ),
]


@dataclass(slots=True)
class ResultadoImportacao:
    """O que saiu da leitura do SQLite da balanca."""

    por_peso: list[dict[str, Any]] = field(default_factory=list)
    por_unidade: list[dict[str, Any]] = field(default_factory=list)
    #: Produtos que NAO podem ser vendidos, com o motivo. Precisam aparecer:
    #: um produto sem preco some do caixa silenciosamente se ninguem avisar.
    ignorados: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.por_peso) + len(self.por_unidade)

    def por_categoria(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for item in [*self.por_peso, *self.por_unidade]:
            contagem[item["categoria"]] = contagem.get(item["categoria"], 0) + 1
        return dict(sorted(contagem.items(), key=lambda par: (-par[1], par[0])))


def classificar(nome: str) -> str:
    """
    Adivinha a categoria pelo nome.

    >>> classificar("CANELONE CARNE")
    'Massas recheadas'
    >>> classificar("MOLHO BOL CONG.")
    'Congelados'
    >>> classificar("XPTO")
    'Outros'
    """
    alvo = nome.upper()
    for categoria, palavras in CATEGORIAS:
        if any(palavra in alvo for palavra in palavras):
            return categoria
    return "Outros"


def limpar_nome(nome: str) -> str:
    """
    Tira o prefixo numerico que a balanca coloca em alguns nomes.

    Os salgados vem como "6COXINHA PQ." -- esse "6" e codigo interno da
    balanca e sairia impresso no cupom do cliente.

    >>> limpar_nome("6COXINHA PQ.")
    'COXINHA PQ.'
    >>> limpar_nome("FETUTINE")
    'FETUTINE'
    >>> limpar_nome("350ml COCA")
    'ml COCA'
    """
    limpo = nome.strip()
    while limpo and limpo[0].isdigit():
        limpo = limpo[1:]
    return limpo.strip() or nome.strip()


def e_codigo_de_balanca(codigo: str) -> bool:
    """
    7 digitos comecando em "2" = PLU da balanca.

    >>> e_codigo_de_balanca("2014800")
    True
    >>> e_codigo_de_balanca("7894900027013")
    False
    """
    return len(codigo) == 7 and codigo.isdigit() and codigo.startswith("2")


def ler_sqlite_balanca(caminho: Path) -> ResultadoImportacao:
    """Le a tabela `produtos` e separa por peso / por unidade."""
    resultado = ResultadoImportacao()

    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    try:
        linhas = conexao.execute(
            "SELECT codigo_barras, nome, preco FROM produtos"
        ).fetchall()
    finally:
        conexao.close()

    for linha in linhas:
        codigo = str(linha["codigo_barras"] or "").strip()
        nome = limpar_nome(str(linha["nome"] or ""))
        preco = float(linha["preco"] or 0)

        if not codigo or not nome:
            resultado.ignorados.append(
                f"{codigo or '(sem codigo)'}: registro incompleto"
            )
            continue

        if codigo == CODIGO_GENERICO:
            continue  # etiqueta generica, nao e produto

        if preco <= 0:
            resultado.ignorados.append(
                f"{codigo} {nome}: sem preco (R$ {preco:.2f}) - "
                f"cadastre o preco antes de vender"
            )
            continue

        if e_codigo_de_balanca(codigo):
            resultado.por_peso.append(
                {
                    "plu": int(codigo[1:5]),
                    "nome": nome,
                    "preco_kg": round(preco, 2),
                    "categoria": classificar(nome),
                    "ativo": True,
                }
            )
        else:
            resultado.por_unidade.append(
                {
                    "codigo": codigo,
                    "nome": nome,
                    "preco_fixo": round(preco, 2),
                    "categoria": classificar(nome),
                    "ativo": True,
                }
            )

    return resultado


def gravar_no_cache_local(
    banco: Banco, resultado: ResultadoImportacao, *, versao: str
) -> None:
    """
    Grava direto no cache SQLite do PDV.

    Permite abrir o caixa sem nenhuma credencial de Redis -- util na
    instalacao e como plano B se o Upstash estiver fora do ar.

    Tudo numa transacao: ou o catalogo troca inteiro, ou nao troca.
    """
    conexao = banco.transacao()
    try:
        conexao.execute("DELETE FROM catalogo_produto")
        conexao.executemany(
            "INSERT INTO catalogo_produto "
            "(plu, prefixo, nome, preco_kg_centavos, categoria, ativo) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    item["plu"],
                    f"2{item['plu']:04d}00",
                    item["nome"],
                    _centavos(item["preco_kg"]),
                    item["categoria"],
                    int(bool(item["ativo"])),
                )
                for item in resultado.por_peso
            ],
        )
        conexao.execute("DELETE FROM catalogo_ean")
        conexao.executemany(
            "INSERT INTO catalogo_ean "
            "(codigo, nome, preco_centavos, categoria, ativo) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    item["codigo"],
                    item["nome"],
                    _centavos(item["preco_fixo"]),
                    item["categoria"],
                    int(bool(item["ativo"])),
                )
                for item in resultado.por_unidade
            ],
        )
        conexao.execute(
            "INSERT INTO catalogo_meta (chave, valor) VALUES ('versao', ?) "
            "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
            (versao,),
        )
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise


def para_objetos(
    resultado: ResultadoImportacao,
) -> tuple[dict[int, ProdutoPeso], dict[str, ProdutoUnidade]]:
    """Converte para os objetos do catalogo (usado nos testes)."""
    por_plu = {
        item["plu"]: ProdutoPeso(
            plu=item["plu"],
            nome=item["nome"],
            preco_kg_centavos=_centavos(item["preco_kg"]),
            categoria=item["categoria"],
            ativo=bool(item["ativo"]),
        )
        for item in resultado.por_peso
    }
    por_ean = {
        item["codigo"]: ProdutoUnidade(
            codigo=item["codigo"],
            nome=item["nome"],
            preco_centavos=_centavos(item["preco_fixo"]),
            categoria=item["categoria"],
            ativo=bool(item["ativo"]),
        )
        for item in resultado.por_unidade
    }
    return por_plu, por_ean
