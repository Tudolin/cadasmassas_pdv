"""
Carrinho da venda em andamento.

Um caixa, um carrinho: o PDV roda num notebook so, com um operador so, e o
carrinho vive na memoria do processo protegido por um lock. Nada de sessao
de usuario nem de carrinho por aba -- se o operador abrir a tela em duas
janelas, ele ve o MESMO carrinho, que e o comportamento certo para um caixa.

Dinheiro aqui e sempre `int` de centavos (ver `dinheiro.py`).

Detalhe importante de negocio: para item pesado, o subtotal e o valor
IMPRESSO NA ETIQUETA, nunca `preco_kg * peso`. A etiqueta e o que o cliente
leu na balanca; recalcular geraria diferenca de centavo no arredondamento e
briga no balcao. O peso vai para o cupom como informacao derivada.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .catalogo import ProdutoPeso, ProdutoUnidade
from .codigo_barras import peso_gramas
from .dinheiro import formatar_moeda, formatar_peso

__all__ = ["Carrinho", "ErroCarrinho", "ItemCarrinho"]

TipoItem = Literal["peso", "unidade"]

#: Trava de sanidade: uma venda de balcao nao tem 200 linhas. Se chegar
#: nisso, alguma coisa esta lendo em loop e e melhor parar.
MAX_ITENS = 200
MAX_QUANTIDADE_ITEM = 999


class ErroCarrinho(ValueError):
    """Operacao invalida no carrinho, com mensagem pronta para o operador."""


@dataclass(frozen=True, slots=True)
class ItemCarrinho:
    """Uma linha do carrinho. Imutavel; alterar = trocar por outra linha."""

    id: str
    tipo: TipoItem
    codigo: str
    nome: str
    quantidade: int
    preco_unitario_centavos: int
    subtotal_centavos: int
    peso_g: int | None = None
    plu: int | None = None

    def para_json(self) -> dict[str, Any]:
        """Versao para a tela: acrescenta os campos ja formatados."""
        dados = asdict(self)
        dados["unidade"] = "kg" if self.tipo == "peso" else "un"
        dados["preco_unitario_texto"] = formatar_moeda(self.preco_unitario_centavos)
        dados["subtotal_texto"] = formatar_moeda(self.subtotal_centavos)
        dados["peso_texto"] = formatar_peso(self.peso_g)
        dados["quantidade_texto"] = (
            formatar_peso(self.peso_g)
            if self.tipo == "peso"
            else f"{self.quantidade} un"
        )
        return dados


class Carrinho:
    """Carrinho unico do caixa, seguro para acesso concorrente."""

    def __init__(self) -> None:
        self._itens: list[ItemCarrinho] = []
        self._trava = threading.RLock()

    # ------------------------------------------------------------- consulta

    @property
    def itens(self) -> list[ItemCarrinho]:
        with self._trava:
            return list(self._itens)

    @property
    def vazio(self) -> bool:
        with self._trava:
            return not self._itens

    @property
    def total_centavos(self) -> int:
        with self._trava:
            return sum(item.subtotal_centavos for item in self._itens)

    def para_json(self) -> dict[str, Any]:
        with self._trava:
            itens = [item.para_json() for item in self._itens]
            total = sum(item.subtotal_centavos for item in self._itens)
        return {
            "itens": itens,
            "quantidade_itens": len(itens),
            "total_centavos": total,
            "total_texto": formatar_moeda(total),
            "vazio": not itens,
        }

    # -------------------------------------------------------------- escrita

    def adicionar_pesado(
        self,
        produto: ProdutoPeso,
        total_centavos: int,
        codigo: str,
    ) -> ItemCarrinho:
        """
        Adiciona um item lido de etiqueta de balanca.

        `total_centavos` vem da etiqueta e e a fonte da verdade do subtotal.
        """
        if total_centavos <= 0:
            raise ErroCarrinho(
                f"A etiqueta de {produto.nome} veio com valor zero. "
                f"Pese o produto de novo."
            )

        item = ItemCarrinho(
            id=_novo_id(),
            tipo="peso",
            codigo=codigo,
            nome=produto.nome,
            quantidade=1,
            preco_unitario_centavos=produto.preco_kg_centavos,
            subtotal_centavos=total_centavos,
            peso_g=peso_gramas(total_centavos, produto.preco_kg_centavos),
            plu=produto.plu,
        )
        return self._inserir(item)

    def adicionar_pesado_manual(
        self,
        produto: ProdutoPeso,
        peso_g: int,
    ) -> ItemCarrinho:
        """
        Adiciona item por peso digitado a mao (etiqueta `2000000` ou busca
        por nome). Aqui o subtotal E calculado, porque nao existe etiqueta.
        """
        if peso_g <= 0:
            raise ErroCarrinho("Informe um peso maior que zero.")
        if peso_g > 50_000:
            raise ErroCarrinho("Peso acima de 50 kg: confira o valor digitado.")

        subtotal = round(produto.preco_kg_centavos * peso_g / 1000)
        if subtotal <= 0:
            raise ErroCarrinho(
                f"{produto.nome} com {peso_g} g daria R$ 0,00. Confira o peso."
            )

        item = ItemCarrinho(
            id=_novo_id(),
            tipo="peso",
            codigo=produto.prefixo,
            nome=produto.nome,
            quantidade=1,
            preco_unitario_centavos=produto.preco_kg_centavos,
            subtotal_centavos=subtotal,
            peso_g=peso_g,
            plu=produto.plu,
        )
        return self._inserir(item)

    def adicionar_unidade(
        self,
        produto: ProdutoUnidade,
        quantidade: int = 1,
    ) -> ItemCarrinho:
        """
        Adiciona produto de prateleira.

        Ler o mesmo EAN duas vezes soma na linha que ja existe, em vez de
        criar linha repetida -- e o que o operador espera ao passar tres
        latas iguais.
        """
        if quantidade <= 0:
            raise ErroCarrinho("Quantidade precisa ser pelo menos 1.")

        with self._trava:
            for indice, existente in enumerate(self._itens):
                if existente.tipo == "unidade" and existente.codigo == produto.codigo:
                    nova_quantidade = existente.quantidade + quantidade
                    if nova_quantidade > MAX_QUANTIDADE_ITEM:
                        raise ErroCarrinho(
                            f"Quantidade maxima de {MAX_QUANTIDADE_ITEM} "
                            f"atingida para {produto.nome}."
                        )
                    atualizado = ItemCarrinho(
                        id=existente.id,
                        tipo="unidade",
                        codigo=existente.codigo,
                        nome=existente.nome,
                        quantidade=nova_quantidade,
                        preco_unitario_centavos=produto.preco_centavos,
                        subtotal_centavos=produto.preco_centavos * nova_quantidade,
                    )
                    self._itens[indice] = atualizado
                    return atualizado

            item = ItemCarrinho(
                id=_novo_id(),
                tipo="unidade",
                codigo=produto.codigo,
                nome=produto.nome,
                quantidade=quantidade,
                preco_unitario_centavos=produto.preco_centavos,
                subtotal_centavos=produto.preco_centavos * quantidade,
            )
            return self._inserir(item)

    def remover(self, id_item: str) -> ItemCarrinho:
        """Remove uma linha pelo id. Estoura se o id nao existe."""
        with self._trava:
            for indice, item in enumerate(self._itens):
                if item.id == id_item:
                    return self._itens.pop(indice)
        raise ErroCarrinho("Esse item nao esta mais no carrinho.")

    def limpar(self) -> int:
        """Zera o carrinho e devolve quantas linhas foram descartadas."""
        with self._trava:
            quantidade = len(self._itens)
            self._itens.clear()
            return quantidade

    def _inserir(self, item: ItemCarrinho) -> ItemCarrinho:
        with self._trava:
            if len(self._itens) >= MAX_ITENS:
                raise ErroCarrinho(
                    f"O carrinho chegou a {MAX_ITENS} itens. "
                    f"Finalize ou limpe a venda."
                )
            self._itens.append(item)
            return item


def _novo_id() -> str:
    """Id curto, so precisa ser unico dentro de um carrinho."""
    return uuid.uuid4().hex[:12]


def calcular_troco(total_centavos: int, recebido_centavos: int) -> int:
    """
    Troco de venda em dinheiro.

    Levanta ErroCarrinho quando o recebido nao cobre o total -- deixar
    passar aqui viraria troco negativo impresso no cupom.
    """
    if recebido_centavos < total_centavos:
        falta = total_centavos - recebido_centavos
        raise ErroCarrinho(
            f"Valor recebido menor que o total: faltam {formatar_moeda(falta)}."
        )
    return recebido_centavos - total_centavos
