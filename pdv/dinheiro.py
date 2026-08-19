"""
Dinheiro: centavos inteiros para calcular, formato brasileiro para mostrar.

Regra do projeto: **valor em dinheiro trafega como int de centavos**, do
codigo de barras ate o SQLite. Float entra em cena so na hora de mostrar
na tela. Assim 0,1 + 0,2 nunca vira 0,30000000000000004 no total da venda.

`Decimal` aparece apenas na fronteira, quando o operador digita um valor.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = ["formatar_moeda", "formatar_peso", "formatar_reais", "para_centavos"]


def formatar_reais(centavos: int) -> str:
    """
    Formata centavos no padrao brasileiro, sem o "R$".

    >>> formatar_reais(957)
    '9,57'
    >>> formatar_reais(123456789)
    '1.234.567,89'
    >>> formatar_reais(-500)
    '-5,00'
    """
    sinal = "-" if centavos < 0 else ""
    inteiro, resto = divmod(abs(int(centavos)), 100)
    # `f"{n:,}"` usa vírgula para milhar e ponto para decimal (padrao en-US);
    # trocamos os dois de lugar em vez de depender de `locale`, que exige o
    # pacote de idioma instalado no Windows e nao e seguro entre threads.
    milhar = f"{inteiro:,}".replace(",", ".")
    return f"{sinal}{milhar},{resto:02d}"


def formatar_moeda(centavos: int) -> str:
    """
    >>> formatar_moeda(3637)
    'R$ 36,37'
    """
    return f"R$ {formatar_reais(centavos)}"


def para_centavos(texto: str | int | float | Decimal | None) -> int | None:
    """
    Le um valor digitado pelo operador e devolve centavos.

    Aceita o que realmente sai de um teclado de caixa: "10", "10,50",
    "10.50", "R$ 10,50", "1.234,56". Devolve None quando nao da para ler --
    nunca 0, que seria confundido com "recebeu zero".

    >>> para_centavos("10,50")
    1050
    >>> para_centavos("R$ 1.234,56")
    123456
    >>> para_centavos("abc") is None
    True
    """
    if texto is None:
        return None
    if isinstance(texto, int) and not isinstance(texto, bool):
        return texto * 100
    if isinstance(texto, float | Decimal):
        return _quantizar(Decimal(str(texto)))

    # O ultimo replace tira ESPACO NAO SEPARAVEL (U+00A0) -- e o que vem
    # colado quando o valor e copiado de planilha ou de pagina web
    # ("R$ 1.234,56"). Sem tirar, o Decimal recusa a string e o caixa
    # diria "valor invalido" para algo que o operador ve como numero.
    limpo = str(texto).strip().replace("R$", "").replace(" ", "").replace(" ", "")  # noqa: RUF001
    if not limpo:
        return None

    # "1.234,56" -> ponto e separador de milhar; "10.50" -> ponto e decimal.
    # A virgula, quando existe, e sempre a decimal no padrao brasileiro.
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")

    try:
        return _quantizar(Decimal(limpo))
    except (InvalidOperation, ArithmeticError, ValueError):
        return None


def _quantizar(valor: Decimal) -> int:
    reais = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(reais * 100)


def formatar_peso(gramas: int | None) -> str:
    """
    Peso legivel para o cupom e para a tela.

    >>> formatar_peso(300)
    '300 g'
    >>> formatar_peso(1042)
    '1,042 kg'
    >>> formatar_peso(None)
    '-'
    """
    if gramas is None:
        return "-"
    if gramas < 1000:
        return f"{gramas} g"
    return f"{gramas / 1000:.3f}".replace(".", ",") + " kg"
