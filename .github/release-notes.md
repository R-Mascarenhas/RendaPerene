## Novidades em 0.13.1

- Preenchimento do preço em compras e vendas manuais pelo fechamento diário do Yahoo Finance,
  consultado em segundo plano. O preço continua editável e a consulta preserva o valor digitado.
- Correção na preservação da fila de revisão de proventos e ajustes visuais nas ações.
- Reorganização interna da edição dos parâmetros de Bazin e do ciclo de busca de proventos.
- Correção de compatibilidade com pandas 3 no cálculo de aportes em períodos sem negociações.

## Sistemas suportados

- Windows 10 ou posterior, 64 bits.
- Ubuntu 22.04 ou posterior, 64 bits.

## Instalação

- Windows: baixe e execute `RendaPerene-vX.Y.Z-windows-x64-setup.exe`. O instalador sugere
  `%LOCALAPPDATA%\Programs\RendaPerene`, permite escolher outra pasta e oferece atalhos.
  Feche o aplicativo antes de atualizar e execute o novo instalador; ele reutiliza a pasta
  anterior e mantém os mesmos atalhos.
- Ubuntu: baixe o `.deb` e instale pelo gerenciador de aplicativos ou com
  `sudo apt install ./RendaPerene-vX.Y.Z-ubuntu-x64.deb`. Abra **RendaPerene** pelo menu ou
  execute `rendaperene`, sem `sudo`. Para atualizar, feche o aplicativo e instale o novo pacote.

Os arquivos `.sha256` permitem verificar a integridade do download.
Usuários dos ZIPs e TAR.GZ antigos precisam baixar o primeiro instalador manualmente neste
GitHub Releases: o aviso das versões antigas procura somente esses formatos. Passe a usar o atalho
criado pelo instalador; cópias antigas do executável continuam abrindo a versão antiga.

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
