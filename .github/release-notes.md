## Novidades em 0.13.0

- Backup opcional no **Google Drive**: conecte sua conta, escolha as carteiras e ative o
  backup automático. A aplicação verifica mudanças a cada 10 minutos enquanto a interface
  estiver aberta e mantém uma cópia por carteira e computador na pasta **RendaPerene** do Drive.
  As carteiras continuam armazenadas localmente; a conexão com o Google é opcional.
- Recuperação de carteiras em outro computador pela mesma conta Google, com prévia e
  confirmação antes de restaurar. É possível criar uma carteira ou substituir uma existente,
  preservando uma cópia local anterior. Os dados incluem pagamentos e decisões sobre proventos.
- Credenciais Google protegidas pelo cofre do sistema: Windows Credential Manager ou
  Secret Service no Ubuntu. Desconectar remove as credenciais locais e mantém os backups no Drive.
- Colunas de nível e nome do logger alinhadas nos logs, facilitando a leitura dos registros.

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

Os backups locais `.rpb` criados pela interface são criptografados e a restauração é feita nela
própria. A senha ou chave de recuperação não é armazenada pela aplicação; perder ambas impede
recuperar o pacote.

Os backups no Google Drive `.rpbc` usam a proteção padrão do Drive, sem senha ou criptografia
adicional do RendaPerene. O Google e quem tiver acesso ao arquivo poderão ler os dados da carteira.
Confira o computador de origem e a prévia antes de restaurar: a aplicação não mescla alterações
entre máquinas.

## Limitações conhecidas

- O aplicativo não atualiza instalações existentes automaticamente.
- Dados de mercado dependem de acesso à rede e das integrações públicas configuradas.
- O backup no Google Drive exige configuração OAuth na distribuição e um cofre de credenciais
  disponível no sistema. O uso local e os backups locais continuam disponíveis sem essa integração.
- O backup automático no Drive funciona somente enquanto a interface estiver aberta; o aplicativo
  não gerencia histórico de versões dos arquivos remotos.
- O aplicativo não é assinado digitalmente e não é distribuído por lojas de aplicativos.
