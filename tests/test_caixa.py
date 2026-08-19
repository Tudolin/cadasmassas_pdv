"""
Testes de ponta a ponta da tela de caixa, pelas rotas HTTP.

Cobre o fluxo real do operador: bipa, confere, escolhe pagamento, finaliza.
Tudo com Upstash desligado -- e tambem a prova de que o PDV vende offline.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pdv.web import Aplicacao

from .conftest import codigo_balanca


def _ler(cliente: Any, codigo: str) -> dict[str, Any]:
    return cliente.post("/api/ler", json={"codigo": codigo}).get_json()


# ------------------------------------------------------------ tela e leitura


def test_tela_do_caixa_abre(cliente: Any) -> None:
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert b"Codigo de barras" in resposta.data


def test_healthz_responde(cliente: Any) -> None:
    assert cliente.get("/healthz").get_json() == {"ok": True}


def test_ler_etiqueta_de_balanca_adiciona_ao_carrinho(cliente: Any) -> None:
    dados = _ler(cliente, "2014800009574")

    assert dados["ok"] is True
    assert dados["item"]["nome"] == "FETUTINE"
    assert dados["item"]["subtotal_texto"] == "R$ 9,57"
    assert dados["item"]["peso_texto"] == "300 g"
    assert dados["carrinho"]["total_texto"] == "R$ 9,57"


@pytest.mark.parametrize(
    ("codigo", "nome", "total"),
    [
        ("2014800009574", "FETUTINE", "R$ 9,57"),
        ("2003400036370", "FRANGO ASSADO", "R$ 36,37"),
        ("2000200013884", "CANELONE P/Q", "R$ 13,88"),
        ("2006900039025", "LASANHA BOLONHESA", "R$ 39,02"),
        ("2015300049480", "MACARRAO", "R$ 49,48"),
        ("2001200045417", "CAPELETI", "R$ 45,41"),
    ],
)
def test_as_seis_etiquetas_reais_entram_pelo_caixa(
    cliente: Any, codigo: str, nome: str, total: str
) -> None:
    """Os mesmos 6 codigos do parser, agora atravessando o app inteiro."""
    dados = _ler(cliente, codigo)

    assert dados["ok"] is True, dados["mensagem"]
    assert dados["item"]["nome"] == nome
    assert dados["item"]["subtotal_texto"] == total


def test_ler_ean_de_prateleira(cliente: Any) -> None:
    dados = _ler(cliente, "7894900027013")

    assert dados["ok"] is True
    assert dados["item"]["nome"] == "COCA-COLA 2L"
    assert dados["item"]["quantidade_texto"] == "1 un"


def test_digito_verificador_invalido_nao_entra_no_carrinho(cliente: Any) -> None:
    dados = _ler(cliente, "2014800009575")

    assert dados["ok"] is False
    assert "verificador" in dados["mensagem"].lower()
    assert dados["carrinho"]["vazio"] is True


def test_plu_fora_do_catalogo_avisa_e_nao_adiciona(cliente: Any) -> None:
    # PLU 777 nao existe no catalogo de teste; codigo com mod10 valido.
    dados = _ler(cliente, codigo_balanca(777, 1000))

    assert dados["ok"] is False
    assert "777" in dados["mensagem"]
    assert dados["carrinho"]["vazio"] is True


def test_ean_desconhecido_avisa(cliente: Any) -> None:
    dados = _ler(cliente, "1111111111116")

    assert dados["ok"] is False
    assert "nao encontrado" in dados["mensagem"]


def test_produto_inativo_nao_e_vendido(cliente: Any) -> None:
    """PLU 99 esta no catalogo com ativo=False."""
    dados = _ler(cliente, codigo_balanca(99, 1000))

    assert dados["ok"] is False
    assert dados["carrinho"]["vazio"] is True


def test_ean_inativo_nao_e_vendido(cliente: Any) -> None:
    dados = _ler(cliente, "7891000000001")

    assert dados["ok"] is False


def test_etiqueta_generica_por_kg_pede_o_produto(cliente: Any) -> None:
    dados = _ler(cliente, "2000000")

    assert dados["ok"] is False
    assert dados["pedir_peso"] is True


def test_codigo_vazio_nao_quebra(cliente: Any) -> None:
    dados = _ler(cliente, "   ")

    assert dados["ok"] is False
    assert dados["carrinho"]["vazio"] is True


def test_leitura_sem_corpo_json_nao_quebra(cliente: Any) -> None:
    resposta = cliente.post("/api/ler")

    assert resposta.status_code == 200
    assert resposta.get_json()["ok"] is False


# ---------------------------------------------------------------- carrinho


def test_remover_item_pela_rota(cliente: Any) -> None:
    item = _ler(cliente, "2014800009574")["item"]
    _ler(cliente, "7894900027013")

    dados = cliente.post("/api/carrinho/remover", json={"id": item["id"]}).get_json()

    assert dados["ok"] is True
    assert dados["carrinho"]["quantidade_itens"] == 1
    assert dados["carrinho"]["total_texto"] == "R$ 12,90"


def test_limpar_carrinho_pela_rota(cliente: Any) -> None:
    _ler(cliente, "2014800009574")
    _ler(cliente, "2003400036370")

    dados = cliente.post("/api/carrinho/limpar", json={}).get_json()

    assert dados["ok"] is True
    assert dados["carrinho"]["vazio"] is True


def test_peso_manual_pela_rota(cliente: Any) -> None:
    dados = cliente.post(
        "/api/carrinho/peso", json={"plu": 34, "peso_g": 1500}
    ).get_json()

    assert dados["ok"] is True
    assert dados["item"]["nome"] == "FRANGO ASSADO"
    assert dados["item"]["subtotal_texto"] == "R$ 52,35"
    assert dados["item"]["peso_texto"] == "1,500 kg"


def test_peso_manual_aceita_kg_com_virgula(cliente: Any) -> None:
    dados = cliente.post(
        "/api/carrinho/peso", json={"plu": 148, "peso_kg": "0,300"}
    ).get_json()

    assert dados["ok"] is True
    assert dados["item"]["peso_texto"] == "300 g"


def test_peso_manual_sem_peso_reclama(cliente: Any) -> None:
    dados = cliente.post("/api/carrinho/peso", json={"plu": 148}).get_json()

    assert dados["ok"] is False
    assert "peso" in dados["mensagem"].lower()


def test_busca_por_nome_encontra_sem_acento_e_sem_caixa(cliente: Any) -> None:
    dados = cliente.get("/api/buscar?q=canelone").get_json()

    assert dados["ok"] is True
    assert any(p["nome"] == "CANELONE P/Q" for p in dados["resultados"])


def test_busca_ignora_termo_curto(cliente: Any) -> None:
    assert cliente.get("/api/buscar?q=c").get_json()["resultados"] == []


def test_busca_nao_devolve_inativos(cliente: Any) -> None:
    dados = cliente.get("/api/buscar?q=inativo").get_json()

    assert dados["resultados"] == []


# ---------------------------------------------------------------- checkout


def test_checkout_em_dinheiro_calcula_troco(cliente: Any) -> None:
    _ler(cliente, "2014800009574")  # 9,57
    _ler(cliente, "2003400036370")  # 36,37

    dados = cliente.post(
        "/api/checkout", json={"forma_pagamento": "dinheiro", "recebido": "50,00"}
    ).get_json()

    assert dados["ok"] is True
    assert dados["venda"]["total_texto"] == "R$ 45,94"
    assert dados["venda"]["troco_texto"] == "R$ 4,06"
    assert dados["venda"]["cupom"] == 1
    # Carrinho zerado: o caixa fica pronto para o proximo cliente.
    assert dados["carrinho"]["vazio"] is True


def test_checkout_no_pix_nao_pede_recebido(cliente: Any) -> None:
    _ler(cliente, "7894900027013")

    dados = cliente.post("/api/checkout", json={"forma_pagamento": "pix"}).get_json()

    assert dados["ok"] is True
    assert dados["venda"]["troco_texto"] is None


def test_checkout_em_dinheiro_sem_recebido_e_recusado(cliente: Any) -> None:
    _ler(cliente, "7894900027013")

    dados = cliente.post(
        "/api/checkout", json={"forma_pagamento": "dinheiro"}
    ).get_json()

    assert dados["ok"] is False
    # O carrinho NAO pode ser perdido num erro de digitacao.
    assert dados["carrinho"]["quantidade_itens"] == 1


def test_checkout_com_dinheiro_insuficiente_e_recusado(cliente: Any) -> None:
    _ler(cliente, "2003400036370")  # 36,37

    dados = cliente.post(
        "/api/checkout", json={"forma_pagamento": "dinheiro", "recebido": "10,00"}
    ).get_json()

    assert dados["ok"] is False
    assert "faltam" in dados["mensagem"]
    assert dados["carrinho"]["quantidade_itens"] == 1


def test_checkout_com_carrinho_vazio_e_recusado(cliente: Any) -> None:
    dados = cliente.post("/api/checkout", json={"forma_pagamento": "pix"}).get_json()

    assert dados["ok"] is False
    assert "vazio" in dados["mensagem"]


def test_checkout_com_forma_invalida_e_recusado(cliente: Any) -> None:
    _ler(cliente, "7894900027013")

    dados = cliente.post("/api/checkout", json={"forma_pagamento": "cheque"}).get_json()

    assert dados["ok"] is False
    assert dados["carrinho"]["quantidade_itens"] == 1


def test_cupons_sao_sequenciais(cliente: Any) -> None:
    numeros = []
    for _ in range(3):
        _ler(cliente, "7894900027013")
        dados = cliente.post(
            "/api/checkout", json={"forma_pagamento": "pix"}
        ).get_json()
        numeros.append(dados["venda"]["cupom"])

    assert numeros == [1, 2, 3]


def test_cpf_valido_entra_na_venda(cliente: Any, pdv: Aplicacao) -> None:
    _ler(cliente, "7894900027013")

    cliente.post(
        "/api/checkout",
        json={"forma_pagamento": "pix", "cpf": "136.216.149-74"},
    )

    linha = (
        pdv.banco.conexao()
        .execute("SELECT payload FROM venda WHERE cupom = 1")
        .fetchone()
    )
    assert json.loads(linha["payload"])["cpf"] == "13621614974"


def test_cpf_com_tamanho_errado_e_descartado(cliente: Any, pdv: Aplicacao) -> None:
    """Melhor cupom sem CPF do que cupom com CPF invalido impresso."""
    _ler(cliente, "7894900027013")

    cliente.post("/api/checkout", json={"forma_pagamento": "pix", "cpf": "123"})

    linha = (
        pdv.banco.conexao()
        .execute("SELECT payload FROM venda WHERE cupom = 1")
        .fetchone()
    )
    assert json.loads(linha["payload"])["cpf"] is None


# --------------------------------------------------- persistencia da venda


def test_venda_fica_gravada_e_pendente_de_envio(cliente: Any, pdv: Aplicacao) -> None:
    """
    O coracao do offline-first: a venda esta no SQLite e marcada como nao
    sincronizada, esperando a fila.
    """
    _ler(cliente, "2014800009574")
    cliente.post("/api/checkout", json={"forma_pagamento": "pix"})

    linha = (
        pdv.banco.conexao().execute("SELECT * FROM venda WHERE cupom = 1").fetchone()
    )

    assert linha["sincronizado"] == 0
    assert linha["total_centavos"] == 957
    assert linha["forma_pagamento"] == "pix"
    assert linha["uuid"]

    payload = json.loads(linha["payload"])
    assert payload["total"] == 9.57
    assert payload["itens"][0]["nome"] == "FETUTINE"
    assert payload["itens"][0]["peso_g"] == 300
    assert payload["itens"][0]["plu"] == 148


def test_estado_mostra_venda_pendente(cliente: Any) -> None:
    _ler(cliente, "7894900027013")
    cliente.post("/api/checkout", json={"forma_pagamento": "pix"})

    estado = cliente.get("/api/estado").get_json()

    assert estado["fila_vendas"]["pendentes"] == 1
    assert estado["fila_vendas"]["upstash_configurado"] is False
    assert estado["catalogo"]["produtos_peso"] == 7


def test_fechamento_do_dia_agrupa_por_forma(cliente: Any) -> None:
    _ler(cliente, "2014800009574")  # 9,57
    cliente.post(
        "/api/checkout", json={"forma_pagamento": "dinheiro", "recebido": "10"}
    )
    _ler(cliente, "7894900027013")  # 12,90
    cliente.post("/api/checkout", json={"forma_pagamento": "pix"})

    fechamento = cliente.get("/api/fechamento").get_json()["fechamento"]

    assert fechamento["quantidade"] == 2
    assert fechamento["total_centavos"] == 2247
    assert fechamento["por_forma"]["dinheiro"]["total_centavos"] == 957
    assert fechamento["por_forma"]["pix"]["total_centavos"] == 1290


# ------------------------------------------------------------------ cupom


def test_checkout_devolve_o_cupom_em_texto(cliente: Any) -> None:
    _ler(cliente, "2014800009574")
    dados = cliente.post(
        "/api/checkout", json={"forma_pagamento": "dinheiro", "recebido": "20"}
    ).get_json()

    cupom = dados["cupom_texto"]

    assert "CASA DAS MASSAS" in cupom
    assert "FETUTINE" in cupom
    assert "R$ 9,57" in cupom
    assert "TROCO:" in cupom
    assert "R$ 10,43" in cupom


def test_cupom_e_salvo_em_arquivo(cliente: Any, pdv: Aplicacao) -> None:
    """Rede de seguranca: mesmo com a impressora desligada, o cupom existe."""
    _ler(cliente, "2014800009574")
    cliente.post("/api/checkout", json={"forma_pagamento": "pix"})

    pdv.impressao.parar()  # espera a worker terminar

    arquivos = list(pdv.config.pasta_cupons.glob("cupom-000001-*.txt"))
    assert len(arquivos) == 1
    assert "FETUTINE" in arquivos[0].read_text(encoding="utf-8")


def test_reimprimir_cupom_existente(cliente: Any) -> None:
    _ler(cliente, "2014800009574")
    cliente.post("/api/checkout", json={"forma_pagamento": "pix"})

    dados = cliente.post("/api/reimprimir", json={"cupom": 1}).get_json()

    assert dados["ok"] is True
    assert "FETUTINE" in dados["cupom_texto"]
    assert "R$ 9,57" in dados["cupom_texto"]


def test_reimprimir_cupom_inexistente(cliente: Any) -> None:
    dados = cliente.post("/api/reimprimir", json={"cupom": 999}).get_json()

    assert dados["ok"] is False
    assert "nao encontrado" in dados["mensagem"]


# ----------------------------------------------------------------- rotas


def test_rota_desconhecida_devolve_json(cliente: Any) -> None:
    resposta = cliente.get("/nao-existe")

    assert resposta.status_code == 404
    assert resposta.get_json()["ok"] is False


def test_sincronizar_catalogo_sem_upstash_explica(cliente: Any) -> None:
    dados = cliente.post("/api/catalogo/sincronizar", json={}).get_json()

    assert dados["ok"] is False
    assert "configurado" in dados["mensagem"]


def test_nota_fiscal_desligada_por_padrao(cliente: Any) -> None:
    estado = cliente.get("/api/estado").get_json()

    assert estado["nota_fiscal"]["habilitado"] is False


def test_pedir_nf_com_emissor_desligado_nao_quebra_a_venda(cliente: Any) -> None:
    _ler(cliente, "7894900027013")

    dados = cliente.post(
        "/api/checkout", json={"forma_pagamento": "pix", "emitir_nf": True}
    ).get_json()

    assert dados["ok"] is True
    assert dados["venda"]["nf_enfileirada"] is False
