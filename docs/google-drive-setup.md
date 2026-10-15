# Configuração do backup no Google Drive

O usuário conecta sua própria conta Google na aplicação. O mantenedor configura uma única
identidade OAuth desktop para o RendaPerene; o usuário não precisa criar um projeto Google.
As carteiras continuam locais e a conexão é opcional.

Se **Conectar ao Google** estiver indisponível, a distribuição ainda não contém uma configuração
Google utilizável. Isso deve ser resolvido pelo mantenedor; cada usuário final apenas conecta sua
conta e escolhe suas carteiras. O registro do cliente OAuth é uma etapa obrigatória do aplicativo,
conforme a [documentação Google](https://developers.google.com/identity/protocols/oauth2/native-app).

## Configuração do mantenedor

Antes de configurar os links públicos da tela de consentimento, publique as páginas de
apresentação, privacidade e termos seguindo o [guia do site](github-pages-setup.md).
Ele identifica os campos no Google Auth Platform e as etapas de domínio, DNS, HTTPS e
comprovação de propriedade no Search Console. O site não recebe callbacks ou tokens;
o cliente permanece desktop com retorno loopback. O contato pelo GitHub Issues não
substitui o e-mail de suporte obrigatório na configuração OAuth.

1. No [Google Cloud Console](https://console.cloud.google.com/), escolha o projeto do aplicativo
   e habilite a Google Drive API.
2. Configure a tela de consentimento para usuários externos, com nome, suporte e política de
   privacidade do produto. Solicite somente `https://www.googleapis.com/auth/drive.file`.
3. Crie um cliente OAuth do tipo **Desktop app**. Baixe o JSON e salve-o como
   `google-oauth-client.json` ao lado de `app.py`. O arquivo está ignorado pelo Git. O exemplo
   [google-oauth-client.example.json](../google-oauth-client.example.json) contém apenas placeholders.
   Para desenvolvimento, também é possível definir `RENDAPERENE_GOOGLE_OAUTH_CLIENT_FILE` com o
   caminho absoluto para esse JSON.
4. Use uma identidade de teste separada e inclua as contas de teste no consentimento. Para a
   distribuição, publique a configuração adequada e cumpra as políticas do Google. O modo
   **External / Testing** expira refresh tokens em sete dias para este escopo.
5. Preserve o mesmo projeto e cliente nas versões Windows e Ubuntu. `RendaPerene.spec` inclui
   o JSON opcional da raiz; sem ele, o pacote continua oferecendo uso e backups locais.

Para os builds do GitHub Actions, cadastre o conteúdo completo do JSON em
**Settings → Secrets and variables → Actions → New repository secret**, com o nome
`GOOGLE_OAUTH_CLIENT_JSON`. O workflow `Package native distributions` cria o arquivo em cada
runner antes de empacotar Windows e Ubuntu, sem imprimir seu conteúdo. JSON inválido interrompe
o build; um secret ausente gera um aviso e produz uma distribuição com login Google desabilitado.
O cliente desktop é validado pelo empacotamento e incluído na distribuição; o secret evita
versionar o arquivo, mas não o oculta dentro do aplicativo distribuído.
Execute o workflow manualmente para validar os novos pacotes antes de publicar uma tag de release.

O ID e o segredo do cliente desktop identificam o aplicativo e são distribuíveis; não são tokens
de usuário. Não adicione `token`, `refresh_token`, senha ou chave a esse JSON. Tokens ficam no
Windows Credential Manager ou no Secret Service da sessão Ubuntu, sem fallback em arquivo.
No Ubuntu desktop, o serviço Secret Service e a sessão D-Bus precisam estar disponíveis e o cofre
desbloqueado. Instalar `keyring` sozinho não cria um cofre. WSL ou ambiente sem sessão gráfica
pode não disponibilizar esse mecanismo.

Para executar a partir do código no Windows, instale as dependências no mesmo ambiente Python
que inicia a aplicação. Na raiz do projeto, usando o ambiente `venv`, execute no PowerShell:

```powershell
.\venv\Scripts\python.exe -m pip install -e .
.\venv\Scripts\python.exe -m streamlit run app.py
```

O pacote `keyring` instala sua dependência nativa `pywin32-ctypes` no Windows. Se os componentes
não estiverem disponíveis, o aplicativo informa que a instalação precisa ser atualizada. Falhas
efetivas de leitura, gravação ou remoção no cofre mantêm o bloqueio da conexão. Após instalar as
dependências, encerre e inicie novamente o processo do Streamlit.

O fluxo solicita uma janela de login no navegador em que o RendaPerene está aberto, usa PKCE
e retorna para `127.0.0.1` em uma porta temporária. A janela é aberta no clique e recebe a URL
Google após a verificação do cofre. Se o popup for bloqueado ou fechado, **Abrir login em nova aba**
permite continuar no mesmo navegador enquanto a autorização estiver válida. O navegador decide
se abre uma janela ou aba. **Cancelar conexão com o Google** encerra a espera pela autorização.
Não exige servidor de autenticação do RendaPerene. Uma pasta preexistente chamada `RendaPerene`
não é automaticamente autorizada: o aplicativo encontra sua pasta pelos marcadores próprios e
cria uma pasta quando necessário. Se computadores criarem pastas simultaneamente, os backups
em todas elas continuam disponíveis e novos arquivos convergem para uma pasta, sem exclusão
das cópias anteriores. O escopo permite apenas arquivos criados ou autorizados para
o aplicativo. Mudanças de projeto/cliente exigem um plano de acesso aos backups antigos.

Os logs no terminal mostram as etapas da conexão: abertura ou bloqueio do popup
(`google_oauth.popup.opened` / `blocked`), verificação do cofre, entrega da URL, navegação,
recebimento do retorno e troca do código por tokens. Falhas registram apenas o tipo do erro;
URLs de autorização, códigos e tokens não são registrados.

Para também gravar os logs no Windows, inicie o aplicativo pelo PowerShell assim:

```powershell
$env:LOG_TO_FILE = "true"
.\venv\Scripts\python.exe -m streamlit run app.py
```

Na instalação padrão, o arquivo fica em
`%LOCALAPPDATA%\RendaPerene\logs\rendaperene.log`. Reinicie o Streamlit após atualizar a aplicação.

## Uso

Se a integração não puder iniciar, a seção mostra a causa específica, como falha ao ler as
preferências locais ou configuração OAuth inválida. O uso das carteiras e backups locais
permanece disponível; essa falha não significa necessariamente que a release não oferece Drive.

Na seção **Backup no Google Drive**, conecte a conta, selecione as carteiras, informe um nome
para o computador, marque **Ativar backup automático** e salve.
O botão **Salvar preferências** confirma as edições; as atualizações automáticas da tela preservam
os campos ainda não salvos. Mudanças salvas em outra aba atualizam os valores apresentados.
As cópias encontradas podem ser recuperadas mediante confirmação ou simplesmente ignoradas,
sem bloquear os envios.
Inspeções e resultados de recuperação aparecem apenas na aba que iniciou a operação; outras
abas mantêm suas próprias carteiras ativas.
A primeira verificação ocorre
após 10 minutos; as seguintes respeitam esse intervalo após terminar a verificação anterior,
enquanto a interface estiver aberta. Conexões lentas e reinícios do sistema não acrescentam
um ciclo de espera ao primeiro envio.
Ao reiniciar a aplicação, as carteiras já configuradas continuam com backup automático. Outra
conta ou instalação precisa de sua própria seleção e ativação; restaurar é sempre opcional.
Configurações antigas com `discovery_complete` ausente ou falso não exigem editar o JSON.
Carteiras novas não entram na seleção automaticamente. Cada computador atualiza seu próprio arquivo
`<carteira>_<maquina>.rpbc`. Nomes iguais não misturam arquivos de instalações diferentes.
Recriar ou substituir uma carteira por outra identidade exige salvar novamente a seleção para
autorizar seus envios, mesmo quando o nome foi mantido. Preferências antigas sem essa identificação
também exigem confirmação da seleção antes de retomar o backup automático.

As cópias aparecem pelo horário de atualização no Drive, com a mais recente primeiro. Confira
origem e dados da prévia antes de confirmar. Uma cópia antiga enviada agora aparece como recente;
o aplicativo não mescla alterações. Ao substituir uma carteira local, mantém uma cópia de recuperação.
Quando o identificador da carteira ainda não existe nesta instalação, escolha **Substituir carteira
local** e selecione o destino (por exemplo, **Carteira Principal**), ou escolha **Criar nova carteira**.
Nomes iguais em computadores diferentes não indicam a mesma identidade. A substituição exige
confirmação do destino e preserva a carteira anterior em `backups/pre-restore`; mudanças locais
após a confirmação exigem nova revisão. Quando a identidade já existe, a restauração usa a carteira
correspondente. Uma cópia já restaurada deve ser revisada antes de excluí-la pela interface, caso
se queira instalar esse mesmo backup em outro destino: a aplicação impede identidades duplicadas.
O pacote inclui o SQLite completo, com pagamentos e decisões de confirmar ou ignorar proventos.
O formato `.rpbc` usa somente a proteção padrão do Google Drive, sem criptografia adicional
do RendaPerene; compartilhar o arquivo permite ler os dados. O backup local `.rpb` mantém sua senha.

Desconectar remove tokens locais e mantém os arquivos. Revogue o acesso em
[Conexões da conta Google](https://myaccount.google.com/connections) quando desejar.
Falha na remoção é informada; nesse caso, remova a credencial `RendaPerene:GoogleDrive:…`
no cofre do sistema ou desbloqueie-o e use **Tentar remover credenciais locais**. A pendência
persiste após reiniciar a aplicação e impede retomar a conexão até concluir a remoção.
Desmarcar carteiras não apaga arquivos. Não existe execução com a interface fechada.
Se a consulta inicial ao Drive falhar temporariamente, as verificações seguintes tentam novamente,
respeitando o intervalo de 10 minutos e a seleção salva com o backup automático ativado.
Se a identificação da conta falhar após consentimento, a credencial já salva no cofre permite
nova tentativa automática, sem refazer o login. A orientação para revogar acesso se aplica a
falhas reais na gravação das credenciais.
Alterar ou substituir o arquivo remoto provoca novo envio da cópia local no próximo ciclo.
Configurações antigas sem ID e versão do último envio recebem uma atualização para registrar
esse estado, sem exigir editar o JSON.

## Validação para distribuição

Os testes automatizados usam SQLite temporário e adaptadores falsos, sem contas ou dados pessoais.
Antes de distribuir, valide com dados sintéticos em Windows e Ubuntu nativos:

- consentimento, popup e link alternativo, cancelamento, expiração e revogação;
- cofres disponíveis, bloqueados ou ausentes, falhas ao salvar e ao remover tokens;
- seleção persistida, primeira verificação após 10 minutos, ausência de reenvio sem mudanças,
  atualização do mesmo arquivo após renomear e recuperação após falha de rede;
- pasta ausente, nomes duplicados e arquivo remoto removido;
- oferta de recuperação opcional e envio apenas das carteiras selecionadas em outra instalação,
  usando a mesma conta e cliente OAuth, sem copiar tokens nem configuração da pasta;
- duas instalações atualizando cópias separadas da mesma carteira;
- recuperação preservando pagamentos e decisões sobre proventos, criação de nova carteira e
  substituição da Principal com outra identidade, mantendo uma cópia anterior;
- pacote corrompido, schema incompatível e alteração local após confirmação preservando a carteira;
- configuração OAuth de produção, identidade comum às releases e ausência de tokens, senhas,
  chaves ou dados pessoais nos logs e artefatos de distribuição.

Registre versão, sistemas e resultados da validação junto à release ou PR. Resultados automatizados
não comprovam por si só o consentimento real, o funcionamento dos cofres ou a transferência entre
máquinas. O modo de teste Google deve ser substituído pela configuração de produção antes da
distribuição, respeitando as políticas aplicáveis.

Consulte a [ADR](adr/0001-optional-google-drive-backup.md) para as decisões e a
[pesquisa de fontes oficiais](research/issue-58-google-drive-credentials.md) para as referências.
O envio de arquivos grandes usa o [protocolo resumable do Drive](https://developers.google.com/workspace/drive/api/guides/manage-uploads);
uma falha de envio será tentada novamente na próxima verificação.
