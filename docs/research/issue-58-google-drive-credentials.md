# Issue #58 — Google Drive e armazenamento de credenciais

Pesquisa em fontes primárias em 11/10/2026. Subsídio para especificação; não configura um projeto Google nem contém credenciais reais. A decisão vigente está na [ADR-0001](../adr/0001-optional-google-drive-backup.md): pasta visível, automação e proteção padrão do Drive, sem senha adicional. A pesquisa de `appDataFolder` abaixo registra a alternativa inicial, não o destino escolhido.

## Pré-requisitos operacionais

- O mantenedor precisa habilitar a Drive API, configurar o consentimento e criar um cliente OAuth do tipo **Desktop app**. O fluxo local usa navegador do sistema, retorno em `127.0.0.1` numa porta disponível, PKCE `S256` e validação de `state`; não depende de servidor remoto. [OAuth para aplicativos instalados](https://developers.google.com/identity/protocols/oauth2/native-app).
- Cliente instalado não consegue guardar um segredo de aplicação: `client_id` e eventual `client_secret` distribuídos identificam o aplicativo, mas não protegem dados do usuário. Tokens de acesso e atualização são credenciais privadas. Distribuir configuração pública do cliente Desktop é diferente de distribuir tokens. [Visão geral do OAuth Google](https://developers.google.com/identity/protocols/oauth2).
- Em **External / Testing**, autorizações e refresh tokens expiram após sete dias e só os usuários de teste cadastrados podem autorizar. A exceção cobre apenas escopos básicos de identidade; não cobre `drive.appdata`. Portanto, publicação em **In production** é pré-requisito operacional para conexão duradoura, sem prometer tokens permanentes. [Audiência e publicação](https://support.google.com/cloud/answer/15549945?hl=en).
- O escopo `https://www.googleapis.com/auth/drive.appdata` é não sensível. Isso reduz o acesso pedido; não elimina requisitos de política ou eventuais exigências de verificação de marca. [Pasta do aplicativo](https://developers.google.com/workspace/drive/api/guides/appdata), [tipos de verificação](https://support.google.com/cloud/answer/13463817?hl=en).

## Consequências para a implementação

- `appDataFolder` fica oculto na interface do Drive e é acessível somente pelo aplicativo. Criar arquivos com `parents=["appDataFolder"]`, listar com `spaces="appDataFolder"` e baixar com `alt=media`. O usuário pode apagar os dados da aplicação; a pasta não substitui a exportação local. [Pasta do aplicativo](https://developers.google.com/workspace/drive/api/guides/appdata).
- **Inferência e requisito conservador:** distribuir a mesma identidade OAuth (mesmo projeto e cliente Desktop) em todas as instalações e reautorizar a mesma conta Google na máquina nova. A documentação consultada descreve isolamento por aplicativo, mas não garante que clientes distintos, mesmo no mesmo projeto, compartilhem a pasta. Não criar um projeto por instalação nem prometer recuperação entre projetos. Validar listagem e restauração entre duas instalações limpas com a identidade distribuída antes da entrega. [Isolamento da pasta](https://developers.google.com/workspace/drive/api/guides/appdata).
- Tratar revogação e expiração como necessidade de reconectar; refresh tokens também podem deixar de funcionar por inatividade, limites ou políticas. Nunca registrar tokens nem incluí-los no pacote de backup. [Expiração de refresh tokens](https://developers.google.com/identity/protocols/oauth2#expiration).

## Cofre do sistema operacional

O backend `keyring.backends.Windows.WinVaultKeyring` usa o Windows Credential Manager. No Ubuntu desktop, `keyring.backends.SecretService.Keyring` depende de um serviço Secret Service e da sessão D-Bus correspondente; em ambiente sem desktop, o daemon/cofre precisa ser iniciado e desbloqueado. Instalar o pacote Python sozinho não garante disponibilidade. [Backend Windows](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py), [documentação do keyring](https://keyring.readthedocs.io/en/latest/).

A biblioteca permite seleção automática, configuração e extensões de terceiros, incluindo backend nulo. **Decisão recomendada:** selecionar explicitamente os backends aprovados, verificar leitura/gravação e tratar bloqueio, indisponibilidade ou erro como conexão indisponível. Não aceitar armazenamento em arquivo de texto como fallback. Guardar a senha dos backups no cofre para permitir automação é uma decisão distinta de guardar tokens OAuth; a recuperação em outra máquina precisa solicitá-la novamente. Isso é política do RendaPerene, não garantia automática da biblioteca. [Configuração e API do keyring](https://keyring.readthedocs.io/en/latest/).

## Esclarecimento do fluxo desejado

Após a primeira proposta, o usuário definiu backup automático em pasta **visível** chamada
`RendaPerene`, com descoberta automática dos backups em uma máquina nova e confirmação antes
de recuperar. A proposta inicial de uploads manuais em `appDataFolder` não atende a esse fluxo.

- `drive.appdata` atende apenas ao espaço oculto do aplicativo, não à pasta visível desejada.
  [Pasta do aplicativo](https://developers.google.com/workspace/drive/api/guides/appdata).
- Para a pasta e os pacotes criados pelo RendaPerene, adotar `https://www.googleapis.com/auth/drive.file`.
  Esse escopo não sensível permite criar arquivos e acessar os arquivos criados ou autorizados para
  o aplicativo, evitando acesso geral ao Drive. Uma pasta preexistente arbitrária não fica autorizada
  só por se chamar `RendaPerene`; usar a pasta criada pelo app ou uma seleção autorizada pelo usuário.
  [Escopos do Drive](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
- Validar descoberta e recuperação entre instalações com a mesma identidade OAuth também para
  esse escopo. Identificar pasta e pacotes por IDs e marcadores próprios, não apenas por nomes.
- O RPB atual exige senha para criar cada pacote. Automação sem intervenção exige obter essa senha
  do cofre, mediante consentimento específico, ou mantê-la apenas durante uma sessão desbloqueada.
  O login Google permite baixar pacotes, mas não substitui a senha ou chave que os descriptografa.
- A frequência e a política foram definidas posteriormente: verificar a cada 10 minutos enquanto
  a aplicação estiver aberta e atualizar um único arquivo por carteira selecionada e instalação.
  Uma máquina não sobrescreve o arquivo da outra; não haverá histórico gerenciado por máquina.

## Escolha para a primeira versão: sem senha adicional

- A criptografia padrão do Drive é automática, em trânsito e em repouso, também para contas
  pessoais. Nenhuma configuração especial ou alteração do arquivo é necessária. O provedor
  gerencia as chaves; o arquivo baixado não permanece criptografado por essa proteção.
  [Privacidade do Drive](https://support.google.com/drive/answer/10375054?hl=pt-BR).
- A criptografia adicional do lado do cliente do Workspace exige conta Workspace e habilitação
  administrativa. É um recurso distinto da proteção padrão e não é requisito desta proposta.
  [Criptografia no Drive](https://support.google.com/drive/answer/10519333?hl=pt-BR).
- O usuário escolheu aceitar a proteção padrão para a primeira versão, evitando senha adicional
  e arquivo de chave no Drive. Isso revisa as premissas originais da #39: a implementação precisará
  de pacote de nuvem sem criptografia própria, preservando o backup local RPB criptografado.
- OAuth retorna tokens de autorização, não a senha Google nem seu hash. Tokens expiram e podem
  mudar entre autorizações; não são uma chave estável para recuperação entre máquinas.
  [Fluxo OAuth](https://developers.google.com/identity/protocols/oauth2).
- OpenID Connect, se solicitado, retorna informações de identidade como `sub` e e-mail;
  `sub` é um identificador, não um segredo. **Conclusão de segurança:** aplicar hash a dados de
  identidade não cria uma chave secreta; obter um identificador do login não substitui gestão de
  chaves. Não solicitar escopos de identidade apenas para tentar derivar uma chave.
  [Informações de identidade](https://developers.google.com/identity/openid-connect/openid-connect).

## Cópias por máquina e sugestão de recuperação

O usuário escolheu nomes legíveis `<carteira>_<maquina>`, com seleção de carteiras por instalação.
O par UUID da carteira e UUID da instalação deve identificar o arquivo; nomes não são únicos
no Drive e não constituem identidade. A atualização mantém o mesmo arquivo para esse par.

O campo `modifiedTime` representa a última modificação e pode ser definido pelo cliente.
Para sugerir o envio mais recente, o RendaPerene não deve defini-lo usando o relógio local;
deve usar o horário retornado pelo Drive após a atualização do conteúdo. Renomeações ou mudanças
externas podem afetar esse campo. **Limite:** a ordenação sugere uma cópia para inspeção, mas não
prova que seu conteúdo inclui alterações feitas em outras máquinas. A restauração exige confirmação.
[Metadados de arquivos do Drive](https://developers.google.com/workspace/drive/api/reference/rest/v3/files).

## Verificações necessárias

- Conectar e reconectar nos ambientes Windows e Ubuntu suportados, com o cofre disponível e bloqueado/ausente.
- Recuperar backup em outra instalação com mesma conta/identidade OAuth, sem senha adicional e sem copiar tokens, configuração de pasta ou cofres locais.
- Confirmar cancelamento, revogação e ausência de refresh token sem fallback inseguro.
- Verificar o pacote distribuído: somente configuração pública de aplicativo; nenhum token, senha ou dado pessoal.
- Definir e testar o pacote de nuvem e sua validação sem afetar a criptografia ou restauração do RPB local.
