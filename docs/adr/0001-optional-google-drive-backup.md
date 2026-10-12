---
status: accepted
date: 2026-10-11
---

# Backup opcional no Google Drive e credenciais locais

Decisão da issue [#58](https://github.com/R-Mascarenhas/RendaPerene/issues/58), parte da
[#39](https://github.com/R-Mascarenhas/RendaPerene/issues/39): oferecer backup e recuperação
opcionais pelo Google Drive, mantendo as carteiras autoritativas em SQLite local. O objetivo
é recuperar dados em outro computador mediante conexão Google e confirmação, sem exigir
uma senha adicional. O backup local `.rpb` continua criptografado por senha.

## Decisões

- O usuário conecta sua conta e ativa explicitamente o backup das carteiras escolhidas.
  Verificar mudanças a cada 10 minutos enquanto a aplicação estiver aberta; carteiras novas
  não entram automaticamente na seleção, inclusive quando reutilizam um nome de arquivo.
  Vincular a seleção à identidade da carteira. Sem mudanças, não reenviar o pacote.
- Usar pasta visível `RendaPerene` e escopo `drive.file`. Identificar pasta e arquivos por IDs
  e marcadores próprios: uma pasta preexistente não fica autorizada apenas pelo nome.
- Manter um arquivo `.rpbc` por UUID da carteira e UUID da instalação. Cada máquina atualiza
  somente sua cópia, sem excluir previamente o arquivo remoto. Renomear carteira ou máquina
  mantém esse par; adicionar máquinas ou carteiras cria novos arquivos.
- Usar a proteção padrão do Drive, sem criptografia própria nem upload de chave. Os pacotes
  contêm snapshots SQLite completos e metadados de recuperação; Google e quem receber acesso
  ao arquivo podem ler seu conteúdo. Tokens, senhas, chaves, logs, planilhas e caches ficam fora
  dos pacotes. O nome legível da máquina é informado pelo usuário, sem coleta de hostname.
- Autorizar por OAuth desktop com PKCE `S256`, `state` e retorno loopback em `127.0.0.1`.
  Solicitar popup no navegador atual e oferecer link para nova aba. Somente a sessão iniciadora
  recebe a URL; verificador e tokens ficam no backend. OAuth não cria contas do RendaPerene.
- Guardar tokens exclusivamente no Windows Credential Manager ou Secret Service do Ubuntu,
  mediante verificação de leitura, gravação e remoção. Cofre indisponível impede a conexão
  remota; uso local permanece disponível. Backends em texto puro, nulos ou não aprovados e
  conexão apenas em memória não são alternativas ao cofre.
- Solicitar acesso offline. Uma nova autorização sem refresh token não conclui a conexão e
  pede nova tentativa, sem sobrescrever credenciais já salvas. A retomada de conexão usa
  credenciais válidas do cofre para o mesmo cliente. Falha ao salvar tokens após consentimento
  descarta a nova credencial em memória e orienta revogar o acesso concedido.
- Distribuir a mesma identidade OAuth nas versões Windows e Ubuntu. O mantenedor controla
  projeto, consentimento e cliente; mudanças exigem um plano para acesso aos backups antigos.
  O ID e o segredo do cliente desktop são configuração distribuível, não credenciais pessoais.
- Consultar os backups ao conectar e antes dos envios. Ordenar pelo horário de atualização
  do Drive apenas como sugestão; mostrar as cópias e máquinas de origem. Ignorar a oferta de
  recuperação não bloqueia envios: salvar a seleção com o backup ativado é o consentimento.
  Exigir confirmação para restaurar. A aplicação não mescla carteiras nem substitui dados
  silenciosamente.
- Para uma identidade nova, permitir escolher uma carteira local a substituir ou criar outra.
  Fixar destino, identidade e conteúdo locais, revalidar antes da publicação e preservar cópia
  anterior e rollback. Uma identidade já instalada corresponde ao destino existente e não pode
  ser duplicada em outro arquivo. Validar estrutura, hashes, SQLite e schema do pacote.
- Desconectar remove credenciais locais e interrompe operações remotas. Falha de remoção é
  informada e mantém uma pendência recuperável, inclusive após reiniciar, com nova tentativa
  sem reautorizar. Revogar acesso no Google e excluir backups são ações separadas; não há exclusão
  automática nem histórico de versões gerenciado pelo aplicativo.

## Alternativas consideradas

| Alternativa | Motivo da escolha atual |
| --- | --- |
| Somente backup local | Continua disponível, mas exige transferência manual entre computadores. |
| Criptografia própria com senha ou chave | Exige outro segredo para recuperação; preservada no backup local e adiada na nuvem. |
| Chave junto do pacote no Drive | Acrescenta gestão de chaves sem proteger contra acesso a ambos os arquivos. |
| Pasta oculta `appDataFolder` | Não atende à pasta visível escolhida; `drive.file` limita o acesso aos arquivos do aplicativo. |
| Um arquivo por carteira compartilhado entre máquinas | Permite que uma máquina sobrescreva a cópia da outra. |
| Tokens em arquivo ou conexão sem cofre | Enfraquece a proteção das credenciais para ampliar compatibilidade. |

A decisão substitui as premissas iniciais da #39 de usar `drive.appdata`, criptografia antes do
upload e versões imutáveis. Banco em nuvem, login obrigatório, sincronização bidirecional e
acesso geral ao Drive permanecem fora do escopo.

## Consequências

A proteção gerenciada pelo Drive não oculta o conteúdo do Google nem permanece no arquivo
baixado. Não derivar chaves de tokens, e-mail ou identificadores: OAuth não fornece a senha
Google nem seu hash. Hashes detectam corrupção, mas não autenticam o pacote contra quem possa
alterar arquivo e manifesto; `.rpbc` não oferece a autenticação criptográfica do `.rpb`.

Perder acesso à conta ou remover os arquivos compromete a recuperação remota. Cópias de
máquinas diferentes podem divergir; um envio recente pode conter dados antigos. A quantidade
de arquivos é estável por par carteira/instalação, mas o tamanho e as revisões internas do Drive
podem variar. A aplicação mantém uso e recuperação locais independentes da integração.

O mantenedor assume suporte aos cofres dos dois sistemas, manutenção da identidade OAuth e
atendimento às políticas do Google. A configuração de produção e a validação entre instalações
são condições de distribuição. A [arquitetura](../../ARCHITECTURE.md) descreve a implementação;
o [guia do Drive](../google-drive-setup.md) concentra configuração, diagnóstico e validação.
As fontes consultadas estão na [pesquisa](../research/issue-58-google-drive-credentials.md).
