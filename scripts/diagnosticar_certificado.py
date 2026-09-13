"""
Descobre QUEM emitiu o certificado TLS que a maquina esta vendo ao falar com
o Upstash -- util quando `testar_redis.py` da erro de
"CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate".

Esse erro quase sempre e antivirus ou proxy corporativo interceptando o
HTTPS (fazendo o papel de "homem no meio" para poder olhar o trafego). Eles
trocam o certificado real do site por um deles proprios; se o emissor abaixo
NAO for da Amazon/Upstash/Let's Encrypt, e essa a causa.

Uso:
    .venv\\Scripts\\python scripts\\diagnosticar_certificado.py
"""

from __future__ import annotations

import os
import socket
import ssl
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdv.config import carregar_config


def descobrir_emissor(host: str, porta: int = 443, timeout: float = 5.0) -> dict | None:
    """
    Conecta SEM validar o certificado (de proposito: e so para ler quem o
    assinou) e devolve o campo `issuer` como dicionario.
    """
    contexto = ssl.create_default_context()
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE

    with socket.create_connection((host, porta), timeout=timeout) as bruto:
        with contexto.wrap_socket(bruto, server_hostname=host) as seguro:
            der = seguro.getpeercert(binary_form=True)

    if not der:
        return None

    caminho = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".pem", delete=False, encoding="ascii"
        ) as arquivo:
            arquivo.write(ssl.DER_cert_to_PEM_cert(der))
            caminho = arquivo.name
        # API interna do CPython, mas estavel ha muitas versoes e e
        # exatamente o que os testes da propria stdlib usam para decodificar
        # um certificado sem precisar de uma dependencia so para isso.
        info = ssl._ssl._test_decode_cert(caminho)
    finally:
        if caminho:
            os.unlink(caminho)

    return dict(item[0] for item in info.get("issuer", ()))


_EMISSORES_CONHECIDOS = ("amazon", "upstash", "let's encrypt", "digicert", "google trust")


def diagnosticar(host: str) -> str:
    """
    Monta o texto de diagnostico para `host`. Usado tanto pelo `main()` deste
    script quanto automaticamente pelo `testar_redis.py` quando o erro de
    PING cheira a certificado.
    """
    try:
        emissor = descobrir_emissor(host)
    except OSError as erro:
        return (
            f"Nao deu nem para conectar em {host}:443 sem validar nada: {erro}\n"
            "Isso aponta para firewall/rede bloqueando a porta 443, nao para "
            "o certificado."
        )

    if not emissor:
        return f"O servidor {host} nao devolveu certificado nenhum (estranho)."

    nome = emissor.get("organizationName") or emissor.get("commonName") or "?"
    linhas = [f"Certificado apresentado por {host} foi emitido por: {nome}"]

    if any(pedaco in nome.lower() for pedaco in _EMISSORES_CONHECIDOS):
        linhas.append(
            "Este emissor e legitimo -- entao NAO e antivirus/proxy trocando "
            "certificado. A causa mais comum quando o emissor e legitimo mas o "
            "Python ainda assim recusa (\"unable to get local issuer "
            "certificate\") e o Windows com a lista de certificados-raiz "
            "desatualizada (comum em maquina que fica muito tempo sem rodar o "
            "Windows Update): falta a raiz do emissor (ex.: 'ISRG Root X1' do "
            "Let's Encrypt) no repositorio de certificados confiaveis do "
            "sistema. Corrija baixando a lista atual da propria Microsoft (nao "
            "depende do Windows Update completo estar liberado), como "
            "Administrador:\n\n"
            "    certutil -generateSSTFromWU roots.sst\n\n"
            "e importando o arquivo `roots.sst` gerado: abra o Gerenciador de "
            "Certificados (`certmgr.msc`) -> Autoridades de Certificacao Raiz "
            "Confiaveis -> Certificados -> botao direito -> Todas as Tarefas -> "
            "Importar -> selecione `roots.sst` (pode aceitar todos). Reinicie "
            "e rode `testar_redis.py` de novo.\n"
            "Menos provavel, mas confira tambem: relogio/data do Windows "
            "errado tambem derruba validacao de certificado."
        )
    else:
        linhas.append(
            "Este NAO e o emissor esperado (Amazon/Upstash/Let's Encrypt/DigiCert).\n"
            "Alguma coisa na maquina esta trocando o certificado -- o nome acima\n"
            "geralmente e o do proprio antivirus ou proxy corporativo. Passos:\n\n"
            "  1. Abra as configuracoes do antivirus instalado e procure por algo\n"
            f"     como 'Inspecao HTTPS', 'Filtro Web' ou 'Protecao de rede' com o\n"
            f"     nome '{nome}'. A maioria (Kaspersky, ESET, Avast, Norton) tem uma\n"
            "     lista de excecoes -- adicione '*.upstash.io' nela.\n"
            "  2. Sem opcao de excecao: desligue temporariamente a inspecao HTTPS,\n"
            "     rode `testar_redis.py` de novo para confirmar, e depois decida\n"
            "     com o dono se deixa desligado so para esse dominio ou no geral.\n"
            "  3. Se a maquina estiver numa rede de empresa/provedor com proxy\n"
            "     obrigatorio, fale com quem administra a rede: e a mesma correcao,\n"
            "     so que do lado deles."
        )

    return "\n".join(linhas)


def main() -> int:
    config = carregar_config()
    host = urlparse(config.upstash_url).hostname if config.upstash_url else None
    if not host:
        print("UPSTASH_REDIS_REST_URL nao esta configurada no .env; nada para testar.")
        return 1

    print(f"Conectando em {host}:443 sem validar certificado, so para ler o emissor...\n")
    print(diagnosticar(host))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
