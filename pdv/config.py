"""
Configuracao do PDV: variaveis de ambiente com padroes que ja funcionam.

Objetivo: `python run.py` sobe o caixa numa maquina limpa sem nenhum
arquivo de configuracao. O `.env` e opcional e serve para as credenciais
do Upstash e para o nome da impressora.

Sem dependencia de python-dotenv -- o leitor abaixo resolve o formato
`CHAVE=valor` que e tudo o que precisamos, e economiza um import no boot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Config", "DadosLoja", "carregar_config", "carregar_env"]

RAIZ = Path(__file__).resolve().parent.parent


def carregar_env(caminho: Path | None = None) -> None:
    """
    Copia um arquivo `.env` para `os.environ` sem sobrescrever o que ja veio
    do ambiente de verdade (o ambiente ganha do arquivo, sempre).
    """
    arquivo = caminho or RAIZ / ".env"
    if not arquivo.is_file():
        return

    for linha_bruta in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha_bruta.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def _texto(nome: str, padrao: str) -> str:
    valor = os.environ.get(nome, "").strip()
    return valor or padrao


def _inteiro(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "").strip() or padrao)
    except ValueError:
        return padrao


def _booleano(nome: str, padrao: bool = False) -> bool:
    valor = os.environ.get(nome, "").strip().lower()
    if not valor:
        return padrao
    return valor in {"1", "true", "sim", "yes", "on"}


@dataclass(frozen=True, slots=True)
class DadosLoja:
    """Cabecalho do cupom. Vem do cupom que a loja ja imprime hoje."""

    nome: str = "CASA DAS MASSAS - PINHEIRINHO"
    subtitulo: str = "SISTEMA DE VENDAS PDV"
    endereco: str = "R. Mario Gomes Cezar, 230"
    bairro_cidade: str = "Pinheirinho, Curitiba - PR"
    cep: str = "CEP: 81150-313"
    cnpj: str = "32.055.018/0001-87"
    fone: str = "(41) 3268-2817"


@dataclass(frozen=True, slots=True)
class Config:
    # ---- servidor -------------------------------------------------------
    #: Somente loopback: o caixa nao precisa ser visivel na rede da loja.
    host: str = "127.0.0.1"
    porta: int = 8777
    #: Threads do waitress. O caixa e um usuario so; 4 sobra e mantem a
    #: memoria baixa no notebook compartilhado.
    threads: int = 4

    # ---- banco local ----------------------------------------------------
    banco: Path = field(default_factory=lambda: RAIZ / "dados" / "pdv.db")

    # ---- leitura de codigo de barras ------------------------------------
    #: 5 = comportamento do PDV em producao (ate R$ 999,99).
    #: 4 = especificacao escrita (ate R$ 99,99). Ver pdv/codigo_barras.py.
    digitos_preco: int = 5

    # ---- catalogo -------------------------------------------------------
    upstash_url: str = ""
    upstash_token: str = ""
    #: De quanto em quanto tempo comparar `catalogo:versao`.
    intervalo_catalogo_s: int = 60
    #: Timeout curto: sincronizacao nunca deve prender uma thread por muito
    #: tempo, e a leitura de codigo nunca depende dela.
    timeout_rede_s: int = 8

    # ---- fila de vendas -------------------------------------------------
    intervalo_fila_s: int = 15
    max_tentativas_venda: int = 0  # 0 = tenta para sempre, com backoff

    # ---- impressao ------------------------------------------------------
    #: Vazio = usa a impressora padrao do Windows.
    impressora: str = ""
    largura_cupom: int = 48
    #: Impressora termica nao fala UTF-8. cp860 = portugues.
    codepage_cupom: str = "cp860"
    imprimir_habilitado: bool = True
    #: Copia de cada cupom em texto, para quando a impressora falha.
    pasta_cupons: Path = field(default_factory=lambda: RAIZ / "dados" / "cupons")

    # ---- nota fiscal ----------------------------------------------------
    #: Desligada por padrao. Ver o cabecalho de pdv/nota_fiscal.py antes de
    #: ligar: o emissor herdado (Selenium/IOB) nao conclui sem uma pessoa.
    nf_habilitada: bool = False
    #: "arquivo" (padrao, registra o pedido em JSON) ou "iob" (Selenium).
    nf_tipo: str = "arquivo"
    nf_usuario: str = ""
    nf_senha: str = ""
    pasta_nf: Path = field(default_factory=lambda: RAIZ / "dados" / "notas")

    loja: DadosLoja = field(default_factory=DadosLoja)

    @property
    def upstash_configurado(self) -> bool:
        return bool(self.upstash_url and self.upstash_token)

    @property
    def url_local(self) -> str:
        return f"http://{self.host}:{self.porta}/"


def carregar_config() -> Config:
    """Monta a Config a partir do ambiente (lendo o `.env` antes)."""
    carregar_env()

    # Os mesmos tres pares de nomes que o precifier aceita, para o dono
    # poder copiar e colar as variaveis da Vercel sem renomear nada.
    url = (
        (
            os.environ.get("UPSTASH_REDIS_REST_URL")
            or os.environ.get("KV_REST_API_URL")
            or os.environ.get("REDIS_REST_API_URL")
            or ""
        )
        .strip()
        .rstrip("/")
    )
    token = (
        os.environ.get("UPSTASH_REDIS_REST_TOKEN")
        or os.environ.get("KV_REST_API_TOKEN")
        or os.environ.get("REDIS_REST_API_TOKEN")
        or ""
    ).strip()

    banco = Path(_texto("PDV_BANCO", str(RAIZ / "dados" / "pdv.db")))
    cupons = Path(_texto("PDV_PASTA_CUPONS", str(RAIZ / "dados" / "cupons")))

    return Config(
        host=_texto("PDV_HOST", "127.0.0.1"),
        porta=_inteiro("PDV_PORTA", 8777),
        threads=_inteiro("PDV_THREADS", 4),
        banco=banco,
        digitos_preco=_inteiro("PDV_DIGITOS_PRECO", 5),
        upstash_url=url,
        upstash_token=token,
        intervalo_catalogo_s=_inteiro("PDV_INTERVALO_CATALOGO", 60),
        timeout_rede_s=_inteiro("PDV_TIMEOUT_REDE", 8),
        intervalo_fila_s=_inteiro("PDV_INTERVALO_FILA", 15),
        max_tentativas_venda=_inteiro("PDV_MAX_TENTATIVAS_VENDA", 0),
        impressora=_texto("PDV_IMPRESSORA", ""),
        largura_cupom=_inteiro("PDV_LARGURA_CUPOM", 48),
        codepage_cupom=_texto("PDV_CODEPAGE_CUPOM", "cp860"),
        imprimir_habilitado=_booleano("PDV_IMPRIMIR", True),
        pasta_cupons=cupons,
        nf_habilitada=_booleano("PDV_NF_HABILITADA", False),
        nf_tipo=_texto("PDV_NF_TIPO", "arquivo"),
        nf_usuario=_texto("PDV_NF_USUARIO", ""),
        nf_senha=_texto("PDV_NF_SENHA", ""),
        pasta_nf=Path(_texto("PDV_PASTA_NF", str(RAIZ / "dados" / "notas"))),
    )
