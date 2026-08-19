"""
Testes do parser de codigo de barras.

Os 6 primeiros casos sao etiquetas reais da balanca da loja, conferidas a
mao. Eles sao o contrato: se um deles quebrar, o PDV esta cobrando errado.
"""

from __future__ import annotations

import dataclasses

import pytest

from pdv.codigo_barras import (
    CODIGO_PRODUTO_POR_KG,
    TipoLeitura,
    digito_verificador_ean13,
    ean13_valido,
    interpretar,
    peso_gramas,
    prefixo_de_plu,
)

# (codigo, plu esperado, total em centavos esperado)
ETIQUETAS_REAIS = [
    ("2014800009574", 148, 957),
    ("2003400036370", 34, 3637),
    ("2006900039025", 69, 3902),
    ("2001200045417", 12, 4541),
    ("2015300049480", 153, 4948),
    ("2000200013884", 2, 1388),
]


# --------------------------------------------------------------------------
# Casos reais
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("codigo", "plu", "centavos"), ETIQUETAS_REAIS)
def test_etiquetas_reais_da_balanca(codigo: str, plu: int, centavos: int) -> None:
    leitura = interpretar(codigo)

    assert leitura.tipo is TipoLeitura.BALANCA
    assert leitura.aceita
    assert leitura.plu == plu
    assert leitura.total_centavos == centavos
    assert leitura.codigo == codigo
    assert leitura.motivo is None
    assert leitura.aviso is None


@pytest.mark.parametrize(("codigo", "plu", "centavos"), ETIQUETAS_REAIS)
def test_etiquetas_reais_dao_o_mesmo_valor_com_4_digitos(
    codigo: str, plu: int, centavos: int
) -> None:
    """
    As 6 etiquetas reais tem "0" na posicao 8, entao ler 4 ou 5 digitos de
    preco da o mesmo resultado. Este teste trava essa equivalencia: e o que
    permite rodar em modo 5 digitos sem contrariar a especificacao escrita.
    """
    leitura = interpretar(codigo, digitos_preco=4)

    assert leitura.plu == plu
    assert leitura.total_centavos == centavos
    assert leitura.aviso is None


@pytest.mark.parametrize(("codigo", "plu", "_centavos"), ETIQUETAS_REAIS)
def test_prefixo_bate_com_a_chave_do_catalogo_legado(
    codigo: str, plu: int, _centavos: int
) -> None:
    """O catalogo antigo indexa por "2" + PLU + "00" (7 digitos)."""
    leitura = interpretar(codigo)

    assert leitura.prefixo == codigo[:7]
    assert leitura.prefixo == prefixo_de_plu(plu)


def test_valores_em_reais_para_exibicao() -> None:
    assert interpretar("2014800009574").total_reais == pytest.approx(9.57)
    assert interpretar("2003400036370").total_reais == pytest.approx(36.37)
    assert interpretar("2015300049480").total_reais == pytest.approx(49.48)


# --------------------------------------------------------------------------
# Digito verificador
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("codigo", "_plu", "_centavos"), ETIQUETAS_REAIS)
def test_todas_as_etiquetas_reais_fecham_o_mod10(
    codigo: str, _plu: int, _centavos: int
) -> None:
    assert ean13_valido(codigo)
    assert digito_verificador_ean13(codigo[:12]) == int(codigo[12])


def test_digito_verificador_de_ean_conhecido() -> None:
    # Coca-Cola 2L, que ja aparece no historico de vendas da loja.
    assert ean13_valido("7894900027013")
    assert digito_verificador_ean13("789490002701") == 3


def test_digito_verificador_exige_12_digitos() -> None:
    with pytest.raises(ValueError):
        digito_verificador_ean13("123")
    with pytest.raises(ValueError):
        digito_verificador_ean13("12345678901a")


def test_ean13_valido_recusa_tamanho_e_letras() -> None:
    assert not ean13_valido("201480000957")  # 12 digitos
    assert not ean13_valido("20148000095744")  # 14 digitos
    assert not ean13_valido("201480000957X")


# --------------------------------------------------------------------------
# Erros: etiqueta de balanca corrompida
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codigo",
    [
        "2014800009575",  # verificador certo seria 4
        "2003400036371",  # verificador certo seria 0
        "2006900039020",  # verificador certo seria 5
        "2001200045410",  # verificador certo seria 7
        "2015300049481",  # verificador certo seria 0
        "2000200013880",  # verificador certo seria 4
    ],
)
def test_etiqueta_de_balanca_com_verificador_errado_e_recusada(codigo: str) -> None:
    leitura = interpretar(codigo)

    assert leitura.tipo is TipoLeitura.INVALIDA
    assert not leitura.aceita
    assert leitura.total_centavos is None, "nao pode vazar valor de leitura suja"
    assert leitura.plu is None
    assert "verificador" in leitura.motivo.lower()


def test_mensagem_de_erro_diz_qual_digito_era_esperado() -> None:
    leitura = interpretar("2014800009575")

    assert "termina em 5" in leitura.motivo
    assert "dava 4" in leitura.motivo


def test_um_digito_trocado_no_meio_tambem_e_pego() -> None:
    """Troca no campo de preco: 0957 -> 0857. O mod10 nao fecha mais."""
    leitura = interpretar("2014800008574")

    assert leitura.tipo is TipoLeitura.INVALIDA


# --------------------------------------------------------------------------
# Codigos de prateleira
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codigo",
    [
        "7894900027013",  # Coca-Cola 2L
        "7894900010015",  # Coca-Cola 350ml
        "7891000315507",
    ],
)
def test_ean_de_prateleira_vai_para_busca_exata(codigo: str) -> None:
    leitura = interpretar(codigo)

    assert leitura.tipo is TipoLeitura.EAN
    assert leitura.aceita
    assert leitura.codigo == codigo
    assert leitura.plu is None
    assert leitura.total_centavos is None


def test_codigo_comecando_com_2_mas_sem_13_digitos_e_prateleira() -> None:
    """Codigo interno curto: nao e etiqueta de balanca, e busca exata."""
    leitura = interpretar("2007500")

    assert leitura.tipo is TipoLeitura.EAN
    assert leitura.codigo == "2007500"


def test_codigo_nao_numerico_e_tratado_como_prateleira() -> None:
    """Code128 alfanumerico: deixa o catalogo dizer se existe ou nao."""
    leitura = interpretar("ABC-123")

    assert leitura.tipo is TipoLeitura.EAN
    assert leitura.codigo == "ABC-123"


def test_ean_de_prateleira_nao_precisa_de_mod10_valido() -> None:
    """
    A especificacao manda buscar por codigo exato: quem decide se existe e
    o catalogo, nao o mod10. Rejeitar aqui esconderia produtos cadastrados
    com codigo interno.
    """
    leitura = interpretar("7894900027010")  # verificador errado de proposito

    assert leitura.tipo is TipoLeitura.EAN


# --------------------------------------------------------------------------
# Etiqueta generica por kg
# --------------------------------------------------------------------------


def test_produto_por_kg_pede_peso_na_mao() -> None:
    leitura = interpretar(CODIGO_PRODUTO_POR_KG)

    assert leitura.tipo is TipoLeitura.PRODUTO_POR_KG
    assert leitura.aceita
    assert leitura.total_centavos is None
    assert leitura.prefixo == "2000000"


# --------------------------------------------------------------------------
# Normalizacao da entrada do leitor
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bruto",
    [
        "2014800009574\r\n",
        "  2014800009574  ",
        "2014800009574\n",
        "2014 8000 0957 4",
        "\t2014800009574\t",
    ],
)
def test_ruido_do_leitor_hid_e_limpo(bruto: str) -> None:
    leitura = interpretar(bruto)

    assert leitura.tipo is TipoLeitura.BALANCA
    assert leitura.codigo == "2014800009574"
    assert leitura.total_centavos == 957


@pytest.mark.parametrize("bruto", ["", "   ", "\r\n", "\t"])
def test_leitura_vazia_e_invalida(bruto: str) -> None:
    leitura = interpretar(bruto)

    assert leitura.tipo is TipoLeitura.INVALIDA
    assert not leitura.aceita
    assert "vazia" in leitura.motivo.lower()


# --------------------------------------------------------------------------
# Largura do campo de preco (4 vs 5 digitos)
# --------------------------------------------------------------------------


def test_etiqueta_acima_de_100_reais_com_5_digitos() -> None:
    """
    2 kg de CANELONE CARNE a R$ 61,90/kg = R$ 123,80.
    Em 5 digitos o valor aparece inteiro.
    """
    codigo = _com_verificador("201530012380")
    leitura = interpretar(codigo, digitos_preco=5)

    assert leitura.total_centavos == 12380
    assert leitura.aviso is None


def test_etiqueta_acima_de_100_reais_com_4_digitos_avisa() -> None:
    """Em 4 digitos o mesmo valor perde os R$ 100 -- e precisa gritar."""
    codigo = _com_verificador("201530012380")
    leitura = interpretar(codigo, digitos_preco=4)

    assert leitura.total_centavos == 2380
    assert leitura.aviso is not None
    assert "100,00" in leitura.aviso


def test_largura_de_preco_invalida_e_erro_de_programacao() -> None:
    for largura in (0, 3, 6, 12):
        with pytest.raises(ValueError):
            interpretar("2014800009574", digitos_preco=largura)


def test_teto_de_cada_modo() -> None:
    cinco = interpretar(_com_verificador("201530099999"), digitos_preco=5)
    assert cinco.total_centavos == 99999  # R$ 999,99

    quatro = interpretar(_com_verificador("201530009999"), digitos_preco=4)
    assert quatro.total_centavos == 9999  # R$ 99,99


# --------------------------------------------------------------------------
# Peso derivado
# --------------------------------------------------------------------------


def test_peso_sai_da_divisao_pelo_preco_por_kg() -> None:
    # FETUTINE: R$ 9,57 a R$ 31,90/kg -> 300 g
    assert peso_gramas(957, 3190) == 300


def test_peso_de_etiqueta_real_de_frango() -> None:
    # FRANGO ASSADO: R$ 36,37 a R$ 34,90/kg -> ~1042 g
    assert peso_gramas(3637, 3490) == 1042


def test_peso_sem_preco_por_kg_e_none_nao_zero() -> None:
    assert peso_gramas(957, 0) is None
    assert peso_gramas(957, -1) is None


def test_peso_arredonda_para_o_grama_mais_proximo() -> None:
    assert peso_gramas(1000, 3000) == 333  # 333,33 g


# --------------------------------------------------------------------------
# Garantias estruturais
# --------------------------------------------------------------------------


def test_leitura_e_imutavel() -> None:
    """Leitura e frozen: ninguem altera um valor de dinheiro depois de lido."""
    leitura = interpretar("2014800009574")

    with pytest.raises(dataclasses.FrozenInstanceError):
        leitura.plu = 999  # type: ignore[misc]


def test_prefixo_de_plu_valida_faixa() -> None:
    assert prefixo_de_plu(2) == "2000200"
    assert prefixo_de_plu(9999) == "2999900"

    with pytest.raises(ValueError):
        prefixo_de_plu(10000)
    with pytest.raises(ValueError):
        prefixo_de_plu(-1)


def test_toda_leitura_recusada_traz_motivo_legivel() -> None:
    for bruto in ["", "2014800009575"]:
        leitura = interpretar(bruto)
        assert leitura.tipo is TipoLeitura.INVALIDA
        assert leitura.motivo
        assert leitura.motivo.endswith(".")


def test_nenhuma_leitura_aceita_traz_motivo() -> None:
    for bruto in ETIQUETAS_REAIS:
        assert interpretar(bruto[0]).motivo is None


# --------------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------------


def _com_verificador(doze_digitos: str) -> str:
    """Fecha um codigo de 12 digitos com o verificador correto."""
    return doze_digitos + str(digito_verificador_ean13(doze_digitos))


def test_apoio_com_verificador_gera_codigo_valido() -> None:
    """O helper dos testes tambem precisa estar certo."""
    assert _com_verificador("201480000957") == "2014800009574"
    assert ean13_valido(_com_verificador("201530012380"))
