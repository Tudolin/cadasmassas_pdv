"""
Aplicacao Flask do caixa: as rotas e o que amarra os modulos.

Desenho das rotas: a tela do caixa e uma pagina so, e toda interacao e um
POST curto que devolve o carrinho inteiro em JSON. A tela nao faz conta
nenhuma -- ela desenha o que o servidor mandou. Isso evita a classe de bug
mais chata de PDV, que e o total da tela nao bater com o total gravado.

Nenhuma rota que o operador usa faz chamada de rede. `/api/ler` toca so em
memoria; `/api/checkout` toca so no SQLite.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, render_template, request

from .carrinho import Carrinho, ErroCarrinho, calcular_troco
from .catalogo import Catalogo
from .codigo_barras import TipoLeitura, interpretar
from .config import Config
from .db import Banco
from .dinheiro import formatar_moeda, para_centavos
from .fila import FilaVendas, VendaGravada
from .impressao import GerenciadorImpressao, impressora_padrao, listar_impressoras
from .nota_fiscal import EmissorNF, PedidoNF
from .recibo import montar_cupom

__all__ = ["Aplicacao", "criar_app"]

log = logging.getLogger(__name__)

FORMAS_PAGAMENTO = {"dinheiro", "debito", "credito", "cartao", "pix"}


class Aplicacao:
    """
    Reune os componentes vivos do PDV.

    Existe para as rotas nao dependerem de variavel global e para o teste
    poder montar um PDV inteiro com um banco temporario.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.banco = Banco(config.banco)
        self.carrinho = Carrinho()

        cliente = self._criar_cliente()
        self.catalogo = Catalogo(
            self.banco, cliente, intervalo_s=config.intervalo_catalogo_s
        )
        self.fila = FilaVendas(
            self.banco,
            cliente,
            intervalo_s=config.intervalo_fila_s,
            max_tentativas=config.max_tentativas_venda,
        )
        self.impressao = GerenciadorImpressao(
            pasta_cupons=config.pasta_cupons,
            impressora=config.impressora,
            codepage=config.codepage_cupom,
            habilitado=config.imprimir_habilitado,
        )

        from .nota_fiscal import construir_adaptador

        adaptador = None
        if config.nf_habilitada:
            try:
                adaptador = construir_adaptador(
                    habilitada=True,
                    pasta=config.pasta_nf,
                    tipo=config.nf_tipo,
                    usuario=config.nf_usuario,
                    senha=config.nf_senha,
                )
            except Exception as erro:
                # NF mal configurada nao pode impedir o caixa de abrir.
                log.warning("nota fiscal desligada: %s", erro)
        self.nf = EmissorNF(self.banco, adaptador)

    def _criar_cliente(self):
        if not self.config.upstash_configurado:
            log.warning(
                "UPSTASH_REDIS_REST_URL/TOKEN ausentes: o PDV vai rodar "
                "100% local (catalogo do cache, vendas so no SQLite)."
            )
            return None
        from .upstash import ClienteUpstash

        return ClienteUpstash(
            self.config.upstash_url,
            self.config.upstash_token,
            timeout_s=self.config.timeout_rede_s,
        )

    def iniciar(self) -> None:
        """Sobe as threads de fundo. O catalogo local carrega antes de tudo."""
        self.catalogo.iniciar()
        self.fila.iniciar()
        self.impressao.iniciar()
        self.nf.iniciar()

    def parar(self) -> None:
        """
        Encerra na ordem inversa da subida.

        As threads sao paradas (e aguardadas) ANTES de o banco fechar: fechar
        primeiro faria uma worker no meio de um INSERT falhar sem necessidade.
        """
        self.nf.parar()
        self.impressao.parar()
        self.fila.parar()
        self.catalogo.parar()
        self.banco.fechar_tudo()


# --------------------------------------------------------------------------
# Fabrica do app
# --------------------------------------------------------------------------


def criar_app(config: Config, aplicacao: Aplicacao | None = None) -> Flask:
    app = Flask(__name__)
    pdv = aplicacao or Aplicacao(config)
    app.extensions["pdv"] = pdv

    # A tela nao guarda estado; sem cache o F5 nunca mostra carrinho velho.
    app.config["TEMPLATES_AUTO_RELOAD"] = False
    app.json.sort_keys = False

    # ---------------------------------------------------------------- tela

    @app.get("/")
    def tela_caixa() -> str:
        return render_template(
            "caixa.html",
            loja=config.loja,
            versao_catalogo=pdv.catalogo.snapshot.versao,
        )

    @app.get("/healthz")
    def saude() -> Any:
        return jsonify({"ok": True})

    # ------------------------------------------------------------- leitura

    @app.post("/api/ler")
    def ler_codigo() -> Any:
        """
        Coracao do caixa: recebe o que o leitor digitou e devolve o carrinho.

        Tudo em memoria -- nenhuma chamada de rede nesta rota, por requisito.
        """
        dados = request.get_json(silent=True) or {}
        bruto = str(dados.get("codigo", ""))

        leitura = interpretar(bruto, digitos_preco=config.digitos_preco)

        if leitura.tipo is TipoLeitura.INVALIDA:
            return _resposta(
                pdv, ok=False, mensagem=leitura.motivo or "Leitura invalida."
            )

        if leitura.tipo is TipoLeitura.PRODUTO_POR_KG:
            return _resposta(
                pdv,
                ok=False,
                mensagem="Etiqueta generica por kg: escolha o produto e informe o peso.",
                extra={"pedir_peso": True},
            )

        try:
            if leitura.tipo is TipoLeitura.BALANCA:
                produto = pdv.catalogo.buscar_por_plu(leitura.plu or -1)
                if produto is None:
                    return _resposta(
                        pdv,
                        ok=False,
                        mensagem=(
                            f"PLU {leitura.plu} nao esta no catalogo. "
                            f"Cadastre o produto no precifier ou use a busca "
                            f"por nome."
                        ),
                    )
                item = pdv.carrinho.adicionar_pesado(
                    produto, leitura.total_centavos or 0, leitura.codigo
                )
            else:
                unidade = pdv.catalogo.buscar_por_ean(leitura.codigo)
                if unidade is None:
                    return _resposta(
                        pdv,
                        ok=False,
                        mensagem=f"Codigo {leitura.codigo} nao encontrado no catalogo.",
                    )
                item = pdv.carrinho.adicionar_unidade(unidade)
        except ErroCarrinho as erro:
            return _resposta(pdv, ok=False, mensagem=str(erro))

        return _resposta(
            pdv,
            ok=True,
            mensagem=f"{item.nome} - {formatar_moeda(item.subtotal_centavos)}",
            extra={"item": item.para_json(), "aviso": leitura.aviso},
        )

    # ------------------------------------------------------------ carrinho

    @app.get("/api/carrinho")
    def ver_carrinho() -> Any:
        return _resposta(pdv, ok=True, mensagem="")

    @app.post("/api/carrinho/remover")
    def remover_item() -> Any:
        dados = request.get_json(silent=True) or {}
        try:
            item = pdv.carrinho.remover(str(dados.get("id", "")))
        except ErroCarrinho as erro:
            return _resposta(pdv, ok=False, mensagem=str(erro))
        return _resposta(pdv, ok=True, mensagem=f"{item.nome} removido.")

    @app.post("/api/carrinho/limpar")
    def limpar_carrinho() -> Any:
        quantidade = pdv.carrinho.limpar()
        return _resposta(
            pdv,
            ok=True,
            mensagem=(
                f"Carrinho zerado ({quantidade} item(ns))."
                if quantidade
                else "O carrinho ja estava vazio."
            ),
        )

    @app.post("/api/carrinho/peso")
    def adicionar_por_peso() -> Any:
        """Item por peso digitado a mao (etiqueta ilegivel ou `2000000`)."""
        dados = request.get_json(silent=True) or {}
        try:
            plu = int(dados.get("plu"))
        except (TypeError, ValueError):
            return _resposta(pdv, ok=False, mensagem="PLU invalido.")

        produto = pdv.catalogo.buscar_por_plu(plu)
        if produto is None:
            return _resposta(pdv, ok=False, mensagem=f"PLU {plu} nao esta no catalogo.")

        gramas = _ler_gramas(dados.get("peso_g"), dados.get("peso_kg"))
        if gramas is None:
            return _resposta(pdv, ok=False, mensagem="Informe o peso em gramas ou kg.")

        try:
            item = pdv.carrinho.adicionar_pesado_manual(produto, gramas)
        except ErroCarrinho as erro:
            return _resposta(pdv, ok=False, mensagem=str(erro))

        return _resposta(
            pdv,
            ok=True,
            mensagem=f"{item.nome} - {formatar_moeda(item.subtotal_centavos)}",
            extra={"item": item.para_json()},
        )

    @app.post("/api/carrinho/unidade")
    def adicionar_por_unidade() -> Any:
        """Produto de prateleira escolhido pela busca por nome."""
        dados = request.get_json(silent=True) or {}
        codigo = str(dados.get("codigo", "")).strip()
        unidade = pdv.catalogo.buscar_por_ean(codigo)
        if unidade is None:
            return _resposta(pdv, ok=False, mensagem=f"Codigo {codigo} nao encontrado.")

        try:
            quantidade = max(1, int(dados.get("quantidade", 1)))
            item = pdv.carrinho.adicionar_unidade(unidade, quantidade)
        except (TypeError, ValueError):
            return _resposta(pdv, ok=False, mensagem="Quantidade invalida.")
        except ErroCarrinho as erro:
            return _resposta(pdv, ok=False, mensagem=str(erro))

        return _resposta(
            pdv,
            ok=True,
            mensagem=f"{item.nome} - {formatar_moeda(item.subtotal_centavos)}",
            extra={"item": item.para_json()},
        )

    @app.get("/api/buscar")
    def buscar() -> Any:
        termo = request.args.get("q", "")
        return jsonify({"ok": True, "resultados": pdv.catalogo.buscar_por_nome(termo)})

    # ------------------------------------------------------------ checkout

    @app.post("/api/checkout")
    def checkout() -> Any:
        """
        Fecha a venda.

        Ordem, e ela importa:
        1. valida;
        2. GRAVA no SQLite (com fsync) -- daqui para frente a venda existe;
        3. enfileira impressao e NF;
        4. limpa o carrinho e responde.

        Passos 3 e 4 nao podem falhar de forma a desfazer o 2, e nenhum
        deles espera rede ou papel.
        """
        dados = request.get_json(silent=True) or {}

        forma = str(dados.get("forma_pagamento", "")).strip().lower()
        if forma not in FORMAS_PAGAMENTO:
            return _resposta(
                pdv,
                ok=False,
                mensagem=f"Forma de pagamento invalida: escolha {_lista(FORMAS_PAGAMENTO)}.",
            )

        itens = pdv.carrinho.itens
        if not itens:
            return _resposta(pdv, ok=False, mensagem="O carrinho esta vazio.")

        total = pdv.carrinho.total_centavos
        recebido: int | None = None
        troco: int | None = None

        if forma == "dinheiro":
            recebido = para_centavos(dados.get("recebido"))
            if recebido is None:
                return _resposta(
                    pdv, ok=False, mensagem="Informe o valor recebido em dinheiro."
                )
            try:
                troco = calcular_troco(total, recebido)
            except ErroCarrinho as erro:
                return _resposta(pdv, ok=False, mensagem=str(erro))

        cpf = _limpar_documento(dados.get("cpf"))

        try:
            venda = pdv.fila.gravar(
                itens=itens,
                total_centavos=total,
                forma_pagamento=forma,
                recebido_centavos=recebido,
                troco_centavos=troco,
                cpf=cpf,
            )
        except Exception as erro:
            # Falhou a gravacao = a venda NAO existe. Nada de imprimir, nada
            # de limpar carrinho: o operador tenta de novo com tudo no lugar.
            log.exception("falha ao gravar a venda")
            return _resposta(
                pdv,
                ok=False,
                mensagem=(
                    f"NAO foi possivel gravar a venda ({erro}). "
                    f"O carrinho foi mantido -- tente finalizar de novo."
                ),
            )

        cupom = montar_cupom(venda, config.loja, largura=config.largura_cupom)
        pdv.impressao.enfileirar(cupom, venda.cupom)

        nf_enfileirada = False
        if dados.get("emitir_nf") and pdv.nf.habilitado:
            pdv.nf.enfileirar(_pedido_nf(venda))
            nf_enfileirada = True

        pdv.carrinho.limpar()

        return _resposta(
            pdv,
            ok=True,
            mensagem=f"Venda #{venda.cupom:06d} finalizada.",
            extra={
                "venda": {
                    "cupom": venda.cupom,
                    "uuid": venda.uuid,
                    "total_centavos": venda.total_centavos,
                    "total_texto": formatar_moeda(venda.total_centavos),
                    "forma_pagamento": venda.forma_pagamento,
                    "recebido_texto": (
                        formatar_moeda(recebido) if recebido is not None else None
                    ),
                    "troco_centavos": troco,
                    "troco_texto": formatar_moeda(troco) if troco is not None else None,
                    "nf_enfileirada": nf_enfileirada,
                },
                "cupom_texto": "\n".join(cupom),
            },
        )

    @app.post("/api/reimprimir")
    def reimprimir() -> Any:
        """Reimprime um cupom ja fechado, a partir do que esta no SQLite."""
        dados = request.get_json(silent=True) or {}
        try:
            numero = int(dados.get("cupom"))
        except (TypeError, ValueError):
            return _resposta(pdv, ok=False, mensagem="Numero de cupom invalido.")

        linha = (
            pdv.banco.conexao()
            .execute("SELECT payload FROM venda WHERE cupom = ?", (numero,))
            .fetchone()
        )
        if linha is None:
            return _resposta(pdv, ok=False, mensagem=f"Cupom {numero} nao encontrado.")

        venda = _venda_do_payload(numero, linha["payload"])
        if venda is None:
            return _resposta(pdv, ok=False, mensagem="Dados do cupom corrompidos.")

        linhas = montar_cupom(venda, config.loja, largura=config.largura_cupom)
        pdv.impressao.enfileirar(linhas, numero)
        return _resposta(
            pdv,
            ok=True,
            mensagem=f"Cupom {numero:06d} enviado para a impressora.",
            extra={"cupom_texto": "\n".join(linhas)},
        )

    # ----------------------------------------------------------- operacao

    @app.get("/api/estado")
    def estado() -> Any:
        return jsonify(
            {
                "ok": True,
                "catalogo": pdv.catalogo.estado(),
                "fila_vendas": pdv.fila.estado(),
                "impressao": pdv.impressao.estado(),
                "nota_fiscal": pdv.nf.estado(),
                "digitos_preco": config.digitos_preco,
            }
        )

    @app.post("/api/catalogo/sincronizar")
    def sincronizar_catalogo() -> Any:
        """
        Unica rota que espera rede de proposito -- e o operador que pediu,
        clicando em "Atualizar catalogo".
        """
        mudou = pdv.catalogo.sincronizar_agora(forcar=True)
        estado_catalogo = pdv.catalogo.estado()
        if estado_catalogo["ultimo_erro"]:
            return jsonify(
                {
                    "ok": False,
                    "mensagem": f"Falha ao atualizar: {estado_catalogo['ultimo_erro']}",
                    "catalogo": estado_catalogo,
                }
            )
        return jsonify(
            {
                "ok": True,
                "mensagem": (
                    "Catalogo atualizado."
                    if mudou
                    else "O catalogo ja estava na versao mais recente."
                ),
                "catalogo": estado_catalogo,
            }
        )

    @app.post("/api/vendas/sincronizar")
    def sincronizar_vendas() -> Any:
        enviadas = pdv.fila.sincronizar_agora()
        return jsonify(
            {
                "ok": True,
                "mensagem": f"{enviadas} venda(s) enviada(s).",
                "fila_vendas": pdv.fila.estado(),
            }
        )

    @app.get("/api/fechamento")
    def fechamento() -> Any:
        dados = pdv.fila.vendas_do_dia()
        dados["total_texto"] = formatar_moeda(dados["total_centavos"])
        for forma in dados["por_forma"].values():
            forma["total_texto"] = formatar_moeda(forma["total_centavos"])
        return jsonify({"ok": True, "fechamento": dados})

    @app.get("/api/impressoras")
    def impressoras() -> Any:
        return jsonify(
            {
                "ok": True,
                "impressoras": listar_impressoras(),
                "padrao": impressora_padrao(),
                "configurada": config.impressora,
            }
        )

    # ------------------------------------------------------------- erros

    @app.errorhandler(404)
    def nao_encontrado(_erro: Any) -> Any:
        return jsonify({"ok": False, "mensagem": "Rota nao encontrada."}), 404

    @app.errorhandler(500)
    def erro_interno(erro: Any) -> Any:
        log.exception("erro interno", exc_info=erro)
        return (
            jsonify({"ok": False, "mensagem": "Erro interno; veja o log do PDV."}),
            500,
        )

    return app


# --------------------------------------------------------------------------
# Apoio
# --------------------------------------------------------------------------


def _resposta(
    pdv: Aplicacao,
    *,
    ok: bool,
    mensagem: str,
    extra: dict[str, Any] | None = None,
) -> Any:
    """
    Resposta padrao de toda rota de carrinho: o carrinho INTEIRO vai junto.

    Custa alguns kilobytes e elimina a possibilidade de a tela ficar
    dessincronizada do servidor.
    """
    corpo: dict[str, Any] = {
        "ok": ok,
        "mensagem": mensagem,
        "carrinho": pdv.carrinho.para_json(),
    }
    if extra:
        corpo.update(extra)
    return jsonify(corpo)


def _lista(valores: set[str]) -> str:
    return ", ".join(sorted(valores))


def _ler_gramas(peso_g: Any, peso_kg: Any) -> int | None:
    """Aceita peso em gramas (inteiro) ou em kg (com virgula)."""
    if peso_g not in (None, ""):
        try:
            return int(float(str(peso_g).replace(",", ".")))
        except (TypeError, ValueError):
            return None
    if peso_kg not in (None, ""):
        try:
            return int(round(float(str(peso_kg).replace(",", ".")) * 1000))
        except (TypeError, ValueError):
            return None
    return None


def _limpar_documento(valor: Any) -> str | None:
    if not valor:
        return None
    digitos = "".join(c for c in str(valor) if c.isdigit())
    return digitos if len(digitos) in (11, 14) else None


def _pedido_nf(venda: VendaGravada) -> PedidoNF:
    return PedidoNF(
        venda_uuid=venda.uuid,
        cupom=venda.cupom,
        criado_em=venda.criado_em,
        total_centavos=venda.total_centavos,
        forma_pagamento=venda.forma_pagamento,
        cpf=venda.cpf,
        itens=[],  # a worker remonta a partir do payload gravado
    )


def _venda_do_payload(cupom: int, payload: str) -> VendaGravada | None:
    """Reconstroi uma VendaGravada a partir do JSON do SQLite."""
    import json

    from .carrinho import ItemCarrinho

    try:
        dados = json.loads(payload)
    except json.JSONDecodeError:
        return None

    itens = []
    for indice, bruto in enumerate(dados.get("itens", [])):
        itens.append(
            ItemCarrinho(
                id=f"r{indice}",
                tipo="peso" if bruto.get("tipo") == "peso" else "unidade",
                codigo=str(bruto.get("codigo", "")),
                nome=str(bruto.get("nome", "")),
                quantidade=int(bruto.get("quantidade") or 1),
                preco_unitario_centavos=round(
                    float(bruto.get("preco_unitario") or 0) * 100
                ),
                subtotal_centavos=round(float(bruto.get("subtotal") or 0) * 100),
                peso_g=bruto.get("peso_g"),
                plu=bruto.get("plu"),
            )
        )

    return VendaGravada(
        cupom=cupom,
        uuid=str(dados.get("uuid", "")),
        criado_em=str(dados.get("timestamp", "")),
        total_centavos=int(dados.get("total_centavos") or 0),
        forma_pagamento=str(dados.get("forma_pagamento", "")),
        recebido_centavos=dados.get("recebido_centavos"),
        troco_centavos=dados.get("troco_centavos"),
        itens=itens,
        cpf=dados.get("cpf"),
    )
