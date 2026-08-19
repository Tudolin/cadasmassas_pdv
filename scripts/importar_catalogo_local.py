"""
Carrega o catalogo da balanca direto no cache local do PDV.

Use isto na INSTALACAO, antes de configurar o Upstash: o caixa passa a
vender na hora, 100%% offline. Depois, quando o Upstash estiver configurado
e o catalogo publicado, a sincronizacao substitui este conteudo sozinha.

Tambem serve de plano B: se o Upstash cair e o cache local estiver vazio
(maquina nova), este comando devolve o caixa ao ar em segundos.

Uso:
    .venv\\Scripts\\python scripts\\importar_catalogo_local.py
    .venv\\Scripts\\python scripts\\importar_catalogo_local.py --banco outro.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdv.config import carregar_config
from pdv.db import Banco
from pdv.importador import (
    gravar_no_cache_local,
    ler_sqlite_balanca,
)


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        description="Importa o catalogo da balanca para o cache local do PDV"
    )
    analisador.add_argument(
        "--banco",
        default="pdv_database.db",
        help="SQLite de origem, com a tabela `produtos` (padrao: pdv_database.db)",
    )
    argumentos = analisador.parse_args(argv)

    origem = Path(argumentos.banco)
    if not origem.is_file():
        print(f"ERRO: nao achei {origem.resolve()}")
        return 1

    print(f"Lendo {origem.resolve()} ...")
    resultado = ler_sqlite_balanca(origem)

    print(f"\n  {len(resultado.por_peso):>4} produto(s) por peso (PLU da balanca)")
    print(f"  {len(resultado.por_unidade):>4} produto(s) por unidade (EAN)")

    if resultado.ignorados:
        print(f"\n  {len(resultado.ignorados)} produto(s) NAO importado(s):")
        for item in resultado.ignorados[:15]:
            print(f"    - {item}")
        if len(resultado.ignorados) > 15:
            print(f"    ... e outros {len(resultado.ignorados) - 15}")
        print(
            "\n  Estes produtos nao vao aparecer no caixa. Ajuste o preco na\n"
            "  balanca (ou no precifier) e rode este comando de novo."
        )

    print("\n  Por categoria:")
    for categoria, quantos in resultado.por_categoria().items():
        print(f"    {quantos:>4}  {categoria}")

    if resultado.total == 0:
        print("\nNada para importar.")
        return 1

    config = carregar_config()
    banco = Banco(config.banco)
    gravar_no_cache_local(banco, resultado, versao=f"local-{origem.stat().st_mtime_ns}")

    print(
        f"\nPronto. {resultado.total} produto(s) no cache local "
        f"({config.banco}).\nInicie o PDV com:  python run.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
