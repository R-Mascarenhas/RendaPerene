## Novidades em 0.10.0

- Backups locais agora são publicados como pacotes `.rpb` criptografados por senha, com
  AES-256-GCM e derivação de chave Argon2id. Uma chave de recuperação opcional pode ser baixada
  separadamente e deve ser guardada fora do pacote.
- A nova tela de restauração autentica e valida backups locais ou enviados pelo usuário antes de
  restaurar uma carteira. Ela confere hashes, integridade SQLite, identidade e compatibilidade do
  schema, permite prévia e confirmação explícita e preserva a versão anterior em
  `backups/pre-restore/` antes de substituí-la.
- O aplicativo verifica em segundo plano, uma vez por sessão, se há uma versão mais nova no
  GitHub Releases e oferece o pacote compatível para Windows ou Ubuntu x64, sem enviar dados da
  carteira.
- O logging foi centralizado: a saída padrão registra eventos seguros da aplicação, e logs locais
  rotacionados podem ser habilitados com `LOG_TO_FILE=true`. Dados financeiros, nomes de
  carteiras e identificadores de sessão não são registrados.

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

Os backups criados pela interface são criptografados e a restauração é feita nela própria. A senha
ou chave de recuperação não é armazenada pela aplicação; perder ambas impede recuperar o pacote.

## Limitações conhecidas

- O aplicativo não atualiza instalações existentes automaticamente.
- Dados de mercado dependem de acesso à rede e das integrações públicas configuradas.
- O aplicativo não é assinado digitalmente e não é distribuído por lojas de aplicativos.
