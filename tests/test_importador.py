"""
Testes do importador do catalogo da balanca.

Usa um SQLite montado no teste com o MESMO esquema e os MESMOS dados reais
do `pdv_database.db` da loja.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pdv.db import Banco
from pdv.importador import (
    classificar,
    e_codigo_de_balanca,
    gravar_no_cache_local,
    ler_sqlite_balanca,
    limpar_nome,
    para_objetos,
)

# Linhas reais da tabela `produtos` (codigo_barras, nome, preco).
LINHAS_REAIS = [
    ("2000000", "PRODUTO POR KG", 0.01),  # etiqueta generica: nao e produto
    ("2000100", "CANELONE CARNE", 61.9),
    ("2000200", "CANELONE P/Q", 61.9),
    ("2014800", "FETUTINE", 36.9),
    ("2003400", "FRANGO ASSADO", 38.9),
    ("2007200", "6COXINHA PQ.", 1.1),  # prefixo numerico da balanca
    ("2006700", "MOLHO BOL CONG.", 0.0),  # sem preco: nao pode ser vendido
    ("7894900027013", "COCA-COLA 2L", 12.9),
    ("7894900010015", "COCA-COLA 350ml", 5.5),
]


@pytest.fixture
def banco_balanca(tmp_path: Path) -> Path:
    caminho = tmp_path / "balanca.db"
    conexao = sqlite3.connect(caminho)
    conexao.execute(
        "CREATE TABLE produtos ("
        "  codigo_barras TEXT PRIMARY KEY,"
        "  nome TEXT NOT NULL,"
        "  preco REAL NOT NULL,"
        "  validade TEXT,"
        "  codigo_sistema INTEGER)"
    )
    conexao.executemany(
        "INSERT INTO produtos (codigo_barras, nome, preco) VALUES (?, ?, ?)",
        LINHAS_REAIS,
    )
    conexao.commit()
    conexao.close()
    return caminho


# ------------------------------------------------------------- classificacao


def test_e_codigo_de_balanca() -> None:
    assert e_codigo_de_balanca("2014800")
    assert e_codigo_de_balanca("2000200")
    assert not e_codigo_de_balanca("7894900027013")  # EAN de fabricante
    assert not e_codigo_de_balanca("201480")  # 6 digitos
    assert not e_codigo_de_balanca("3014800")  # nao comeca com 2
    assert not e_codigo_de_balanca("20148AB")


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("CANELONE CARNE", "Massas recheadas"),
        ("CAPELETI FRANGO", "Massas recheadas"),
        ("LASANHA BOLONHESA", "Lasanhas"),
        ("MACARRAO", "Massas"),
        ("FETUTINE", "Massas"),
        ("FRANGO ASSADO", "Carnes"),
        ("COCA-COLA 2L", "Bebidas"),
        ("COXINHA PQ.", "Salgados"),
        ("PUDIM", "Doces"),
        ("RISOTO DE FRANGO", "Rotisseria"),
        ("XPTO DESCONHECIDO", "Outros"),
    ],
)
def test_classificar(nome: str, esperado: str) -> None:
    assert classificar(nome) == esperado


def test_congelados_vencem_massas() -> None:
    """
    A ordem das categorias importa: "MOLHO BOL CONG." tem "MOLHO" e "CONG.".
    Congelados vem primeiro na lista, igual ao precifier.
    """
    assert classificar("MOLHO BOL CONG.") == "Congelados"
    assert classificar("MOLHO SUGO") == "Molhos"


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("6COXINHA PQ.", "COXINHA PQ."),
        ("6ESFIHA DE CARNE", "ESFIHA DE CARNE"),
        ("FETUTINE", "FETUTINE"),
        ("  CANELONE  ", "CANELONE"),
        ("123", "123"),  # so digitos: devolve como veio, nao vazio
    ],
)
def test_limpar_nome(bruto: str, esperado: str) -> None:
    assert limpar_nome(bruto) == esperado


# ------------------------------------------------------------------ leitura


def test_separa_peso_de_unidade(banco_balanca: Path) -> None:
    resultado = ler_sqlite_balanca(banco_balanca)

    plus = {item["plu"] for item in resultado.por_peso}
    assert plus == {1, 2, 148, 34, 72}

    codigos = {item["codigo"] for item in resultado.por_unidade}
    assert codigos == {"7894900027013", "7894900010015"}


def test_etiqueta_generica_nao_entra_no_catalogo(banco_balanca: Path) -> None:
    """`2000000` e um pedido de peso, nao um produto vendavel."""
    resultado = ler_sqlite_balanca(banco_balanca)

    assert all(item["plu"] != 0 for item in resultado.por_peso)
    assert "PRODUTO POR KG" not in [i["nome"] for i in resultado.por_peso]


def test_produto_sem_preco_e_ignorado_com_motivo(banco_balanca: Path) -> None:
    """
    Nao pode sumir em silencio: produto sem preco desaparece do caixa e o
    operador so descobre com o cliente na frente.
    """
    resultado = ler_sqlite_balanca(banco_balanca)

    assert len(resultado.ignorados) == 1
    assert "MOLHO BOL CONG." in resultado.ignorados[0]
    assert "sem preco" in resultado.ignorados[0]
    assert all(item["nome"] != "MOLHO BOL CONG." for item in resultado.por_peso)


def test_plu_sai_dos_digitos_2_a_5(banco_balanca: Path) -> None:
    resultado = ler_sqlite_balanca(banco_balanca)
    por_plu = {item["plu"]: item for item in resultado.por_peso}

    assert por_plu[148]["nome"] == "FETUTINE"
    assert por_plu[1]["nome"] == "CANELONE CARNE"
    assert por_plu[2]["nome"] == "CANELONE P/Q"


def test_nome_do_salgado_perde_o_prefixo(banco_balanca: Path) -> None:
    resultado = ler_sqlite_balanca(banco_balanca)
    por_plu = {item["plu"]: item for item in resultado.por_peso}

    assert por_plu[72]["nome"] == "COXINHA PQ."


def test_total_e_por_categoria(banco_balanca: Path) -> None:
    resultado = ler_sqlite_balanca(banco_balanca)

    assert resultado.total == 7  # 5 por peso + 2 por unidade
    assert resultado.por_categoria()["Massas recheadas"] == 2
    assert resultado.por_categoria()["Bebidas"] == 2


# ------------------------------------------------------------- conversao


def test_preco_vira_centavos_exatos(banco_balanca: Path) -> None:
    """
    61.9 em float e 61.899999...; convertido via str/Decimal precisa dar
    6190 centavos redondos.
    """
    resultado = ler_sqlite_balanca(banco_balanca)
    por_plu, por_ean = para_objetos(resultado)

    assert por_plu[1].preco_kg_centavos == 6190
    assert por_plu[148].preco_kg_centavos == 3690
    assert por_ean["7894900027013"].preco_centavos == 1290
    assert por_ean["7894900010015"].preco_centavos == 550


def test_prefixo_reconstruido_bate_com_a_etiqueta(banco_balanca: Path) -> None:
    resultado = ler_sqlite_balanca(banco_balanca)
    por_plu, _ = para_objetos(resultado)

    assert por_plu[148].prefixo == "2014800"
    assert por_plu[2].prefixo == "2000200"


# -------------------------------------------------------- cache local


def test_gravar_no_cache_local(banco_balanca: Path, banco_pdv: Banco) -> None:
    banco = banco_pdv
    resultado = ler_sqlite_balanca(banco_balanca)

    gravar_no_cache_local(banco, resultado, versao="teste-1")

    conexao = banco.conexao()
    assert conexao.execute("SELECT COUNT(*) FROM catalogo_produto").fetchone()[0] == 5
    assert conexao.execute("SELECT COUNT(*) FROM catalogo_ean").fetchone()[0] == 2
    assert banco.meta("versao") == "teste-1"

    linha = conexao.execute("SELECT * FROM catalogo_produto WHERE plu = 148").fetchone()
    assert linha["nome"] == "FETUTINE"
    assert linha["preco_kg_centavos"] == 3690
    assert linha["prefixo"] == "2014800"
    assert linha["ativo"] == 1


def test_gravar_duas_vezes_substitui_e_nao_duplica(
    banco_balanca: Path, banco_pdv: Banco
) -> None:
    banco = banco_pdv
    resultado = ler_sqlite_balanca(banco_balanca)

    gravar_no_cache_local(banco, resultado, versao="v1")
    gravar_no_cache_local(banco, resultado, versao="v2")

    conexao = banco.conexao()
    assert conexao.execute("SELECT COUNT(*) FROM catalogo_produto").fetchone()[0] == 5
    assert banco.meta("versao") == "v2"


def test_catalogo_gravado_e_lido_pelo_pdv(
    banco_balanca: Path, banco_pdv: Banco
) -> None:
    """
    Fecha o ciclo: gravar no cache e o Catalogo carregar de volta -- e o que
    acontece de verdade no boot do PDV.
    """
    from pdv.catalogo import Catalogo

    banco = banco_pdv
    gravar_no_cache_local(banco, ler_sqlite_balanca(banco_balanca), versao="v1")

    catalogo = Catalogo(banco, None)
    catalogo.iniciar()  # sem Upstash nao sobe thread nenhuma

    assert catalogo.snapshot.origem == "local"
    assert catalogo.snapshot.versao == "v1"

    fetutine = catalogo.buscar_por_plu(148)
    assert fetutine is not None
    assert fetutine.nome == "FETUTINE"
    assert fetutine.preco_kg_centavos == 3690

    coca = catalogo.buscar_por_ean("7894900027013")
    assert coca is not None
    assert coca.preco_centavos == 1290

    assert catalogo.buscar_por_plu(9999) is None
