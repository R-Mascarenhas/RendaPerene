## Sistemas suportados

- Windows 10 ou posterior, 64 bits.
- Ubuntu 22.04 ou posterior, 64 bits.

## Instalação

Baixe o arquivo correspondente ao seu sistema operacional e extraia-o em uma pasta própria.
Execute o aplicativo dentro da pasta extraída. Os arquivos `.sha256` permitem verificar a
integridade do download com uma ferramenta compatível com SHA-256.

## Dados persistentes

As carteiras ficam fora da pasta do aplicativo:

- Windows: `%LOCALAPPDATA%\\RendaPerene`;
- Linux: `$XDG_DATA_HOME/RendaPerene` ou `~/.local/share/RendaPerene`.

Antes de substituir uma versão instalada, preserve uma cópia da pasta de dados. A aplicação
detecta bancos legados e oferece a migração para o layout atual na primeira execução.

## Limitações conhecidas

- O aplicativo não atualiza instalações existentes automaticamente.
- Dados de mercado dependem de acesso à rede e das integrações públicas configuradas.
- O aplicativo não é assinado digitalmente e não é distribuído por lojas de aplicativos.
