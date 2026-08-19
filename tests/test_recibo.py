"""
Testes do cupom.

O que mais importa aqui e a LARGURA: o cupom antigo montava linhas de 52
caracteres numa bobina de 48, e a impressora quebrava sozinha no meio do
valor em dinheiro. Todo teste de layout confere `len(linha) <= largura`.
"""

from __future__ import annotations

import pytest

from pdv.carrinho import ItemCarrinho
from pdv.config import DadosLoja
from pdv.fila import VendaGravada
from pdv.recibo import LARGURA_PADRAO, montar_cupom

LOJA = DadosLoja()


def _venda(**ajustes) -> VendaGravada:
    base = {
        "cupom": 1,
        "uuid": "abc-123",
        "criado_em": "2026-08-19T14:37:02-03:00",
        "total_centavos": 5884,
        "forma_pagamento": "dinheiro",
        "recebido_centavos": 10000,
        "troco_centavos": 4116,
        "itens": [
            ItemCarrinho(
                id="i1",
                tipo="peso",
                codigo="2014800009574",
                nome="FETUTINE",
                quantidade=1,
                preco_unitario_centavos=3690,
                subtotal_centavos=957,
                peso_g=259,
                plu=148,
            ),
            ItemCarrinho(
                id="i2",
                tipo="peso",
                codigo="2003400036370",
                nome="FRANGO ASSADO",
                quantidade=1,
                preco_unitario_centavos=3890,
                subtotal_centavos=3637,
                peso_g=935,
                plu=34,
            ),
            ItemCarrinho(
                id="i3",
                tipo="unidade",
                codigo="7894900027013",
                nome="COCA-COLA 2L",
                quantidade=1,
                preco_unitario_centavos=1290,
                subtotal_centavos=1290,
            ),
        ],
        "cpf": None,
    }
    base.update(ajustes)
    return VendaGravada(**base)


# ------------------------------------------------------------------ largura


def test_nenhuma_linha_passa_da_largura() -> None:
    linhas = montar_cupom(_venda(), LOJA)

    excedentes = [
        (i, linha) for i, linha in enumerate(linhas) if len(linha) > LARGURA_PADRAO
    ]
    assert not excedentes, f"linhas maiores que {LARGURA_PADRAO}: {excedentes}"


@pytest.mark.parametrize("largura", [32, 40, 48, 56])
def test_respeita_qualquer_largura_configurada(largura: int) -> None:
    """32 = bobina de 58 mm; 48 = 80 mm."""
    linhas = montar_cupom(_venda(), LOJA, largura=largura)

    assert all(len(linha) <= largura for linha in linhas)


def test_nome_muito_longo_e_cortado_nao_quebra_a_linha() -> None:
    venda = _venda(
        itens=[
            ItemCarrinho(
                id="i1",
                tipo="peso",
                codigo="2014800009574",
                nome="CANELONE DE CARNE COM MOLHO BRANCO E QUEIJO GRATINADO ESPECIAL",
                quantidade=1,
                preco_unitario_centavos=6190,
                subtotal_centavos=12380,
                peso_g=2000,
                plu=1,
            )
        ],
        total_centavos=12380,
    )

    linhas = montar_cupom(venda, LOJA)

    assert all(len(linha) <= LARGURA_PADRAO for linha in linhas)


def test_valor_grande_nao_e_cortado() -> None:
    """Se algo tiver que ser cortado, e o rotulo -- nunca o dinheiro."""
    venda = _venda(
        total_centavos=99999999, recebido_centavos=99999999, troco_centavos=0
    )

    texto = "\n".join(montar_cupom(venda, LOJA))

    assert "R$ 999.999,99" in texto


def test_sufixo_por_kg_aparece_na_bobina_de_80mm() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA, largura=48))

    assert "R$ 36,90/kg" in texto


def test_sufixo_por_kg_sai_inteiro_na_bobina_estreita() -> None:
    """
    Em 32 colunas o "/kg" nao cabe. Ele precisa sair INTEIRO -- cortado no
    meio ("R$ 36,90/") pareceria defeito de impressao para o cliente.
    """
    linhas = montar_cupom(_venda(), LOJA, largura=32)
    texto = "\n".join(linhas)

    assert "R$ 36,90" in texto
    assert "/kg" not in texto
    assert "90/" not in texto, "sufixo cortado no meio"


def test_valor_do_item_nunca_e_cortado_em_bobina_estreita() -> None:
    for largura in (32, 40, 48):
        texto = "\n".join(montar_cupom(_venda(), LOJA, largura=largura))
        assert "R$ 9,57" in texto, f"subtotal perdido em {largura} colunas"
        assert "R$ 36,37" in texto, f"subtotal perdido em {largura} colunas"
        assert "R$ 12,90" in texto, f"subtotal perdido em {largura} colunas"


# ---------------------------------------------------------------- conteudo


def test_cabecalho_tem_os_dados_da_loja() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "CASA DAS MASSAS - PINHEIRINHO" in texto
    assert "32.055.018/0001-87" in texto
    assert "(41) 3268-2817" in texto
    assert "R. Mario Gomes Cezar, 230" in texto


def test_data_e_hora_no_formato_brasileiro() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "DATA: 19/08/2026" in texto
    assert "HORA: 14:37:02" in texto


def test_numero_do_cupom_com_seis_digitos() -> None:
    texto = "\n".join(montar_cupom(_venda(cupom=42), LOJA))

    assert "CUPOM: #000042" in texto
    assert "*** CUPOM 000042 ***" in texto


def test_item_pesado_mostra_peso_e_preco_por_kg() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "FETUTINE" in texto
    assert "259 g" in texto
    assert "R$ 36,90/kg" in texto
    assert "R$ 9,57" in texto


def test_item_pesado_acima_de_um_quilo_em_kg() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "935 g" in texto  # abaixo de 1 kg fica em gramas


def test_item_unitario_mostra_quantidade() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "COCA-COLA 2L" in texto
    assert "1 un" in texto


def test_itens_sao_numerados() -> None:
    linhas = montar_cupom(_venda(), LOJA)
    texto = "\n".join(linhas)

    assert "001   FETUTINE" in texto
    assert "002   FRANGO ASSADO" in texto
    assert "003   COCA-COLA 2L" in texto


def test_total_e_contagem_de_itens() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "3 ITEM(NS)" in texto
    assert "R$ 58,84" in texto


# --------------------------------------------------------------- pagamento


def test_dinheiro_mostra_recebido_e_troco() -> None:
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "DINHEIRO" in texto
    assert "R$ 100,00" in texto
    assert "TROCO:" in texto
    assert "R$ 41,16" in texto


def test_cartao_nao_mostra_troco() -> None:
    venda = _venda(
        forma_pagamento="debito", recebido_centavos=None, troco_centavos=None
    )

    texto = "\n".join(montar_cupom(venda, LOJA))

    assert "CARTAO DEBITO" in texto
    assert "TROCO" not in texto
    assert "RECEBIDO" not in texto


def test_pix() -> None:
    venda = _venda(forma_pagamento="pix", recebido_centavos=None, troco_centavos=None)

    assert "PIX" in "\n".join(montar_cupom(venda, LOJA))


def test_forma_desconhecida_aparece_em_maiuscula() -> None:
    """Nao pode sumir do cupom so porque nao esta no dicionario."""
    venda = _venda(forma_pagamento="vale", recebido_centavos=None, troco_centavos=None)

    assert "VALE" in "\n".join(montar_cupom(venda, LOJA))


# --------------------------------------------------------------------- CPF


def test_cpf_formatado() -> None:
    texto = "\n".join(montar_cupom(_venda(cpf="13621614974"), LOJA))

    assert "136.216.149-74" in texto


def test_cnpj_formatado() -> None:
    texto = "\n".join(montar_cupom(_venda(cpf="32055018000187"), LOJA))

    assert "32.055.018/0001-87" in texto


def test_sem_cpf_nao_imprime_a_linha() -> None:
    texto = "\n".join(montar_cupom(_venda(cpf=None), LOJA))

    assert "CPF/CNPJ:" not in texto


# ------------------------------------------------------------------ rodape


def test_rodape_avisa_que_nao_e_fiscal() -> None:
    """
    O cupom nao e documento fiscal. Precisa estar escrito, sempre -- e o que
    separa um comprovante de venda de uma nota falsa.
    """
    texto = "\n".join(montar_cupom(_venda(), LOJA))

    assert "** CUPOM NAO FISCAL **" in texto


def test_carrinho_de_um_item_so() -> None:
    venda = _venda(
        itens=[
            ItemCarrinho(
                id="i1",
                tipo="unidade",
                codigo="7894900010015",
                nome="COCA-COLA 350ml",
                quantidade=1,
                preco_unitario_centavos=550,
                subtotal_centavos=550,
            )
        ],
        total_centavos=550,
        recebido_centavos=1000,
        troco_centavos=450,
    )

    linhas = montar_cupom(venda, LOJA)

    assert "1 ITEM(NS)" in "\n".join(linhas)
    assert all(len(linha) <= LARGURA_PADRAO for linha in linhas)
