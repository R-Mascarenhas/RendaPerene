## Novidades em 0.9.0

- Novo backup local consistente para uma ou mais carteiras, com validação SQLite, hashes
  SHA-256 e metadados do conjunto criado.
- O catálogo de ativos incluído no aplicativo agora é somente leitura; ativos da carteira que
  não constem nele continuam preservados e podem ser informados manualmente com validação do
  ticker B3.
- Correção do cache das análises de mercado para respeitar a carteira ativa e suas correções
  anuais de proventos.
- O aplicativo passa a ser exclusivamente local, sem o antigo modo de demonstração no
  Streamlit Cloud.
- Suporte oficial ao Python 3.10 até o Python 3.14.

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

O backup criado pela interface ainda não é criptografado e a restauração permanece manual.

## Limitações conhecidas

- O aplicativo não atualiza instalações existentes automaticamente.
- Dados de mercado dependem de acesso à rede e das integrações públicas configuradas.
- O aplicativo não é assinado digitalmente e não é distribuído por lojas de aplicativos.
