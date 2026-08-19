"""
Fixtures comuns.

Todo teste roda contra um PDV completo, mas com banco em pasta temporaria e
SEM Upstash configurado -- nenhum teste toca a rede. E tambem a prova de que
o PDV funciona 100% offline, que e um requisito e nao um detalhe.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pdv.catalogo import ProdutoPeso, ProdutoUnidade, Snapshot
from pdv.codigo_barras import digito_verificador_ean13
from pdv.config import Config
from pdv.db import Banco
from pdv.web import Aplicacao, criar_app


def codigo_balanca(plu: int, centavos: int) -> str:
    """
    Monta uma etiqueta de balanca VALIDA para os testes.

    Existe porque calcular o digito verificador a mao dentro do teste e um
    convite ao falso positivo: um codigo com mod10 errado e recusado no
    parser e o teste "passa" sem nunca chegar na regra que ele queria testar.
    """
    if not 0 <= centavos <= 99999:
        raise ValueError("centavos fora da faixa de 5 digitos")
    doze = f"2{plu:04d}{centavos:07d}"
    return doze + str(digito_verificador_ean13(doze))


# Catalogo de teste com nomes e precos reais da loja (do produtos-export.json).
PRODUTOS_PESO = [
    ProdutoPeso(plu=148, nome="FETUTINE", preco_kg_centavos=3190),
    ProdutoPeso(plu=34, nome="FRANGO ASSADO", preco_kg_centavos=3490),
    ProdutoPeso(plu=2, nome="CANELONE P/Q", preco_kg_centavos=6190),
    ProdutoPeso(plu=69, nome="LASANHA BOLONHESA", preco_kg_centavos=5990),
    ProdutoPeso(plu=153, nome="MACARRAO", preco_kg_centavos=7500),
    ProdutoPeso(plu=12, nome="CAPELETI", preco_kg_centavos=6990),
    ProdutoPeso(plu=99, nome="PRODUTO INATIVO", preco_kg_centavos=1000, ativo=False),
]

PRODUTOS_UNIDADE = [
    ProdutoUnidade(codigo="7894900027013", nome="COCA-COLA 2L", preco_centavos=1290),
    ProdutoUnidade(codigo="7894900010015", nome="COCA-COLA 350ml", preco_centavos=550),
    ProdutoUnidade(
        codigo="7891000000001", nome="AGUA MINERAL", preco_centavos=350, ativo=False
    ),
]


@pytest.fixture
def banco_pdv(tmp_path: Path) -> Iterator[Banco]:
    """
    Banco local do PDV, fechado no fim do teste.

    Fechar importa: conexao sqlite abandonada solta ResourceWarning quando o
    coletor de lixo passa, e como o pytest esta configurado com
    `filterwarnings = error`, esse aviso apareceria como falha em QUALQUER
    teste que estivesse rodando naquele momento -- um mistério perfeito.
    """
    with Banco(tmp_path / "pdv.db") as banco:
        yield banco


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        banco=tmp_path / "pdv.db",
        pasta_cupons=tmp_path / "cupons",
        pasta_nf=tmp_path / "notas",
        upstash_url="",
        upstash_token="",
        imprimir_habilitado=False,  # nao mexe na impressora da maquina
        digitos_preco=5,
    )


@pytest.fixture
def pdv(config: Config) -> Iterator[Aplicacao]:
    """
    PDV montado e COM as threads de fundo rodando.

    `iniciar()` vem antes de injetar o catalogo de teste porque ele carrega o
    cache do SQLite (vazio aqui) e sobrescreveria o snapshot. Sem Upstash
    configurado, as threads de catalogo e de fila saem na hora; a de
    impressao sobe -- e e ela que os testes de cupom precisam.
    """
    aplicacao = Aplicacao(config)
    aplicacao.iniciar()
    aplicacao.catalogo._snapshot = Snapshot(
        versao="teste-1",
        por_plu={p.plu: p for p in PRODUTOS_PESO},
        por_ean={u.codigo: u for u in PRODUTOS_UNIDADE},
        atualizado_em="2026-08-19T10:00:00-03:00",
        origem="teste",
    )
    yield aplicacao
    aplicacao.parar()


@pytest.fixture
def cliente(config: Config, pdv: Aplicacao):
    """Cliente HTTP de teste do Flask, ligado ao mesmo PDV da fixture `pdv`."""
    app = criar_app(config, pdv)
    app.config.update(TESTING=True)
    with app.test_client() as teste:
        yield teste
