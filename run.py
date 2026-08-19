"""
Entrada do PDV: sobe o waitress e (opcionalmente) abre a tela.

Uso:
    python run.py                 # servidor + abre o navegador
    python run.py --sem-navegador # so o servidor
    python run.py --janela        # janela nativa (pywebview, se instalado)

Nao use `flask run` nem `app.run()`: o servidor de desenvolvimento do Flask
e single-thread por padrao e nao foi feito para ficar de pe o dia inteiro.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from pdv.config import carregar_config
from pdv.web import Aplicacao, criar_app

RAIZ = Path(__file__).resolve().parent


def configurar_log(nivel: str = "INFO") -> None:
    pasta = RAIZ / "dados"
    pasta.mkdir(parents=True, exist_ok=True)

    formato = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"

    manipuladores: list[logging.Handler] = [
        # `delay=True`: o arquivo so e aberto quando houver a primeira linha
        # de log, o que tira um I/O do caminho do boot.
        logging.FileHandler(pasta / "pdv.log", encoding="utf-8", delay=True),
    ]
    # Sob `pythonw.exe` (usado no inicio automatico, para nao piscar console)
    # nao existe saida padrao: `sys.stdout` vem None quando ninguem
    # redirecionou. StreamHandler(None) escreveria em stderr e, se stderr
    # tambem for None, estoura -- derrubando o PDV por causa de um log.
    if sys.stdout is not None:
        manipuladores.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format=formato,
        handlers=manipuladores,
    )
    # O waitress loga cada requisicao em INFO; num caixa isso e ruido.
    logging.getLogger("waitress").setLevel(logging.WARNING)


def porta_livre(host: str, porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as teste:
        teste.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return teste.connect_ex((host, porta)) != 0


def esperar_e_abrir(url: str, host: str, porta: int, *, timeout: float = 15.0) -> None:
    """
    Abre o navegador só depois que a porta responde.

    Abrir antes mostra "nao foi possivel conectar" e o operador acha que o
    sistema nao subiu.
    """
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if not porta_livre(host, porta):
            webbrowser.open(url)
            return
        time.sleep(0.1)
    logging.warning("servidor nao respondeu em %.0fs; abra %s a mao", timeout, url)


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="PDV Casa das Massas")
    analisador.add_argument("--sem-navegador", action="store_true")
    analisador.add_argument(
        "--janela",
        action="store_true",
        help="abre em janela nativa (requer pywebview)",
    )
    analisador.add_argument("--log", default="INFO")
    argumentos = analisador.parse_args(argv)

    configurar_log(argumentos.log)
    log = logging.getLogger("pdv")

    inicio = time.monotonic()
    config = carregar_config()

    if not porta_livre(config.host, config.porta):
        # Provavelmente o PDV ja esta rodando (a tarefa agendada disparou
        # duas vezes). Abrir a tela do que ja esta de pe e o certo.
        log.warning("porta %d ja esta em uso; abrindo a tela existente", config.porta)
        if not argumentos.sem_navegador:
            webbrowser.open(config.url_local)
        return 0

    aplicacao = Aplicacao(config)
    app = criar_app(config, aplicacao)
    aplicacao.iniciar()

    log.info(
        "PDV pronto em %s (%.2fs) | catalogo: %d itens | upstash: %s",
        config.url_local,
        time.monotonic() - inicio,
        aplicacao.catalogo.snapshot.total,
        "sim" if config.upstash_configurado else "NAO",
    )

    if argumentos.janela:
        return _rodar_com_janela(app, config, aplicacao)

    if not argumentos.sem_navegador:
        threading.Thread(
            target=esperar_e_abrir,
            args=(config.url_local, config.host, config.porta),
            daemon=True,
        ).start()

    from waitress import serve

    try:
        serve(
            app,
            host=config.host,
            port=config.porta,
            threads=config.threads,
            # O caixa e local: nada de esperar cliente lento.
            channel_timeout=60,
            ident="PDV",
        )
    except KeyboardInterrupt:
        log.info("encerrando por Ctrl+C")
    finally:
        aplicacao.parar()
    return 0


def _rodar_com_janela(app, config, aplicacao) -> int:
    """Servidor numa thread + janela nativa na principal (pywebview exige)."""
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        logging.getLogger("pdv").error(
            "pywebview nao esta instalado. Rode: pip install pywebview"
        )
        return 1

    from waitress import serve

    threading.Thread(
        target=serve,
        args=(app,),
        kwargs={
            "host": config.host,
            "port": config.porta,
            "threads": config.threads,
            "ident": "PDV",
        },
        daemon=True,
    ).start()

    try:
        webview.create_window(
            "PDV Casa das Massas", config.url_local, width=1280, height=800
        )
        webview.start()
    finally:
        aplicacao.parar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
