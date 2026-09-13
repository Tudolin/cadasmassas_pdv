"""
Teste de conexao com o Upstash Redis.

Rode isto ANTES de abrir o caixa numa maquina nova. Ele responde, em
portugues e na ordem em que as coisas costumam dar errado:

  1. as variaveis de ambiente existem?
  2. o servidor responde (PING)?
  3. quanto tempo leva uma ida e volta?
  4. da para ESCREVER (o PDV precisa gravar `venda:*`)?
  5. o catalogo esta publicado e em que formato?
  6. os produtos tem preco valido?

Uso:
    .venv\\Scripts\\python scripts\\testar_redis.py
    .venv\\Scripts\\python scripts\\testar_redis.py --detalhado

Codigo de saida 0 = tudo pronto para vender. Diferente de 0 = tem problema,
e a saida diz qual.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Permite rodar como `python scripts/testar_redis.py` sem instalar o pacote.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdv.catalogo import (
    CHAVE_SNAPSHOT,
    CHAVE_VERSAO,
    PREFIXO_PRODUTO,
    PREFIXO_PRODUTO_EAN,
)
from pdv.config import carregar_config
from pdv.upstash import ClienteUpstash, ErroUpstash

CHAVE_DE_TESTE = "pdv:teste:conexao"

OK = "  [ok]   "
FALHA = "  [FALHA]"
ALERTA = "  [aviso]"


def titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * len(texto)}")


def mascarar(segredo: str) -> str:
    """Mostra so o suficiente para conferir se e o token certo."""
    if len(segredo) <= 12:
        return "*" * len(segredo)
    return f"{segredo[:6]}...{segredo[-4:]} ({len(segredo)} caracteres)"


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Testa o Upstash do PDV")
    analisador.add_argument(
        "--detalhado", action="store_true", help="lista os produtos encontrados"
    )
    analisador.add_argument(
        "--sem-escrita",
        action="store_true",
        help="nao testa gravacao (use com token somente-leitura)",
    )
    argumentos = analisador.parse_args(argv)

    print("=" * 62)
    print("  TESTE DE CONEXAO - PDV Casa das Massas <-> Upstash Redis")
    print("=" * 62)

    problemas: list[str] = []
    avisos: list[str] = []

    # ---------------------------------------------------------------- 1/6
    titulo("1/6  Variaveis de ambiente")
    config = carregar_config()

    if not config.upstash_url:
        print(f"{FALHA} UPSTASH_REDIS_REST_URL nao esta definida.")
        problemas.append("URL ausente")
    else:
        print(f"{OK} URL:   {config.upstash_url}")
        if not config.upstash_url.startswith("https://"):
            print(f"{ALERTA} a URL deveria comecar com https://")
            avisos.append("URL sem https")

    if not config.upstash_token:
        print(f"{FALHA} UPSTASH_REDIS_REST_TOKEN nao esta definida.")
        problemas.append("token ausente")
    else:
        print(f"{OK} Token: {mascarar(config.upstash_token)}")

    if problemas:
        print(
            "\nNao da para continuar sem URL e token. "
            "Crie o arquivo .env na raiz do projeto:\n\n"
            "    UPSTASH_REDIS_REST_URL=https://seu-banco.upstash.io\n"
            "    UPSTASH_REDIS_REST_TOKEN=seu-token-aqui\n\n"
            "O README explica onde achar esses dois valores "
            "(secao 'Configurar o Upstash Redis')."
        )
        return 1

    cliente = ClienteUpstash(
        config.upstash_url, config.upstash_token, timeout_s=config.timeout_rede_s
    )

    # ---------------------------------------------------------------- 2/6
    titulo("2/6  O servidor responde? (PING)")
    try:
        inicio = time.monotonic()
        resposta = cliente.comando("PING")
        decorrido = (time.monotonic() - inicio) * 1000
    except ErroUpstash as erro:
        print(f"{FALHA} {erro}")
        print(_dica_do_erro(str(erro)))
        if "certificate" in str(erro).lower() or "ssl" in str(erro).lower():
            _tentar_diagnosticar_certificado(config.upstash_url)
        return 1

    if resposta == "PONG":
        print(f"{OK} PONG em {decorrido:.0f} ms")
    else:
        print(f"{ALERTA} resposta inesperada: {resposta!r}")
        avisos.append("PING estranho")

    # ---------------------------------------------------------------- 3/6
    titulo("3/6  Latencia (5 idas e voltas)")
    tempos: list[float] = []
    for _ in range(5):
        inicio = time.monotonic()
        try:
            cliente.comando("PING")
        except ErroUpstash as erro:
            print(f"{FALHA} caiu no meio da medicao: {erro}")
            problemas.append("instavel")
            break
        tempos.append((time.monotonic() - inicio) * 1000)

    if tempos:
        media = sum(tempos) / len(tempos)
        print(
            f"{OK} media {media:.0f} ms "
            f"(min {min(tempos):.0f} / max {max(tempos):.0f})"
        )
        if media > 1500:
            print(
                f"{ALERTA} acima de 1,5 s. Nao impede o caixa de funcionar "
                f"(nenhuma leitura de codigo espera rede), mas a fila de "
                f"vendas vai esvaziar devagar."
            )
            avisos.append("latencia alta")

    # ---------------------------------------------------------------- 4/6
    titulo("4/6  Permissao de escrita (o PDV grava venda:*)")
    if argumentos.sem_escrita:
        print(f"{ALERTA} pulado por --sem-escrita")
        avisos.append("escrita nao testada")
    else:
        try:
            marca = f"teste-{int(time.time())}"
            cliente.comando("SET", CHAVE_DE_TESTE, marca, "EX", "60")
            lido = cliente.get(CHAVE_DE_TESTE)
            cliente.comando("DEL", CHAVE_DE_TESTE)

            if lido == marca:
                print(f"{OK} gravou, leu e apagou `{CHAVE_DE_TESTE}`")
            else:
                print(f"{FALHA} gravou {marca!r} mas leu {lido!r}")
                problemas.append("escrita inconsistente")
        except ErroUpstash as erro:
            print(f"{FALHA} {erro}")
            if "permission" in str(erro).lower() or "readonly" in str(erro).lower():
                print(
                    "         Este token parece ser SOMENTE LEITURA. O PDV "
                    "precisa gravar em `venda:*`.\n"
                    "         No painel do Upstash, use o token normal "
                    "(nao o 'Read-Only Token')."
                )
            problemas.append("sem permissao de escrita")

    # ---------------------------------------------------------------- 5/6
    titulo("5/6  Catalogo publicado")
    try:
        versao = cliente.get(CHAVE_VERSAO)
        if versao is None:
            print(f"{ALERTA} `{CHAVE_VERSAO}` nao existe.")
            print(
                "         Sem ela o PDV baixa o catalogo inteiro a cada "
                "checagem em vez de so quando muda. Funciona, mas gasta rede.\n"
                "         `scripts/publicar_catalogo.py` cria essa chave."
            )
            avisos.append("catalogo:versao ausente")
        else:
            print(f"{OK} {CHAVE_VERSAO} = {versao}")

        snapshot = cliente.get_json(CHAVE_SNAPSHOT)
        formato = None

        if isinstance(snapshot, dict) and (
            snapshot.get("produtos") or snapshot.get("eans")
        ):
            formato = "snapshot"
            quantos_peso = len(snapshot.get("produtos") or [])
            quantos_ean = len(snapshot.get("eans") or [])
            print(
                f"{OK} `{CHAVE_SNAPSHOT}` presente: "
                f"{quantos_peso} por peso + {quantos_ean} por unidade "
                f"(1 requisicao por sincronizacao)"
            )
        else:
            print(
                f"{ALERTA} `{CHAVE_SNAPSHOT}` nao existe; procurando chave a chave..."
            )
            chaves_peso = cliente.scan_chaves(f"{PREFIXO_PRODUTO}*")
            chaves_ean = cliente.scan_chaves(f"{PREFIXO_PRODUTO_EAN}*")
            quantos_peso, quantos_ean = len(chaves_peso), len(chaves_ean)

            if quantos_peso or quantos_ean:
                formato = "chaves"
                print(
                    f"{OK} {quantos_peso} chave(s) `{PREFIXO_PRODUTO}*` e "
                    f"{quantos_ean} `{PREFIXO_PRODUTO_EAN}*`"
                )
            else:
                print(f"{FALHA} nenhum produto encontrado no banco.")
                print(
                    "         O PDV vai abrir, mas TODA leitura vai dizer "
                    "'nao esta no catalogo'.\n"
                    "         Rode: python scripts\\publicar_catalogo.py"
                )
                problemas.append("catalogo vazio")

        # ------------------------------------------------------------ 6/6
        titulo("6/6  Sanidade dos produtos")
        if formato is None:
            print(f"{ALERTA} nada para conferir (catalogo vazio)")
        else:
            _conferir_produtos(cliente, formato, snapshot, argumentos.detalhado, avisos)

    except ErroUpstash as erro:
        print(f"{FALHA} {erro}")
        problemas.append("falha ao ler catalogo")

    # -------------------------------------------------------------- resumo
    print("\n" + "=" * 62)
    if problemas:
        print("  RESULTADO: TEM PROBLEMA")
        for item in problemas:
            print(f"    - {item}")
        print("=" * 62)
        return 1

    if avisos:
        print("  RESULTADO: FUNCIONA, COM RESSALVAS")
        for item in avisos:
            print(f"    - {item}")
        print("=" * 62)
        return 0

    print("  RESULTADO: TUDO PRONTO PARA VENDER")
    print("=" * 62)
    return 0


def _conferir_produtos(
    cliente: ClienteUpstash,
    formato: str,
    snapshot: object,
    detalhado: bool,
    avisos: list[str],
) -> None:
    """Usa o mesmo carregador do PDV, para o teste refletir o que ele vera."""
    from tempfile import TemporaryDirectory

    from pdv.catalogo import Catalogo
    from pdv.db import Banco

    with TemporaryDirectory() as pasta:
        catalogo = Catalogo(Banco(Path(pasta) / "teste.db"), cliente)
        try:
            por_plu, por_ean, versao = catalogo._baixar(None)
        except ErroUpstash as erro:
            print(f"{FALHA} {erro}")
            return

    ativos_peso = sum(1 for p in por_plu.values() if p.ativo)
    ativos_ean = sum(1 for u in por_ean.values() if u.ativo)

    print(
        f"{OK} o PDV entenderia {len(por_plu)} produto(s) por peso "
        f"({ativos_peso} ativo(s)) e {len(por_ean)} por unidade "
        f"({ativos_ean} ativo(s))"
    )
    print(f"{OK} versao efetiva do catalogo: {versao}")

    if len(por_plu) + len(por_ean) == 0:
        print(
            f"{ALERTA} nenhum produto passou pela validacao. Causa mais comum: "
            f"falta `preco_kg` (por peso) ou `preco_fixo` (por unidade)."
        )
        avisos.append("produtos sem preco valido")
        return

    if ativos_peso + ativos_ean == 0:
        print(f"{ALERTA} todos os produtos estao com ativo=false.")
        avisos.append("todos inativos")

    if detalhado:
        print("\n  Produtos por peso (PLU -> nome, preco/kg):")
        for plu in sorted(por_plu):
            produto = por_plu[plu]
            marca = "" if produto.ativo else "  [INATIVO]"
            print(
                f"    {plu:>4}  {produto.nome[:34]:<34} "
                f"R$ {produto.preco_kg:>8.2f}/kg{marca}"
            )
        print("\n  Produtos por unidade (EAN -> nome, preco):")
        for codigo in sorted(por_ean):
            unidade = por_ean[codigo]
            marca = "" if unidade.ativo else "  [INATIVO]"
            print(
                f"    {codigo:<14} {unidade.nome[:30]:<30} "
                f"R$ {unidade.preco:>8.2f}{marca}"
            )


def _tentar_diagnosticar_certificado(url: str) -> None:
    """
    Conecta de novo, sem validar nada, so para dizer QUEM emitiu o
    certificado -- se nao for Amazon/Upstash/Let's Encrypt, o nome que
    aparece geralmente e o do proprio antivirus/proxy que esta interceptando
    o HTTPS. Nunca deixa uma falha aqui (rede pior ainda, python antigo sem a
    API interna) esconder o resultado do PING que já foi reportado acima.
    """
    from urllib.parse import urlparse

    host = urlparse(url).hostname if url else None
    if not host:
        return

    print("\n         Verificando quem emitiu o certificado...")
    try:
        from diagnosticar_certificado import diagnosticar

        for linha in diagnosticar(host).splitlines():
            print(f"         {linha}" if linha else "")
    except Exception as erro:  # diagnostico e so um extra, nao pode travar o teste principal
        print(f"         (nao consegui diagnosticar: {erro})")


def _dica_do_erro(erro: str) -> str:
    """Traduz o erro cru numa acao concreta."""
    baixo = erro.lower()

    if "401" in baixo or "unauthorized" in baixo:
        return (
            "         O token foi recusado. Copie de novo do painel do "
            "Upstash\n"
            "         (Database -> REST API -> UPSTASH_REDIS_REST_TOKEN) e "
            "confira\n"
            "         se nao ficou espaco ou quebra de linha no .env."
        )
    if "404" in baixo:
        return (
            "         URL nao encontrada. Confira se a URL e a do endpoint "
            "REST\n"
            "         (termina em .upstash.io) e nao a de conexao redis://."
        )
    if "name or service not known" in baixo or "getaddrinfo" in baixo:
        return (
            "         Nao resolveu o endereco: ou a URL esta com erro de "
            "digitacao,\n"
            "         ou a maquina esta sem internet/DNS."
        )
    if "timed out" in baixo or "timeout" in baixo:
        return (
            "         Tempo esgotado. Internet caida, ou firewall/proxy da "
            "loja\n"
            "         bloqueando HTTPS de saida para *.upstash.io."
        )
    if "certificate" in baixo or "ssl" in baixo:
        return (
            "         Erro de certificado TLS. Costuma ser antivirus ou "
            "proxy\n"
            "         corporativo interceptando HTTPS."
        )
    return "         Veja a mensagem acima; o README tem a secao de problemas comuns."


if __name__ == "__main__":
    raise SystemExit(main())
