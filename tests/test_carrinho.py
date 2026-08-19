"""Testes do carrinho: onde o dinheiro e somado."""

from __future__ import annotations

import pytest

from pdv.carrinho import MAX_ITENS, Carrinho, ErroCarrinho, calcular_troco
from pdv.catalogo import ProdutoPeso, ProdutoUnidade

FETUTINE = ProdutoPeso(plu=148, nome="FETUTINE", preco_kg_centavos=3190)
FRANGO = ProdutoPeso(plu=34, nome="FRANGO ASSADO", preco_kg_centavos=3490)
COCA_2L = ProdutoUnidade(
    codigo="7894900027013", nome="COCA-COLA 2L", preco_centavos=1290
)


@pytest.fixture
def carrinho() -> Carrinho:
    return Carrinho()


# --------------------------------------------------------------- item pesado


def test_subtotal_do_item_pesado_vem_da_etiqueta(carrinho: Carrinho) -> None:
    """
    A etiqueta manda. Se recalculassemos `preco_kg * peso`, o arredondamento
    daria diferenca de centavo do que esta impresso e o cliente reclamaria.
    """
    item = carrinho.adicionar_pesado(FETUTINE, 957, "2014800009574")

    assert item.subtotal_centavos == 957
    assert item.preco_unitario_centavos == 3190
    assert item.peso_g == 300
    assert item.plu == 148
    assert carrinho.total_centavos == 957


def test_duas_etiquetas_do_mesmo_produto_sao_duas_linhas(carrinho: Carrinho) -> None:
    """Cada embalagem pesada e unica: nao pode agrupar."""
    carrinho.adicionar_pesado(FETUTINE, 957, "2014800009574")
    carrinho.adicionar_pesado(FETUTINE, 2574, "2014800025748")

    assert len(carrinho.itens) == 2
    assert carrinho.total_centavos == 3531


def test_etiqueta_com_valor_zero_e_recusada(carrinho: Carrinho) -> None:
    with pytest.raises(ErroCarrinho, match="valor zero"):
        carrinho.adicionar_pesado(FETUTINE, 0, "2014800000006")

    assert carrinho.vazio


# ------------------------------------------------------- item pesado manual


def test_peso_manual_calcula_o_subtotal(carrinho: Carrinho) -> None:
    """Sem etiqueta nao ha valor impresso, entao aqui o calculo e nosso."""
    item = carrinho.adicionar_pesado_manual(FRANGO, 1000)

    assert item.subtotal_centavos == 3490
    assert item.peso_g == 1000


def test_peso_manual_arredonda_para_o_centavo(carrinho: Carrinho) -> None:
    # 333 g a R$ 31,90/kg = R$ 10,6227 -> R$ 10,62
    item = carrinho.adicionar_pesado_manual(FETUTINE, 333)

    assert item.subtotal_centavos == 1062


@pytest.mark.parametrize("gramas", [0, -1, -500])
def test_peso_manual_precisa_ser_positivo(carrinho: Carrinho, gramas: int) -> None:
    with pytest.raises(ErroCarrinho, match="maior que zero"):
        carrinho.adicionar_pesado_manual(FETUTINE, gramas)


def test_peso_manual_absurdo_e_barrado(carrinho: Carrinho) -> None:
    """Dedo escorregado no teclado: 50 kg de massa nao e uma venda."""
    with pytest.raises(ErroCarrinho, match="50 kg"):
        carrinho.adicionar_pesado_manual(FETUTINE, 60_000)


# ------------------------------------------------------------ item unitario


def test_ler_o_mesmo_ean_duas_vezes_soma_na_mesma_linha(carrinho: Carrinho) -> None:
    carrinho.adicionar_unidade(COCA_2L)
    item = carrinho.adicionar_unidade(COCA_2L)

    assert len(carrinho.itens) == 1
    assert item.quantidade == 2
    assert item.subtotal_centavos == 2580
    assert carrinho.total_centavos == 2580


def test_quantidade_maior_que_um_de_uma_vez(carrinho: Carrinho) -> None:
    item = carrinho.adicionar_unidade(COCA_2L, 3)

    assert item.quantidade == 3
    assert item.subtotal_centavos == 3870


def test_quantidade_zero_ou_negativa_e_recusada(carrinho: Carrinho) -> None:
    for quantidade in (0, -2):
        with pytest.raises(ErroCarrinho):
            carrinho.adicionar_unidade(COCA_2L, quantidade)


def test_teto_de_quantidade_por_linha(carrinho: Carrinho) -> None:
    carrinho.adicionar_unidade(COCA_2L, 999)

    with pytest.raises(ErroCarrinho, match="maxima"):
        carrinho.adicionar_unidade(COCA_2L)


# ------------------------------------------------------------------ remocao


def test_remover_por_id(carrinho: Carrinho) -> None:
    primeiro = carrinho.adicionar_pesado(FETUTINE, 957, "2014800009574")
    carrinho.adicionar_unidade(COCA_2L)

    removido = carrinho.remover(primeiro.id)

    assert removido.id == primeiro.id
    assert len(carrinho.itens) == 1
    assert carrinho.total_centavos == 1290


def test_remover_id_inexistente_reclama(carrinho: Carrinho) -> None:
    with pytest.raises(ErroCarrinho, match="nao esta mais"):
        carrinho.remover("nao-existe")


def test_remover_duas_vezes_o_mesmo_id_reclama_na_segunda(carrinho: Carrinho) -> None:
    item = carrinho.adicionar_unidade(COCA_2L)
    carrinho.remover(item.id)

    with pytest.raises(ErroCarrinho):
        carrinho.remover(item.id)


def test_limpar_devolve_quantas_linhas_sairam(carrinho: Carrinho) -> None:
    carrinho.adicionar_pesado(FETUTINE, 957, "2014800009574")
    carrinho.adicionar_unidade(COCA_2L, 2)

    assert carrinho.limpar() == 2
    assert carrinho.vazio
    assert carrinho.total_centavos == 0
    assert carrinho.limpar() == 0


def test_teto_de_itens_no_carrinho(carrinho: Carrinho) -> None:
    """Trava contra leitor em loop enviando o mesmo codigo sem parar."""
    for _ in range(MAX_ITENS):
        carrinho.adicionar_pesado(FETUTINE, 100, "2014800001001")

    with pytest.raises(ErroCarrinho, match=str(MAX_ITENS)):
        carrinho.adicionar_pesado(FETUTINE, 100, "2014800001001")


# ------------------------------------------------------------------- totais


def test_total_soma_pesados_e_unitarios(carrinho: Carrinho) -> None:
    carrinho.adicionar_pesado(FETUTINE, 957, "2014800009574")
    carrinho.adicionar_pesado(FRANGO, 3637, "2003400036370")
    carrinho.adicionar_unidade(COCA_2L, 2)

    assert carrinho.total_centavos == 957 + 3637 + 2580


def test_total_em_centavos_nao_acumula_erro_de_float(carrinho: Carrinho) -> None:
    """
    O caso classico: 0,10 + 0,20 em float da 0,30000000000000004. Com centavos
    inteiros, 100 itens de 10 centavos dao exatamente R$ 10,00.
    """
    for _ in range(100):
        carrinho.adicionar_pesado(FETUTINE, 10, "2014800000109")

    assert carrinho.total_centavos == 1000


def test_json_do_carrinho_traz_texto_pronto(carrinho: Carrinho) -> None:
    carrinho.adicionar_pesado(FETUTINE, 957, "2014800009574")
    carrinho.adicionar_unidade(COCA_2L, 2)

    dados = carrinho.para_json()

    assert dados["total_texto"] == "R$ 35,37"  # 9,57 + 2 x 12,90
    assert dados["quantidade_itens"] == 2
    assert dados["vazio"] is False
    assert dados["itens"][0]["quantidade_texto"] == "300 g"
    assert dados["itens"][0]["unidade"] == "kg"
    assert dados["itens"][1]["quantidade_texto"] == "2 un"


def test_json_de_carrinho_vazio(carrinho: Carrinho) -> None:
    dados = carrinho.para_json()

    assert dados["vazio"] is True
    assert dados["total_texto"] == "R$ 0,00"
    assert dados["itens"] == []


def test_itens_devolve_copia_nao_a_lista_interna(carrinho: Carrinho) -> None:
    """Quem recebe `itens` nao pode mexer no carrinho por acidente."""
    carrinho.adicionar_unidade(COCA_2L)
    lista = carrinho.itens
    lista.clear()

    assert len(carrinho.itens) == 1


# -------------------------------------------------------------------- troco


def test_troco_normal() -> None:
    assert calcular_troco(12149, 15000) == 2851


def test_troco_exato_e_zero() -> None:
    assert calcular_troco(5000, 5000) == 0


def test_recebido_menor_que_o_total_e_erro() -> None:
    with pytest.raises(ErroCarrinho, match=r"faltam R\$ 5,00"):
        calcular_troco(5000, 4500)
