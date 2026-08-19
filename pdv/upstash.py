"""
Cliente minimo do Upstash Redis pela API REST (HTTPS).

Por que nao a biblioteca oficial: a API REST do Upstash e um POST com o
comando dentro de um array JSON. Resolver isso com `urllib` da stdlib custa
o arquivo abaixo e evita arrastar `requests`/`httpx` (e as dependencias
transitivas deles) para dentro de um processo que precisa subir em poucos
segundos num notebook compartilhado.

Nada aqui e chamado no caminho da leitura do codigo de barras. Este modulo
so roda nas threads de sincronizacao.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
from typing import Any

__all__ = ["ClienteUpstash", "ErroUpstash"]

log = logging.getLogger(__name__)


class ErroUpstash(RuntimeError):
    """Falhou a conversa com o Upstash (rede, auth ou erro do Redis)."""


class ClienteUpstash:
    """
    Cliente sincrono e sem estado (fora da configuracao).

    Seguro para usar de mais de uma thread: cada chamada abre e fecha a sua
    propria conexao. Nao guardamos socket aberto de proposito -- o volume e
    baixissimo (uma checagem de versao por minuto, uma venda por vez) e um
    socket ocioso no Windows daria mais dor de cabeca do que ganho.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout_s: int = 8,
        tentativas: int = 3,
    ) -> None:
        if not url or not token:
            raise ValueError("URL e token do Upstash sao obrigatorios")
        self._url = url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s
        self._tentativas = max(1, tentativas)

    # ---------------------------------------------------------------- HTTP

    def _post(self, caminho: str, corpo: Any) -> Any:
        dados = json.dumps(corpo).encode("utf-8")
        pedido = urllib.request.Request(
            f"{self._url}{caminho}",
            data=dados,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )

        ultimo_erro: Exception | None = None
        for tentativa in range(1, self._tentativas + 1):
            try:
                with urllib.request.urlopen(pedido, timeout=self._timeout_s) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as erro:
                detalhe = erro.read().decode("utf-8", "replace")[:300]
                # 4xx nao melhora com repeticao: token errado continua errado.
                if 400 <= erro.code < 500:
                    raise ErroUpstash(f"HTTP {erro.code}: {detalhe}") from erro
                ultimo_erro = ErroUpstash(f"HTTP {erro.code}: {detalhe}")
            except (urllib.error.URLError, TimeoutError, OSError) as erro:
                ultimo_erro = ErroUpstash(f"rede: {erro}")
            except json.JSONDecodeError as erro:
                ultimo_erro = ErroUpstash(f"resposta nao era JSON: {erro}")

            if tentativa < self._tentativas:
                # Backoff curto so para engolir soluco de rede. O backoff
                # longo (minutos) e responsabilidade de quem chama.
                espera = 0.4 * 2 ** (tentativa - 1) + random.uniform(0, 0.2)
                time.sleep(espera)

        raise ultimo_erro or ErroUpstash("falha desconhecida")

    # ------------------------------------------------------------ comandos

    def comando(self, *args: Any) -> Any:
        """
        Roda um comando Redis. Ex.: `cliente.comando("GET", "catalogo:versao")`.

        Devolve o campo `result` da resposta.
        """
        resposta = self._post("", [str(a) for a in args])
        if isinstance(resposta, dict):
            if "error" in resposta:
                raise ErroUpstash(str(resposta["error"]))
            return resposta.get("result")
        raise ErroUpstash(f"formato inesperado: {resposta!r}")

    def pipeline(self, comandos: list[list[Any]]) -> list[Any]:
        """
        Roda varios comandos numa unica viagem de rede.

        Essencial para o catalogo: buscar 150 produtos em 150 requisicoes
        levaria minutos numa conexao ruim; num pipeline e uma ida e volta.
        """
        if not comandos:
            return []

        resposta = self._post("/pipeline", [[str(a) for a in cmd] for cmd in comandos])
        if not isinstance(resposta, list):
            raise ErroUpstash(f"pipeline devolveu {resposta!r}")

        resultados: list[Any] = []
        for item in resposta:
            if isinstance(item, dict) and item.get("error"):
                # Um comando ruim no meio nao derruba os outros -- mas fica
                # registrado para nao virar dado faltando em silencio.
                log.warning("comando do pipeline falhou: %s", item["error"])
                resultados.append(None)
            elif isinstance(item, dict):
                resultados.append(item.get("result"))
            else:
                resultados.append(item)
        return resultados

    # -------------------------------------------------------------- acucar

    def get(self, chave: str) -> str | None:
        valor = self.comando("GET", chave)
        return None if valor is None else str(valor)

    def get_json(self, chave: str) -> Any | None:
        """
        GET seguido de parse.

        O precifier grava via `@vercel/kv`, que serializa o objeto em JSON.
        Se o valor vier como string nao-JSON, devolvemos None em vez de
        estourar -- catalogo meio quebrado nao pode derrubar o caixa.
        """
        bruto = self.get(chave)
        if bruto is None:
            return None
        try:
            return json.loads(bruto)
        except json.JSONDecodeError:
            log.warning("valor de %s nao era JSON valido", chave)
            return None

    def set_json(self, chave: str, valor: Any) -> None:
        self.comando("SET", chave, json.dumps(valor, ensure_ascii=False))

    def scan_chaves(self, padrao: str, *, limite: int = 5000) -> list[str]:
        """
        Lista chaves por padrao (`SCAN` em lote, nao `KEYS`).

        `KEYS` trava o Redis enquanto varre; `SCAN` nao. Mesmo com um
        catalogo pequeno vale manter o habito -- o banco e compartilhado com
        o precifier em producao.
        """
        chaves: list[str] = []
        cursor = "0"
        while True:
            resultado = self.comando("SCAN", cursor, "MATCH", padrao, "COUNT", 200)
            if not isinstance(resultado, list) or len(resultado) != 2:
                raise ErroUpstash(f"SCAN devolveu {resultado!r}")

            cursor = str(resultado[0])
            chaves.extend(str(c) for c in (resultado[1] or []))

            if cursor == "0" or len(chaves) >= limite:
                break
        return chaves[:limite]

    def ping(self) -> bool:
        """Testa credenciais e conectividade. Usado pelo /api/diagnostico."""
        try:
            return self.comando("PING") == "PONG"
        except ErroUpstash:
            return False
