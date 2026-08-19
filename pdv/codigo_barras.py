"""
Leitura e validacao dos codigos de barras que chegam pelo leitor USB.

O leitor se comporta como teclado (HID): ele "digita" o codigo e da Enter.
Este modulo e PURO de proposito -- nao faz I/O, nao toca no banco, nao
importa nada de fora da stdlib. Toda a decisao de dinheiro acontece aqui,
entao ele precisa ser 100% coberto por teste unitario.

Formato da etiqueta da balanca (13 digitos, prefixo "2")
--------------------------------------------------------

    2  0148  00  0957   4
    |  |     |   |      |
    |  |     |   |      +-- pos 13    : digito verificador EAN-13 (mod10)
    |  |     |   +--------- pos  9-12 : preco em centavos
    |  |     +------------- pos  6- 8 : reservado (ver AVISO abaixo)
    |  +------------------- pos  2- 5 : PLU do produto, zero-padded
    +----------------------- pos  1    : prefixo fixo "2" = item pesavel

AVISO -- largura do campo de preco (4 ou 5 digitos)
---------------------------------------------------
A especificacao escrita diz que o preco ocupa as posicoes 9-12 (4 digitos),
o que limita a etiqueta a R$ 99,99. O PDV que hoje roda na loja (app.py,
`decodificar_codigo_barras`) le `codigo[-6:-1]`, ou seja as posicoes 8-12
(5 digitos), permitindo ate R$ 999,99.

Nas 6 etiquetas reais conferidas a mao a posicao 8 e sempre "0", entao as
duas leituras dao exatamente o mesmo valor. A diferenca so aparece numa
etiqueta de R$ 100,00 ou mais -- e ai a leitura de 4 digitos erra em
R$ 100 para baixo, silenciosamente. Como o catalogo tem itens a
R$ 61,90/kg (2 kg = R$ 123,80), tratamos 5 digitos como o padrao correto.

Quem quiser voltar ao comportamento da especificacao usa
`interpretar(codigo, digitos_preco=4)`. Nesse modo, se a posicao 8 vier
diferente de "0", a leitura devolve `aviso` preenchido para o operador ver.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .dinheiro import formatar_moeda

__all__ = [
    "CODIGO_PRODUTO_POR_KG",
    "DIGITOS_PRECO_PADRAO",
    "Leitura",
    "TipoLeitura",
    "digito_verificador_ean13",
    "ean13_valido",
    "interpretar",
    "peso_gramas",
    "prefixo_de_plu",
]

# --------------------------------------------------------------------------
# Constantes do formato
# --------------------------------------------------------------------------

PREFIXO_BALANCA = "2"
TAMANHO_EAN13 = 13

#: Etiqueta generica "PRODUTO POR KG": o operador digita o peso na mao.
CODIGO_PRODUTO_POR_KG = "2000000"

#: Fim (exclusivo) do campo de preco -- sempre logo antes do verificador.
_PRECO_FIM = 12

#: Quantos digitos o campo de preco ocupa. Ver AVISO no topo do modulo.
DIGITOS_PRECO_PADRAO = 5

#: Larguras aceitas para o campo de preco.
_DIGITOS_PRECO_ACEITOS = (4, 5)


class TipoLeitura(str, Enum):
    """O que o leitor acabou de ler."""

    #: Etiqueta de balanca valida: sabemos PLU e quanto custa.
    BALANCA = "balanca"
    #: Etiqueta generica por kg: falta o operador informar o peso.
    PRODUTO_POR_KG = "produto_por_kg"
    #: Codigo de prateleira (bebida, doce industrializado): busca exata.
    EAN = "ean"
    #: Nao deu para confiar na leitura. NUNCA entra no carrinho.
    INVALIDA = "invalida"


@dataclass(frozen=True, slots=True)
class Leitura:
    """Resultado da interpretacao de um codigo. Imutavel e serializavel."""

    tipo: TipoLeitura
    #: Codigo normalizado (sem espacos / Enter do leitor).
    codigo: str
    #: PLU do produto -- so em BALANCA.
    plu: int | None = None
    #: Primeiros 7 digitos ("2" + PLU + 2 reservados). E a chave usada pelo
    #: catalogo legado (tabela `produtos.codigo_barras`).
    prefixo: str | None = None
    #: Preco total impresso na etiqueta, em centavos (inteiro exato).
    total_centavos: int | None = None
    #: Por que a leitura foi recusada -- so em INVALIDA.
    motivo: str | None = None
    #: Alerta que nao impede a venda, mas o operador precisa ver.
    aviso: str | None = None

    @property
    def aceita(self) -> bool:
        """Pode seguir para o carrinho?"""
        return self.tipo is not TipoLeitura.INVALIDA

    @property
    def total_reais(self) -> float | None:
        """Somente para exibir/logar. Dinheiro de verdade usa centavos."""
        if self.total_centavos is None:
            return None
        return self.total_centavos / 100.0


# --------------------------------------------------------------------------
# Digito verificador EAN-13
# --------------------------------------------------------------------------


def digito_verificador_ean13(doze_digitos: str) -> int:
    """
    Calcula o 13o digito de um EAN-13 a partir dos 12 primeiros.

    Pesos alternados 1,3,1,3... da esquerda para a direita; o verificador e
    o quanto falta para fechar a proxima dezena.
    """
    if len(doze_digitos) != 12 or not doze_digitos.isdigit():
        raise ValueError("esperado exatamente 12 digitos")

    soma = 0
    for posicao, caractere in enumerate(doze_digitos):
        peso = 3 if posicao % 2 else 1
        soma += int(caractere) * peso
    return (10 - soma % 10) % 10


def ean13_valido(codigo: str) -> bool:
    """True se `codigo` tem 13 digitos e o verificador fecha."""
    if len(codigo) != TAMANHO_EAN13 or not codigo.isdigit():
        return False
    return digito_verificador_ean13(codigo[:12]) == int(codigo[12])


# --------------------------------------------------------------------------
# Interpretacao
# --------------------------------------------------------------------------


def _normalizar(bruto: str) -> str:
    """Tira o Enter do leitor e qualquer espaco que tenha vindo junto."""
    return "".join(bruto.split())


def prefixo_de_plu(plu: int) -> str:
    """
    Monta a chave de 7 digitos que o catalogo legado usa a partir do PLU.

    >>> prefixo_de_plu(148)
    '2014800'
    """
    if not 0 <= plu <= 9999:
        raise ValueError("PLU fora da faixa 0..9999")
    return f"{PREFIXO_BALANCA}{plu:04d}00"


def interpretar(bruto: str, *, digitos_preco: int = DIGITOS_PRECO_PADRAO) -> Leitura:
    """
    Classifica uma leitura do leitor de codigo de barras.

    Regras, na ordem:

    1. Vazio -> INVALIDA.
    2. `2000000` -> PRODUTO_POR_KG (peso digitado a mao).
    3. 13 digitos comecando por "2" -> etiqueta de balanca. O verificador
       EAN-13 e conferido ANTES de qualquer coisa: se nao fechar, a leitura
       e recusada (INVALIDA) e nada entra no carrinho -- uma etiqueta de
       balanca corrompida carrega um valor em dinheiro errado, entao aqui
       recusar e mais seguro do que tentar adivinhar.
    4. Qualquer outra coisa -> EAN de prateleira, para busca exata no
       catalogo. Inclui codigos que comecam com "2" mas nao tem 13 digitos
       (codigos internos) e codigos nao numericos (Code128).
    """
    if digitos_preco not in _DIGITOS_PRECO_ACEITOS:
        raise ValueError(f"digitos_preco deve ser um de {_DIGITOS_PRECO_ACEITOS}")

    codigo = _normalizar(bruto)

    if not codigo:
        return Leitura(
            tipo=TipoLeitura.INVALIDA,
            codigo=codigo,
            motivo="Leitura vazia.",
        )

    if codigo == CODIGO_PRODUTO_POR_KG:
        return Leitura(
            tipo=TipoLeitura.PRODUTO_POR_KG,
            codigo=codigo,
            plu=0,
            prefixo=CODIGO_PRODUTO_POR_KG,
        )

    if _parece_etiqueta_de_balanca(codigo):
        return _ler_etiqueta_de_balanca(codigo, digitos_preco)

    return Leitura(tipo=TipoLeitura.EAN, codigo=codigo)


def _parece_etiqueta_de_balanca(codigo: str) -> bool:
    return (
        len(codigo) == TAMANHO_EAN13
        and codigo.isdigit()
        and codigo.startswith(PREFIXO_BALANCA)
    )


def _ler_etiqueta_de_balanca(codigo: str, digitos_preco: int) -> Leitura:
    if not ean13_valido(codigo):
        esperado = digito_verificador_ean13(codigo[:12])
        return Leitura(
            tipo=TipoLeitura.INVALIDA,
            codigo=codigo,
            motivo=(
                f"Digito verificador invalido: a etiqueta termina em "
                f"{codigo[12]}, mas o calculo EAN-13 dava {esperado}. "
                f"Pese o produto de novo."
            ),
        )

    plu = int(codigo[1:5])
    inicio_preco = _PRECO_FIM - digitos_preco
    total_centavos = int(codigo[inicio_preco:_PRECO_FIM])

    leitura = Leitura(
        tipo=TipoLeitura.BALANCA,
        codigo=codigo,
        plu=plu,
        prefixo=codigo[:7],
        total_centavos=total_centavos,
    )

    # Modo 4 digitos com a posicao 8 ocupada = a etiqueta passou de R$ 99,99
    # e acabamos de jogar R$ 100 (ou mais) no lixo. Avisa, alto e claro.
    if digitos_preco == 4 and codigo[7] != "0":
        descartado = int(codigo[7]) * 100_00
        leitura = replace(
            leitura,
            aviso=(
                f"Etiqueta com preco acima de R$ 99,99 lida em modo de 4 "
                f"digitos: {formatar_moeda(descartado)} foram ignorados. "
                f"Confira o valor antes de fechar a venda."
            ),
        )

    return leitura


# --------------------------------------------------------------------------
# Peso
# --------------------------------------------------------------------------


def peso_gramas(total_centavos: int, preco_kg_centavos: int) -> int | None:
    """
    Descobre o peso que a balanca usou, a partir do total impresso.

    A etiqueta nao carrega o peso -- so o valor final. Como o catalogo sabe
    o preco por kg, o peso sai da divisao. Serve para o recibo e para a nota
    fiscal (que precisa de quantidade em kg).

    Devolve None quando nao da para calcular (preco por kg ausente ou zero),
    e nao 0 -- zero seria confundido com "pesou nada".
    """
    if preco_kg_centavos <= 0:
        return None
    return round(total_centavos * 1000 / preco_kg_centavos)
