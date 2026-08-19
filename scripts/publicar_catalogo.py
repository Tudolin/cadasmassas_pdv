"""
Publica o catalogo no Upstash Redis, no formato que o PDV le.

POR QUE ESTE SCRIPT EXISTE
==========================

O modelo combinado diz que o precifier e a fonte de verdade e escreve
`produto:{plu}` / `produto_ean:{codigo}` / `catalogo:versao`. Hoje ele
**nao escreve nada disso**: grava seis chaves de lista (`precifier:pratos`,
`precifier:insumos`, ...) e o objeto `Prato` nao tem campo de PLU nem de
codigo de barras -- nao existe como ligar um prato do precifier a uma
etiqueta da balanca.

Quem sabe o PLU de cada produto e a balanca, e essa informacao esta na
tabela `produtos` do SQLite do PDV atual (`pdv_database.db`: 153 produtos
com `codigo_barras`, `nome`, `preco`).

Este script faz a ponte: le o SQLite da balanca e publica no Redis o formato
que o PDV espera. Assim o caixa novo funciona hoje, e no dia em que o
precifier ganhar um campo de PLU basta ele gravar as mesmas chaves -- o PDV
nao muda uma linha.

O QUE ELE GRAVA
---------------
    produto:{plu}          -> {nome, preco_kg, categoria, ativo}
    produto_ean:{codigo}   -> {nome, preco_fixo, categoria, ativo}
    catalogo:snapshot      -> tudo num JSON so (atalho de 1 requisicao)
    catalogo:versao        -> inteiro incremental (gravado por ULTIMO)

Uso:
    .venv\\Scripts\\python scripts\\publicar_catalogo.py --simular
    .venv\\Scripts\\python scripts\\publicar_catalogo.py
    .venv\\Scripts\\python scripts\\publicar_catalogo.py --limpar-antigos
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdv.catalogo import (
    CHAVE_SNAPSHOT,
    CHAVE_VERSAO,
    PREFIXO_PRODUTO,
    PREFIXO_PRODUTO_EAN,
)
from pdv.config import carregar_config
from pdv.importador import ResultadoImportacao, ler_sqlite_balanca
from pdv.upstash import ClienteUpstash, ErroUpstash


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        description="Publica o catalogo da balanca no Upstash Redis"
    )
    analisador.add_argument(
        "--banco",
        default="pdv_database.db",
        help="SQLite com a tabela `produtos` (padrao: pdv_database.db)",
    )
    analisador.add_argument(
        "--simular",
        action="store_true",
        help="mostra o que seria publicado, sem gravar nada",
    )
    analisador.add_argument(
        "--limpar-antigos",
        action="store_true",
        help="apaga produto:*/produto_ean:* que nao estao mais no SQLite",
    )
    argumentos = analisador.parse_args(argv)

    origem = Path(argumentos.banco)
    if not origem.is_file():
        print(f"ERRO: nao achei o banco {origem.resolve()}")
        print(
            "\nEste arquivo e o SQLite do PDV atual, com a tabela `produtos`.\n"
            "Ele esta na raiz deste repositorio (pdv_database.db)."
        )
        return 1

    print(f"Lendo {origem.resolve()} ...")
    resultado = ler_sqlite_balanca(origem)
    _mostrar(resultado)

    if resultado.total == 0:
        print("\nNada para publicar.")
        return 1

    if argumentos.simular:
        print("\n--simular: nada foi gravado.")
        return 0

    config = carregar_config()
    if not config.upstash_configurado:
        print(
            "\nERRO: UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN nao "
            "estao definidas.\nRode primeiro: python scripts\\testar_redis.py"
        )
        return 1

    cliente = ClienteUpstash(
        config.upstash_url, config.upstash_token, timeout_s=config.timeout_rede_s
    )

    try:
        return _publicar(cliente, resultado, argumentos.limpar_antigos)
    except ErroUpstash as erro:
        print(f"\nERRO ao publicar: {erro}")
        print("Rode `python scripts\\testar_redis.py` para diagnosticar.")
        return 1


def _mostrar(resultado: ResultadoImportacao) -> None:
    print(f"\n  {len(resultado.por_peso):>4} produto(s) por peso (PLU da balanca)")
    print(f"  {len(resultado.por_unidade):>4} produto(s) por unidade (EAN)")

    if resultado.ignorados:
        print(f"\n  {len(resultado.ignorados)} produto(s) NAO publicado(s):")
        for item in resultado.ignorados[:15]:
            print(f"    - {item}")
        if len(resultado.ignorados) > 15:
            print(f"    ... e outros {len(resultado.ignorados) - 15}")

    print("\n  Por categoria:")
    for categoria, quantos in resultado.por_categoria().items():
        print(f"    {quantos:>4}  {categoria}")

    print("\n  Amostra do que sera gravado:")
    for item in resultado.por_peso[:3]:
        print(
            f"    {PREFIXO_PRODUTO}{item['plu']} -> "
            f"{json.dumps(item, ensure_ascii=False)}"
        )
    for item in resultado.por_unidade[:2]:
        print(
            f"    {PREFIXO_PRODUTO_EAN}{item['codigo']} -> "
            f"{json.dumps(item, ensure_ascii=False)}"
        )


def _publicar(
    cliente: ClienteUpstash,
    resultado: ResultadoImportacao,
    limpar_antigos: bool,
) -> int:
    print("\nPublicando no Upstash...")

    comandos: list[list[Any]] = [
        ["SET", f"{PREFIXO_PRODUTO}{item['plu']}", json.dumps(item, ensure_ascii=False)]
        for item in resultado.por_peso
    ]
    comandos += [
        [
            "SET",
            f"{PREFIXO_PRODUTO_EAN}{item['codigo']}",
            json.dumps(item, ensure_ascii=False),
        ]
        for item in resultado.por_unidade
    ]

    LOTE = 100
    for inicio in range(0, len(comandos), LOTE):
        cliente.pipeline(comandos[inicio : inicio + LOTE])
        print(f"  {min(inicio + LOTE, len(comandos))}/{len(comandos)} chaves")

    if limpar_antigos:
        _limpar_antigos(cliente, resultado)

    # Snapshot de chave unica: com ele o PDV sincroniza em 1 requisicao em vez
    # de 1 SCAN + N GETs.
    versao_anterior = cliente.get(CHAVE_VERSAO)
    try:
        nova_versao = int(versao_anterior or 0) + 1
    except (TypeError, ValueError):
        nova_versao = 1

    cliente.set_json(
        CHAVE_SNAPSHOT,
        {
            "versao": str(nova_versao),
            "produtos": resultado.por_peso,
            "eans": resultado.por_unidade,
        },
    )
    print(f"  {CHAVE_SNAPSHOT} gravado")

    # A versao vai por ULTIMO de proposito: se a publicacao falhasse no meio
    # com a versao ja atualizada, o PDV veria "versao nova" e pararia de
    # tentar, ficando com catalogo pela metade. Gravada no fim, ela funciona
    # como confirmacao de que tudo subiu.
    cliente.comando("SET", CHAVE_VERSAO, str(nova_versao))
    print(f"  {CHAVE_VERSAO} = {nova_versao} (era {versao_anterior or 'inexistente'})")

    print(
        f"\nPronto. {resultado.total} produto(s) publicado(s).\n"
        f"O PDV pega a versao {nova_versao} na proxima checagem (ate 60 s) "
        f"ou na hora,\nse voce clicar em 'Atualizar catalogo' na tela do caixa."
    )
    return 0


def _limpar_antigos(cliente: ClienteUpstash, resultado: ResultadoImportacao) -> None:
    """Apaga chaves de produto que nao existem mais no SQLite de origem."""
    atuais = {f"{PREFIXO_PRODUTO}{item['plu']}" for item in resultado.por_peso}
    atuais |= {
        f"{PREFIXO_PRODUTO_EAN}{item['codigo']}" for item in resultado.por_unidade
    }

    remotas = set(cliente.scan_chaves(f"{PREFIXO_PRODUTO}*"))
    remotas |= set(cliente.scan_chaves(f"{PREFIXO_PRODUTO_EAN}*"))

    sobrando = sorted(remotas - atuais)
    if not sobrando:
        print("  nenhuma chave antiga para apagar")
        return

    print(f"  apagando {len(sobrando)} chave(s) que nao estao mais no SQLite:")
    for chave in sobrando[:10]:
        print(f"    - {chave}")
    if len(sobrando) > 10:
        print(f"    ... e outras {len(sobrando) - 10}")

    cliente.pipeline([["DEL", chave] for chave in sobrando])


if __name__ == "__main__":
    raise SystemExit(main())
