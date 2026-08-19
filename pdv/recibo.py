"""
Montagem do cupom em texto.

Puro de proposito: recebe a venda, devolve uma lista de linhas. Nao sabe o
que e impressora. Da para testar o layout inteiro sem papel, e a mesma lista
serve para a impressora termica, para o arquivo de backup e para a previa
na tela.

O layout segue o cupom que a loja ja imprime hoje (48 colunas = bobina de
80 mm em fonte A), com duas correcoes:

* o texto e centralizado por conta da largura conhecida, em vez de depender
  de espacos digitados na mao;
* as linhas de item cabem na largura -- no cupom antigo,
  `f"{codigo:<6} {nome:<22} {qtd:>3} x R${preco:>7.2f} R${total:>7.2f}"`
  soma 52 caracteres e a impressora quebrava a linha sozinha.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import DadosLoja
from .dinheiro import formatar_moeda, formatar_peso

if TYPE_CHECKING:  # evita import circular em tempo de execucao
    from .fila import VendaGravada

__all__ = ["LARGURA_PADRAO", "montar_cupom"]

LARGURA_PADRAO = 48

_NOMES_PAGAMENTO = {
    "dinheiro": "DINHEIRO",
    "debito": "CARTAO DEBITO",
    "credito": "CARTAO CREDITO",
    "cartao": "CARTAO",
    "pix": "PIX",
}


def montar_cupom(
    venda: VendaGravada,
    loja: DadosLoja,
    *,
    largura: int = LARGURA_PADRAO,
) -> list[str]:
    """Monta o cupom nao fiscal completo, linha por linha."""
    linhas: list[str] = []
    forte = "=" * largura
    fraco = "-" * largura

    def centro(texto: str) -> None:
        linhas.append(texto.center(largura).rstrip())

    # ---- cabecalho -------------------------------------------------------
    linhas.append(forte)
    centro(loja.nome)
    centro(loja.subtitulo)
    linhas.append(forte)
    linhas.append(loja.endereco)
    linhas.append(loja.bairro_cidade)
    linhas.append(loja.cep)
    linhas.append(fraco)
    linhas.append(f"CNPJ: {loja.cnpj}")
    linhas.append(f"FONE: {loja.fone}")
    linhas.append(fraco)

    data, _, hora = venda.criado_em.partition("T")
    ano, mes, dia = [*data.split("-"), "", "", ""][:3]
    linhas.append(f"DATA: {dia}/{mes}/{ano}")
    linhas.append(f"HORA: {hora[:8]}")
    linhas.append(f"CUPOM: #{venda.cupom:06d}")
    linhas.append(fraco)

    # ---- itens -----------------------------------------------------------
    linhas.append("ITEM  DESCRICAO")
    # Cabecalho montado a partir da largura, e nao com espacos digitados a
    # mao: em bobina de 58 mm (32 colunas) um titulo fixo estouraria a linha
    # e a impressora quebraria no meio.
    linhas.append(_par(f"{'':6}QTD/PESO x UNITARIO", "TOTAL", largura))
    linhas.append(fraco)

    for numero, item in enumerate(venda.itens, start=1):
        # Primeira linha: numero do item e nome (o nome fica com o espaco que
        # sobra da largura, entao so e cortado se realmente nao couber).
        recuo = 6
        linhas.append(f"{numero:03d}   {item.nome[: largura - recuo]}")

        quantidade = (
            formatar_peso(item.peso_g)
            if item.tipo == "peso"
            else f"{item.quantidade} un"
        )
        unitario = formatar_moeda(item.preco_unitario_centavos)
        total = formatar_moeda(item.subtotal_centavos)

        # Segunda linha: "quantidade x unitario" a esquerda, total a direita.
        # O sufixo "/kg" e a primeira coisa a sair quando a bobina e estreita:
        # ele e redundante (a quantidade ao lado ja esta em g/kg) e cortado no
        # meio ficaria "R$ 61,90/", que parece defeito de impressao.
        esquerda = f"{' ' * recuo}{quantidade} x {unitario}"
        if item.tipo == "peso" and len(esquerda) + 3 + 1 + len(total) <= largura:
            esquerda += "/kg"

        # `_par` fecha a linha na largura exata, cortando o texto da esquerda
        # se ainda faltar espaco -- nunca o valor, que e dinheiro.
        linhas.append(_par(esquerda, total, largura))

    linhas.append(fraco)

    # ---- totais ----------------------------------------------------------
    linhas.append(
        _par(
            f"{len(venda.itens)} ITEM(NS)  TOTAL:",
            formatar_moeda(venda.total_centavos),
            largura,
        )
    )
    linhas.append(fraco)

    pagamento = _NOMES_PAGAMENTO.get(
        venda.forma_pagamento, venda.forma_pagamento.upper()
    )
    linhas.append(_par("FORMA PGTO:", pagamento, largura))

    if venda.recebido_centavos is not None:
        linhas.append(
            _par("RECEBIDO:", formatar_moeda(venda.recebido_centavos), largura)
        )
    if venda.troco_centavos is not None:
        linhas.append(_par("TROCO:", formatar_moeda(venda.troco_centavos), largura))

    if venda.cpf:
        linhas.append(fraco)
        linhas.append(_par("CPF/CNPJ:", _formatar_cpf_cnpj(venda.cpf), largura))

    # ---- rodape ----------------------------------------------------------
    linhas.append(fraco)
    centro("** CUPOM NAO FISCAL **")
    linhas.append("")
    centro("OBRIGADO PELA PREFERENCIA!")
    centro("VOLTE SEMPRE A CASA DAS MASSAS!")
    linhas.append("")
    centro(f"{loja.fone} (WhatsApp)")
    linhas.append(forte)
    centro(f"*** CUPOM {venda.cupom:06d} ***")
    linhas.append(forte)

    # Garantia final de largura. Os valores em dinheiro ja passaram por
    # `_par`, que corta o rotulo e nunca o valor, entao o que este corte
    # eventualmente apara e texto fixo comprido numa bobina estreita -- e nao
    # centavos. Deixar a impressora quebrar a linha sozinha seria pior: ela
    # joga o resto numa linha nova e desalinha o cupom inteiro.
    return [linha[:largura] for linha in linhas]


def _par(rotulo: str, valor: str, largura: int) -> str:
    """Rotulo a esquerda, valor a direita, preenchendo a largura exata."""
    espaco = largura - len(rotulo) - len(valor)
    if espaco < 1:
        # Nao cabe: corta o rotulo, nunca o valor (o valor e dinheiro).
        rotulo = rotulo[: max(0, largura - len(valor) - 1)]
        espaco = max(1, largura - len(rotulo) - len(valor))
    return f"{rotulo}{' ' * espaco}{valor}"


def _formatar_cpf_cnpj(documento: str) -> str:
    """Formata CPF (11) ou CNPJ (14). Devolve como veio se nao for nenhum."""
    digitos = "".join(c for c in documento if c.isdigit())
    if len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    if len(digitos) == 14:
        return (
            f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
            f"{digitos[8:12]}-{digitos[12:]}"
        )
    return documento


def cupom_para_json(linhas: list[str]) -> dict[str, Any]:
    """Empacota o cupom para a previa na tela."""
    return {"linhas": linhas, "texto": "\n".join(linhas)}
