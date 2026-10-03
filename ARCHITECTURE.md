# Arquitetura do RendaPerene

## Visão geral

O RendaPerene é uma aplicação Python e Streamlit para acompanhar carteiras de investimentos brasileiros (B3) e planejar a aposentadoria. Os dados das carteiras são mantidos em arquivos SQLite locais; a aplicação importa planilhas da B3, obtém dados de mercado por integrações públicas existentes e apresenta a interface em português brasileiro.

A aplicação prioriza o armazenamento local. Ela não utiliza banco de dados em nuvem, autenticação de usuários, telemetria ou scraping automatizado do portal da B3.

## Execução e composição

A interface requer Streamlit 1.55.0 ou superior, conforme `pyproject.toml`. Esse mínimo
suporta abas com `on_change="rerun"` e estado `.open`, além de `width="stretch"` e
`height="content"` para dimensionar os componentes e o histórico.

O `app.py` é a raiz de composição. Ele:

1. seleciona e inicializa o banco de dados da carteira ativa;
2. configura o Streamlit;
3. conecta os adaptadores de produção da carteira, do planejamento, do processamento da B3 e dos dados de mercado com cache;
4. inicializa o estado da sessão; e
5. direciona para as três telas principais: Dashboard, Ativos e Planejamento.

O RendaPerene possui apenas execução local. O banco ativo é `portfolio.db` ou outro arquivo `.db`
selecionado na barra lateral, sempre dentro do diretório gravável do usuário. Os pacotes nativos
iniciam o servidor Streamlit somente em `127.0.0.1`.

Execute a aplicação com:

```bash
venv/bin/streamlit run app.py
```

### Logging

O módulo `core/logging_config.py` concentra a configuração de logging atrás da interface
`configure_logging(logs_dir)`. `run_app.py` a executa antes de iniciar o Streamlit e `app.py` a
reaplica no início de cada execução do script. A configuração substitui somente os handlers que ela
própria instalou, evitando duplicação nos reruns sem remover handlers internos do Streamlit.

`APP_ENV=dev` seleciona `DEBUG`; qualquer outro valor seleciona `INFO`. `LOG_TO_FILE=true`, sem
distinção entre maiúsculas e minúsculas, mantém `stdout` e adiciona um `RotatingFileHandler` em
`logs/rendaperene.log`, sob a raiz de dados local, com 5 MiB por arquivo e três backups. Outros
valores não criam o diretório nem o arquivo de log. Falhas de criação preservam a saída padrão e não
impedem a inicialização. Os padrões são `prod` e `false`, inclusive no workflow de distribuição.
Os módulos consumidores obtêm seus loggers com `logging.getLogger(__name__)`; os diagnósticos de
sessão não possuem um gravador paralelo nem registram dados financeiros. Um filtro nos handlers da
aplicação aceita apenas os namespaces `app`, `run_app`, `core`, `services`, `views` e `__main__`.
Assim, internals de dependências como `yfinance` e `peewee` não são copiados para `stdout` nem para o
arquivo, inclusive em `DEBUG`; falhas relevantes dessas integrações são convertidas pelos adapters
em eventos sanitizados da aplicação. Nomes de carteiras, tickers, quantidades, valores financeiros,
identificadores de sessão e conteúdo tabular não são registrados em nenhum nível. Caminhos absolutos
não são registrados em `INFO` ou níveis superiores. A única exceção em `DEBUG`, destinada ao
desenvolvimento com `APP_ENV=dev`, é o caminho do temporário cuja limpeza falhou e seu traceback;
o evento correspondente em `WARNING` não contém caminho. Em sistemas POSIX, o diretório de logs é
restrito a `0700`; o arquivo ativo e os backups rotacionados usam `0600` e têm essa permissão
reaplicada durante a rotação.

## Camadas e dependências

O repositório possui três camadas principais:

- **`core/`** contém a infraestrutura técnica e os contratos compartilhados. Inclui o `DatabaseManager`, os protocolos de `core/ports.py`, DAOs SQLite, constantes, textos localizados, formatação, gerenciamento de sessão, processamento da B3 e a integração de dados de mercado desacoplada da interface.
- **`services/`** contém as regras de aplicação e de domínio. Os serviços dependem de portas, e não do código de apresentação.
- **`views/`** contém a renderização e as interações do Streamlit. `StreamlitCachedMarketData` conecta a apresentação ao cache remoto não bloqueante; o catálogo e as projeções locais usam `st.cache_data`, com recuperação opcional das projeções em arquivo local.

A direção das dependências é `views` → `services` → contratos e adaptadores de `core`. A raiz de composição seleciona os adaptadores concretos. As views não devem conter cálculos de negócio, SQL direto ou regras de processamento das planilhas da B3.

### Serviços de domínio

- `AssetService` é a fonte única da verdade para transações, dividendos, posições dos ativos, evolução histórica, lista de ativos monitorados, registros normalizados do catálogo e definição do dividend yield alvo do modelo de Bazin com base em dados de mercado.
- `SimulationService` controla as configurações de aposentadoria e os cálculos de anuidade antecipada. Os consumidores devem usar `get_current_simulation()` em vez de reimplementar o cálculo dos aportes. `prepare_historical_evolution()` combina o patrimônio inicial configurado com os aportes líquidos do período e prepara as curvas planejadas para os gráficos do Dashboard e do Planejamento, sem alterar os dados de origem nem o histórico de proventos recebidos. A série de aportes planejados acumula somente os aportes mensais, começando com um aporte no mês 0; os proventos planejados começam em zero e usam o patrimônio inicial mais os aportes anteriores como base a partir do mês 1.
- `GoalService`, em `services/goals_service.py`, controla as metas gerais da carteira, incluindo o reinvestimento opcional de dividendos e o progresso dos aportes anuais. Ele consome os valores planejados de `SimulationService` por meio de `PlanningProviderPort`, sem duplicar os cálculos de aposentadoria.
- `ShareQuantityGoalService`, em `services/share_quantity_goal_service.py`, controla a meta anual de quantidade de cotas por ticker. A base é a quantidade mantida em 1º de janeiro do ano corrente; o progresso mede as aquisições desde essa data, inclusive as que ainda têm custo pendente, excluindo entradas de custódia e ações corporativas. O serviço salva metas de cotas independentes da renda planejada, converte crescimento percentual em cotas com arredondamento para cima e mantém a base de 1º de janeiro durante o ano. Alvos ajustados por eventos corporativos também são arredondados para cima para cotas inteiras, preservando os ajustes contínuos da base e das aquisições e evitando criar uma cota extra por imprecisão numérica. Calcula o esforço anual por `máximo(alvo − base de 01/01, 0) × cotação atual` e a participação de cada ativo nesse esforço. Calcula separadamente o valor restante por `máximo(alvo − posição atual, 0) × cotação atual`; compras realizadas não diminuem o esforço anual. O aporte externo anual é o esforço total menos os proventos anuais projetados para a posição-alvo, com mínimo de zero, sem considerar vendas planejadas como recursos. Os proventos projetados são a soma de `alvo × média anual por cota`, pressupondo a posição-alvo durante um ano e seu reinvestimento no cálculo do aporte. O alerta compara esse aporte externo estimado com o aporte mensal corrigido de `get_current_simulation()` multiplicado por 12. Os indicadores usam tooltips para explicar as fórmulas e a origem dos valores; indisponibilidade de dados de mercado não impede salvar. Metas de manutenção (0%) e redução (até −100%, zero cotas) são permitidas. O progresso das reduções acompanha as vendas; manutenção exige quantidade igual ao alvo. Metas de redução permanecem visíveis após a venda total; essa classificação usa a base de 01/01 do ano consultado e os ajustes por eventos corporativos, inclusive quando o alvo foi salvo em um ano anterior. O progresso pode superar 100%.
- `LocalBackupService`, em `services/local_backup_service.py`, cria um conjunto de backup local para as carteiras selecionadas, valida cada cópia, calcula os hashes, gera os metadados e publica o conjunto de forma atômica. Sua interface não depende de provedor de nuvem.
- `LocalRestoreService`, em `services/local_restore_service.py`, autentica e inspeciona pacotes locais, valida manifesto, hashes, SQLite, identidade e compatibilidade, e orquestra a publicação de uma carteira por vez sem expor credenciais à apresentação.
- `MarketAnalysisService` é o módulo profundo de análise de mercado. Sua interface pública retorna a análise final do ticker; internamente, ele combina o snapshot remoto independente da carteira com as correções anuais da carteira ativa e somente então aplica as regras de `ValuationService`.
- `ValuationService` contém as regras puras do dividend yield alvo e do preço-teto de Bazin; não possui dependências do Streamlit, do banco de dados ou dos dados de mercado.

### Portas e adaptadores

O formulário manual `ManualEntryWidget`, em `views/components/manual_entry.py`, é compartilhado
por Operações e pelo detalhamento da carteira. O detalhamento fornece um ticker fixo; o formulário
não permite substituí-lo e encaminha os lançamentos às mesmas interfaces de `AssetService`.
`AssetAnnualGoalWidget`, em `views/components/asset_annual_goal.py`, consulta o plano anual filtrado
para o ticker exibido. `ShareQuantityGoalService.save_asset_goal()` converte o percentual pela base
de 01/01 e reutiliza a validação e a persistência do plano, salvando somente esse ticker na tabela
existente. Metas individuais salvas permanecem editáveis na aba Metas mesmo com o acompanhamento
geral desativado. Os lançamentos usam a revisão persistida da carteira para invalidar projeções;
lançamentos e alterações contextuais de metas descartam snapshots do editor antes do rerun.
Os campos de cotas e percentual no detalhamento ficam lado a lado e salvam automaticamente por
callback ao confirmar a edição, sem botão de salvar. Após cada tentativa, os dois campos são
recriados a partir da meta persistida; falhas mantêm a meta anterior e exibem o erro. Sem posição
em 01/01, o percentual fica desabilitado com uma explicação. Abrir o detalhamento não salva metas.
O estado dos controles é separado por carteira e ticker e descartado na troca de carteira.

O arquivo `core/ports.py` define as fronteiras para persistência da carteira, origens de backup, correções de proventos, snapshots remotos, análise final de mercado, acesso ao catálogo de ativos, configuração do planejamento, registro do esquema do banco, processamento das planilhas da B3 e comunicação entre serviços. Os adaptadores de produção são os DAOs SQLite, `SQLitePortfolioBackupSourceFactory`, `MarketData`, `StreamlitCachedMarketData` e `B3ExcelParserAdapter`. Nos testes, essas fronteiras são substituídas por bancos isolados, mocks ou adaptadores injetados.

## Persistência

`ApplicationPaths`, em `core/application_paths.py`, é o módulo profundo que separa os recursos
descartáveis do pacote dos dados graváveis. Sua interface resolve os recursos incluídos no pacote,
a raiz de dados, o diretório das carteiras, o catálogo somente leitura, os logs e os backups. Também
prepara os diretórios obrigatórios do layout gravável, inventaria apenas bancos SQLite válidos e
concentra a migração das carteiras antigas. A raiz de composição `app.py` conecta esses caminhos ao
`DatabaseManager`, ao catálogo e aos adaptadores; as views não calculam caminhos do sistema
operacional.

As raízes graváveis padrão são `%LOCALAPPDATA%\RendaPerene` no Windows e
`$XDG_DATA_HOME/RendaPerene` no Linux, com fallback para `~/.local/share/RendaPerene`. O executável
e seus recursos podem ser substituídos sem mover as carteiras. O caminho resolvido do catálogo
integra a chave do cache de leitura, evitando reutilizar uma entrada caso a configuração do caminho
mude durante a execução.

O backup manual é publicado em
`backups/local-backups/<data>_<hora>_<microssegundos>_UTC_rendaperene_<backup_id>.rpb`, sem incorporar
nomes de carteiras no caminho. O identificador mantém a unicidade; a restauração também aceita os
nomes UUID anteriores. A interface apresenta todas as carteiras válidas marcadas por padrão e permite
selecionar um subconjunto. A raiz de composição injeta `SQLitePortfolioBackupSourceFactory` em
`LocalBackupService`. A seleção fixa o nome exibido, o arquivo e sua geração; o adaptador prepara o
schema existente e fornece uma conexão dedicada pelo `DatabaseManager`.
Carteiras ainda não abertas nesta versão recebem as migrações já existentes antes da cópia,
garantindo que possuam um identificador estável.

O módulo usa a API de backup do SQLite para incluir páginas confirmadas do WAL sem produzir cópias
parciais. Depois de fechar cada arquivo, abre a cópia como SQLite imutável, sem criar sidecars
WAL/SHM, exige `PRAGMA integrity_check = ok`, calcula o SHA-256 e gera metadados internos com o nome
exibido, identificadores da carteira, instalação e backup, criação em UTC, versões da aplicação e
schema. Todas as conexões selecionadas e seus reader locks permanecem abertos até a publicação do
pacote, impedindo exclusão ou substituição de uma carteira depois de sua cópia.
Cada cópia possui prazo total de 60 segundos e divide a operação em lotes; tentativas bloqueadas usam
um `busy_timeout` curto para que o callback de progresso possa cancelar a operação dentro desse
limite. Em sistemas POSIX, os diretórios de staging e publicados usam modo `0700`, e os SQLite e
JSON nascem com modo `0600`; diretórios de backup existentes também são restringidos antes da nova
operação. O cancelamento é tratado como carteira em uso e remove todo o diretório temporário.
Carteiras diferentes podem representar instantes ligeiramente distintos, mas cada SQLite é
internamente consistente. O staging é cifrado como RPB v1 e publicado somente quando todas as
carteiras e o manifesto estão completos; falhas removem o staging e não publicam backups. As
migrações normais eventualmente aplicadas às carteiras selecionadas permanecem como
ocorreriam ao abri-las no aplicativo. Seleções removidas, substituídas, inválidas, bloqueadas ou com
identificadores duplicados impedem a publicação do conjunto completo.

Cada carteira mantém seu UUID estável na tabela `portfolio_metadata`, portanto a identidade
acompanha uma futura restauração e não depende do nome do arquivo. A instalação mantém outro UUID
em `.installation-id`, na raiz de dados graváveis, criado atomicamente na primeira solicitação de
backup. Os novos backups são publicados como pacotes RPB v1 criptografados, sem retenção automática
e sem envio a provedores externos. O RPB usa AES-256-GCM,
autentica o cabeçalho e o conteúdo e deriva a chave da senha com Argon2id. A chave de recuperação
`.key` fica fora do pacote e nunca é persistida pela aplicação. O download usa o mesmo nome-base do
`.rpb`, mas a associação segura depende do `backup_id` autenticado, não do nome dos arquivos.

`LocalRestoreService` recebe o conteúdo criptografado e uma senha ou chave apenas em memória. Cada
execução lista os `.rpb` regulares em `backups/local-backups/` por modificação local decrescente;
o conteúdo selecionado é lido pelo serviço somente ao validar ou restaurar, sem aceitar caminhos
externos ou links simbólicos. Na restauração, o hash é conferido novamente antes da publicação.
Pacotes enviados pelo navegador continuam disponíveis para restauração entre instalações. Cada
inspeção materializa o `.rpb` em um diretório privado temporário, autentica o envelope, confere seu
`backup_id` contra o manifesto e valida contagem, caminhos, metadados, SHA-256,
`PRAGMA integrity_check`, identidade e schema de cada carteira. O temporário descriptografado é
removido ao fim da operação; se a limpeza falhar, a interface avisa onde verificar e remover
manualmente os arquivos remanescentes, inclusive na prévia ou após um erro. Uma publicação já
concluída continua sendo informada como sucesso. A prévia
retorna somente metadados autenticados e um destino fixado pela identidade:
uma carteira já conhecida mantém seu arquivo local; uma identidade nova requer um nome local escolhido
pelo usuário e validado por `ApplicationPaths`. A validação recusa nomes vazios, inválidos ou ocupados,
inclusive por arquivos inválidos, auxiliares e marcadores de exclusão. Também verifica em bytes o
nome do banco e os nomes auxiliares gerados contra o limite do sistema de arquivos. A disponibilidade
é conferida
novamente antes da publicação sob os locks existentes, sem substituir outra carteira. Chamadores
sem nome explícito ainda podem usar o destino legado `portfolio_restored_<id>.db`. Pacotes com várias
carteiras são restaurados individualmente.

Na prévia, a interface converte a data UTC autenticada para a hora local quando representável;
datas nos limites de `datetime` permanecem em UTC se a conversão local exceder esse intervalo.
A interface apresenta o nome da carteira de destino usado na navegação, sem exibir identificadores
de instalação, schema ou nomes de arquivos de carteiras ao usuário. A carteira selecionada já aparece
no seletor e não é repetida no resumo do destino; para uma identidade nova, o nome escolhido integra
a confirmação.

Schemas superiores a `CURRENT_SCHEMA_VERSION` são recusados; versões anteriores suportadas são
migradas em uma cópia temporária e verificadas novamente antes da publicação. A confirmação inclui
o hash do pacote, a identidade, a geração e uma assinatura do conteúdo lógico do SQLite; metadados
voláteis do WAL/SHM não invalidam a confirmação, mas alterações reais de conteúdo a cancelam. Para
um destino novo, a ocupação do nome e seus arquivos auxiliares também é reconferida sob lock. A
interface compara ainda a data UTC autenticada do backup com a modificação mais recente do banco ou
WAL e mostra um alerta informativo
quando o backup parece mais antigo. Datas nunca autorizam nem bloqueiam a restauração, porque os
relógios de dispositivos podem divergir.

A publicação final fica em `ApplicationPaths`: o lock de gerenciamento serializa mudanças de
inventário e o lock exclusivo da carteira aguarda todas as conexões leitoras. Em uma substituição,
o banco, WAL, SHM e geração anteriores são movidos para uma pasta UUID em
`backups/pre-restore/`; o SQLite preparado é publicado com `os.replace`, recebe uma nova geração e
invalida os caches locais de validação. Falhas restauram os arquivos anteriores. Se o próprio
rollback falhar, a cópia recuperável permanece, um tombstone impede a recriação silenciosa do banco
e a interface informa o caminho para recuperação manual. A sessão executora ativa a carteira
restaurada e limpa seu estado derivado; outras sessões detectam a nova geração antes do próximo
acesso.

O catálogo é o `assets.csv` incluído no pacote e nunca faz parte do armazenamento gravável. A
aplicação lê esse recurso diretamente, sem copiar, migrar ou mesclar catálogos de versões
anteriores. Dessa forma, uma nova versão substitui integralmente a referência distribuída. Tickers
presentes na carteira, mas ausentes do catálogo, permanecem no SQLite e recebem metadados neutros
somente para apresentação; esses metadados não constituem uma entrada de catálogo.

Quando existem bancos `.db` na antiga pasta `database/` ao lado da aplicação ou em pastas irmãs de
releases anteriores chamadas `RendaPerene-v*`, a barra lateral oferece sua importação. Se
mais de uma versão contém o mesmo nome de carteira, a versão válida mais recente prevalece; uma
cópia inválida mais nova não oculta uma cópia válida anterior. A migração valida a origem, copia
(sem mover) um backup para `backups/legacy-import/`, valida novamente a cópia temporária e somente
então publica o banco em
`database/`. A operação é idempotente e recusa qualquer sobrescrita quando há conteúdo diferente.
Bancos conflitantes podem ser publicados com outro nome seguro dentro de `database/`; a interface
sugere um nome livre, permite editá-lo e preserva tanto o banco existente quanto a origem antiga.
O marcador de conclusão registra o nome efetivamente publicado, continua aceitando o formato
legado sem destino explícito e faz a origem voltar a ser oferecida se essa publicação desaparecer
ou for recriada apenas com valores padrão. A detecção de uma carteira sem dados aceita tanto o
esquema atual quanto o esquema legado anterior às tabelas de preferências, metas e registros B3,
evitando tratar uma simples atualização de esquema como perda de conteúdo.
Bancos importados não são oferecidos novamente quando uma migração de esquema altera os bytes do
destino: a cópia imutável em `backups/legacy-import/` identifica a origem já processada.
Origens antigas que o usuário decide não importar recebem um marcador local separado, gravado
atomicamente em `backups/legacy-import/` com o digest lógico do SQLite. O marcador não altera nem
remove a origem, deixa de valer se seu conteúdo mudar e pode ser removido pela interface para voltar
a oferecer a carteira. Uma importação posterior elimina a preferência obsoleta. Importações e
alterações de preferência são serializadas por origem antiga antes de qualquer lock da carteira de
destino; assim, sessões concorrentes convergem para uma única publicação e um único marcador de
conclusão.
Bancos principais inicializados automaticamente apenas com os valores padrão podem ser substituídos
durante a importação; qualquer dado ou configuração do usuário torna o destino não substituível. A
cópia recuperável relevante permanece em `backups/legacy-import/`. Ao publicar uma carteira
importada, a raiz de composição invalida o estado da sessão derivado do banco e reinicia a execução
para carregar as configurações persistidas antes que a interface permita novas edições. Conexões
abertas pelo `DatabaseManager` registram leitores concorrentes; a publicação final aguarda esses
leitores sob o lock por carteira, impedindo que uma conexão SQLite aberta continue apontando para o
arquivo antigo durante uma substituição. Os locks usam bloqueios advisory do sistema operacional
mantidos por descritores abertos; por isso, um processo encerrado libera automaticamente sua posse
sem que outro processo precise apagar um arquivo de lock que pode já ter sido reutilizado. As
escritas continuam usando o bloqueio nativo do SQLite. A abertura e a inicialização do arquivo de
lock também podem sofrer contenção no Windows: nesses casos, o descritor incompleto é fechado e a
tentativa é repetida dentro do limite de espera existente, sem remover nem assumir o lock de outra
sessão. Erros de entrada/saída que não indicam contenção continuam sendo propagados.
Bancos inválidos não ficam disponíveis para seleção. Se a carteira ativa desaparecer ou se tornar
inválida, a seleção automática de uma alternativa também invalida o estado derivado da carteira
anterior antes de reiniciar a interface. Quando não existe alternativa válida, a aplicação usa um
novo nome `portfolio_recovery*.db`, preservando o arquivo inválido. O reset da carteira também
remove chaves de widgets de metas vinculadas ao banco anterior. Nomes de arquivos de carteiras e
dados financeiros não são escritos em logs.

A exclusão iniciada pela barra lateral também permanece encapsulada em `ApplicationPaths`. A
operação exige o nome completo do arquivo, aceita somente um banco SQLite válido dentro de
`database/`, permite selecionar uma carteira diferente da ativa e impede a remoção da última
carteira válida. Um lock de gerenciamento serializa
exclusões concorrentes e o lock exclusivo existente da carteira aguarda conexões leitoras antes da
movimentação. O banco, WAL, SHM e marcador de geração existentes são
movidos para uma pasta exclusiva em `backups/deleted-portfolios/`, com rollback em caso de falha.
Um tombstone oculto permanece em `database/` para que sessões obsoletas recusem a conexão em vez
de recriar silenciosamente um SQLite vazio. A criação explícita de uma carteira publica uma nova
geração sob o lock da carteira antes de remover esse marcador. Toda conexão compara essa geração
com a identidade guardada na sessão Streamlit; se o mesmo nome agora apontar para outra carteira,
o estado derivado é invalidado e a execução reinicia antes de qualquer acesso ao SQLite.
A confirmação de exclusão também é vinculada à geração da carteira selecionada e conferida
novamente sob o lock; se outra sessão substituir o mesmo nome, o texto anterior deixa de autorizar
a operação e o usuário precisa revisar e confirmar a nova carteira.
Esses backups são permanentes até a remoção manual. Quando a carteira ativa é excluída, a raiz de
composição escolhe outra carteira válida, invalida o estado derivado da sessão e reinicia a execução
antes de inicializar os adaptadores do novo banco.

A validação SQLite usa `PRAGMA quick_check` e mantém em memória o resultado pela identidade física,
caminho, tamanho e datas de modificação e alteração do banco e dos arquivos auxiliares WAL/SHM.
Reruns do Streamlit reutilizam a validação enquanto essa assinatura não muda; a comparação de
conteúdo lógico usada pelos marcadores de migração também é reutilizada para arquivos imutáveis.
Substituir o banco ou um auxiliar, mesmo preservando tamanho e data de modificação, produz uma nova
verificação.

O `DatabaseManager` descobre os provedores de esquema em `core/daos/` e solicita que cada DAO
registrado crie ou migre suas tabelas. Ao terminar, ele atualiza `PRAGMA user_version` para a versão
de schema conhecida pela aplicação sem rebaixar um valor futuro maior. Todas as tabelas ficam no
banco SQLite da carteira ativa. O
catálogo estático não é persistência do usuário: ele permanece no pacote, é acessado por uma porta
somente leitura e pode ser substituído por uma nova versão sem migração.

| Armazenamento | Finalidade |
| --- | --- |
| `transactions` | Registro das movimentações da carteira: `id`, `date`, `ticker`, `transaction_type`, `quantity`, `unit_price`, `fees`, `transaction_origin` e `cost_status` (`KNOWN`, `PENDING`, `CORRECTED`). `date` mantém a data manual nas operações conciliadas e recebe a data da planilha nas novas importações. `transaction_origin` identifica a origem do cadastro: operações manuais permanecem `MANUAL` após a conciliação; novas importações são `B3`. Os tipos persistidos são `BUY`, `SELL` e `GROUP`; entradas de custódia usam o efeito de quantidade de `BUY`, mas sua origem as exclui de aportes e metas de compras. |
| `b3_import_records` | Identidade SHA-256 dos campos normalizados da movimentação, registro original normalizado em JSON, natureza do evento, vínculo opcional à transação e decisão de importação. Transferências ignoradas e conciliações de grupos permanecem registradas sem uma transação agregada. |
| `b3_manual_reconciliations` | Liga uma linha B3 a uma ou mais operações manuais preservadas individualmente. Cada operação manual só pode integrar uma conciliação. |
| `dividends` | Proventos recebidos: `id`, `date`, `ticker`, `dividend_type`, `total_value` e os campos opcionais `quantity` e `unit_price` (`REAL`); os tipos são `DIVIDEND`, `JCP` e `YIELD`. |
| `tracked_market_assets` | Tickers acompanhados manualmente. Os ativos em carteira são combinados com essa lista no monitor de mercado. |
| `dividend_corrections` | Ajustes de dividendos por ticker e por ano, identificados por `(ticker, year)`. |
| `planning_configuration` | Configuração única (`id = 1`): data de nascimento, idade de aposentadoria, dados de renda, taxa de juros anual, salário mínimo, patrimônio inicial, modalidade de renda, parâmetros do modelo de Bazin e data opcional de início do planejamento. |
| `asset_accumulation_goals` | Uma meta de quantidade por ticker: base anual persistida, quantidade-alvo não negativa e modalidade, percentual-alvo opcional, peso derivado legado para o Dashboard, estado ativo, média de proventos de cinco anos e data de criação. A aplicação atualiza a base efetiva para 1º de janeiro no carregamento, sem depender de salvar novamente a cada virada de ano. |
| `goal_settings` | Preferências únicas da carteira para reinvestimento de dividendos e metas de quantidade de ações. O reinvestimento é ativado por padrão; as metas por ação permanecem desativadas até serem habilitadas. |
| `portfolio_metadata` | Identificador UUID estável da carteira, independente do nome do arquivo e preservado dentro de cada backup. Não contém nome da carteira nem dados financeiros. |
| `assets.csv` (recurso do pacote) | Catálogo versionado e somente leitura com metadados descritivos de tickers conhecidos. Tickers da carteira ausentes desse recurso permanecem válidos e não o alteram. |

O SQLite não declara chaves estrangeiras entre esses armazenamentos. Os serviços preservam programaticamente a consistência necessária.

A versão 2 do esquema permite metas de cotas iguais ou inferiores à base anual, inclusive zero. A migração automática substitui a restrição antiga e preserva os registros existentes. A versão 3 converte uma única vez as metas legadas por proventos ou percentual em quantidade fixa, usando o alvo já salvo e removendo o percentual persistido. Preserva a base, os pesos, a média de proventos, o estado ativo e a data de criação, usada como referência para os ajustes por eventos corporativos. Planejamento e Dashboard passam a usar o mesmo alvo independente da renda planejada; o crescimento exibido continua derivado da base de 01/01.

## Regras financeiras e de importação

A versão 4 adiciona `dividends.quantity` e `dividends.unit_price` como campos opcionais, sem
preencher estimativas no banco nem alterar os totais existentes. A migração é idempotente.
O mecanismo de backup e restauração usa essa versão para migrar backups antigos e rejeitar
esquemas futuros. Alterações de metadados dos proventos avançam a revisão das projeções locais.

As operações mantêm apenas `transactions.date`. Uma conciliação confirmada preserva a data,
o preço e as taxas dos lançamentos manuais; a data original da B3 fica no JSON de origem em
`b3_import_records.source_record`. Novas operações usam a data da planilha. O parser prioriza
`Data do Negócio`, quando disponível, e aceita `Data` ou `Data de Liquidação`. A classificação
da coluna serve somente à comparação durante a importação, sem criar outras datas no banco.
Ao importar uma planilha, `AssetService` sugere grupos de operações manuais compatíveis pelo ticker,
tipo, soma das quantidades, preço médio ponderado arredondado a três casas e valor da operação. As
operações de cada grupo devem ser da mesma data e estar no intervalo de dois a seis dias corridos
antes da liquidação, ou na mesma data quando só há data de negócio. Como a planilha não informa
taxas nem a corretora das operações manuais, elas não entram na comparação; a instituição da B3 é
exibida para orientar a decisão humana. `OperationsView` inicia cada sugestão sem seleção e exige
uma escolha explícita entre o lançamento existente e importar como nova operação. As escolhas
usam widgets fora de formulário para atualizar o botão a cada seleção; a confirmação fica
desabilitada até todas as sugestões terem uma escolha válida, sem reutilizar uma operação manual
em duas linhas B3. Ao escolher importar como nova, a operação B3 é importada separadamente.
O DAO revalida o grupo e grava os vínculos e
o registro de origem na mesma transação SQLite, sem criar ou apagar operações financeiras. As
reimportações mantêm a identidade B3 e não duplicam o efeito na carteira. O histórico de
movimentações continua mostrando apenas a data da operação.
A versão 6 cria `b3_manual_reconciliations` para associar uma linha agregada da B3 a várias
operações manuais sem fundir seus registros.
O vínculo registra a confirmação com a B3 sem mudar `transaction_origin='MANUAL'`.
Na inicialização, operações marcadas anteriormente como `B3` que possuem esse vínculo comprovado
com uma negociação conciliada voltam a `MANUAL`. Essa correção é idempotente e preserva os valores,
datas e registros de importação; operações importadas sem vínculo manual mantêm sua origem `B3`.

O importador da B3 recebe a planilha selecionada pelo usuário, normaliza suas colunas e datas e produz registros internos de transações e dividendos em inglês.

- Compras atualizam o preço médio ponderado, incluindo as taxas.
- Vendas reduzem a quantidade mantida sem alterar o preço médio da posição restante.
- `AssetService` centraliza a regra dos aportes líquidos do histórico mensal e do acumulado YTD:
  compras mais taxas de compra menos vendas mais taxas de venda. O cálculo usa as transações
  fornecidas por `PortfolioPort`, exclui custódia e preserva a indisponibilidade quando há custos
  pendentes de negociação no período selecionado. `GoalService` usa esse acumulado sem limitar
  retiradas líquidas a zero; valores negativos aumentam o restante da meta anual.
- Desdobramentos e bonificações da B3 são armazenados como transações `BUY` com custo zero.
- Grupamentos são armazenados como transações `GROUP`, que substituem a quantidade atual pela quantidade informada.
- Resgates são armazenados como transações `SELL`.
- O parser distingue custódia, negociação e evento corporativo. Pares de `Transferência` com o mesmo ticker, data e quantidade, nas direções débito e crédito, representam troca de corretora e são marcados para serem ignorados. `Depósito` é uma aquisição recebida e é registrado como compra conhecida a custo zero. `Transferência - Liquidação` segue a direção de crédito ou débito como negociação; uma liquidação de crédito sem valor financeiro gera aquisição com custo pendente.
- Para entradas de custódia sem par, `AssetService` avalia cronologicamente a quantidade com custo conhecido de dias anteriores; vendas reduzem essa cobertura proporcionalmente e grupamentos a ajustam. Custódia de saída é ignorada. Entradas com cobertura suficiente são ignoradas; as demais geram posição com custo pendente. A análise ocorre sob o mesmo bloqueio de escrita SQLite que registra a decisão.
- `PortfolioDAO` grava origem e efeito na posição atomicamente (`BEGIN IMMEDIATE`). A identidade de origem é independente do custo corrigido. A regularização valida valores finitos, positivos e taxas não negativas, atualiza apenas operações pendentes e preserva a origem; os cálculos são refeitos no próximo carregamento.
- Operações manuais não são conciliadas automaticamente por igualdade exata. A importação sugere grupos de compras/vendas do mesmo ticker, tipo e data, cuja quantidade total e média ponderada arredondada a três casas correspondem à linha B3. O usuário escolhe se cada linha B3 corresponde ao grupo ou deve ser importada separadamente. Cada operação manual só pode integrar uma conciliação; a confirmação preserva datas, taxas e preços individuais e guarda a data B3 no registro de origem, sem adicionar evento financeiro duplicado. Dados financeiros pessoais continuam apenas no SQLite local e na sessão atual.
- A migração adiciona o status sem alterar custos antigos. Uma reimportação associa automaticamente apenas registros que já possuem origem B3 ou correções específicas reconhecidas pela assinatura completa do parser anterior; operações legadas sem proveniência permanecem separadas para não reclassificar silenciosamente uma compra manual. Quando a planilha não informa o custo de uma correção reconhecida, a operação existente é preservada e marcada como pendente. A regra atual de importação não atribui preços por ticker ou data. Decisões persistidas não são reclassificadas por importações posteriores de históricos mais antigos.
- Posições com custo pendente mantêm quantidade, valor de mercado e o capital investido de custo conhecido até então; preço médio e indicadores de rentabilidade dependentes do custo ficam indisponíveis. As telas exibem o capital conhecido junto de um aviso explícito de custos pendentes. A regularização fica em Ativos → Operações e invalida o cache da interface.
- Os cálculos dos aportes para aposentadoria usam pagamentos de anuidade antecipada (`type = 1`) por meio de `SimulationService.pmt_annuity_due()`. Posições com custo pendente são desconsideradas na soma do capital investido até a regularização, sem bloquear o planejamento das demais posições.
- As projeções locais descartáveis do Dashboard e de Ativos usam uma revisão monotônica armazenada no SQLite. Gatilhos avançam a revisão após mudanças de transações, proventos, ativos acompanhados e correções anuais; a chave também inclui a geração publicada do arquivo, impedindo reutilização entre carteiras ou após restauração. Os caches remotos Yahoo e BCB não são limpos por essas mutações.
- `core/screen_cache.py` guarda apenas dados reconstruíveis em `cache/screens.db`, fora de `database/` e `backups/`. O arquivo tem esquema próprio versionado, payload JSON tipado com checksum e limites de 8 MiB por entrada e 128 MiB de payload total; nunca recebe operações ou credenciais como fonte autoritativa. Erro de leitura, gravação ou versão desconhecida desativa apenas aquele acesso ao cache. As projeções locais persistidas incluem identidade e geração da carteira, revisão monotônica, parâmetros e data de cálculo; posições incluem a identidade do catálogo. Resultados que combinam mercado e carteira continuam calculados pelos serviços a partir das duas fontes, sem persistir uma composição potencialmente desatualizada.

## Integrações externas

- O `yfinance` fornece cotações da B3, histórico de preços e dados de dividendos e valuation. Os tickers são consultados com o sufixo `.SA`. Quando a cotação atual está ausente, é zero ou não é finita, a integração utiliza o último fechamento diário positivo e finito antes de aplicar as regras de valuation.
- A integração calcula médias de proventos usando os anos disponíveis desde a listagem; anos listados sem pagamento contam como zero. Sem histórico utilizável, o planejamento mostra uma observação e não inventa uma meta de cotas.
- Os endpoints SGS do Banco Central do Brasil (BCB) fornecem valores de IPCA, Selic e salário mínimo. A integração desacoplada da interface utiliza valores alternativos quando uma requisição falha.
- O adaptador do Streamlit mantém cotações e snapshots remotos dos ativos em cache por 10 minutos, históricos de preço por uma hora e indicadores do BCB por 30 dias. O snapshot é identificado somente pelo ticker normalizado e pelo ano de referência; não contém carteira, sessão, correções locais nem parâmetros do modelo de Bazin. Ele inclui até dez anos completos do histórico anual de dividendos e dos fechamentos não ajustados necessários para a consulta Raio-X.
- `BackgroundMarketData`, em `core/background_market_data.py`, implementa as leituras remotas sobre
  `MarketDataCache`. A leitura retorna imediatamente uma cópia do último dado válido; cache vazio
  retorna indisponibilidade para ativos e referências provisórias para indicadores econômicos.
  `app.py` inicializa o recurso compartilhado por processo, mantido por `st.cache_resource`.
  `st.cache_data(refresh_mode="background")` não está disponível no Streamlit 1.58 instalado e,
  isoladamente, não garante leitura imediata de cache vazio.
- O cache remoto possui locks, limite de 512 entradas, fila de 128 atualizações e dois workers
  daemon. Chaves iguais compartilham a atualização; cotações são identificadas por ticker para
  reutilização entre listas diferentes. A medição de oito operações de I/O controladas de 50 ms
  levou aproximadamente 401 ms em série e 202 ms com dois workers; isso valida o agendamento,
  sem representar um benchmark de latência do Yahoo. Snapshots são agendados juntos antes de
  preparar o detalhamento. Workers consultam a fonte remota e gravam somente respostas válidas
  no arquivo de cache; não acessam o SQLite da carteira, `st.session_state` ou comandos de apresentação.
- Expiração e atualização manual preservam o dado anterior. Respostas inválidas ou falhas não
  substituem valores válidos; o fragmento agenda automaticamente uma nova tentativa após o
  backoff de 30 segundos para entradas ainda acompanhadas pela sessão. Uma revisão por entrada
  descarta respostas anteriores à atualização manual. A capacidade limitada pode remover
  entradas antigas; elas voltarão a ser carregadas em background quando solicitadas. O cache é
  descartável. Na abertura, entradas remotas válidas no arquivo local são recuperadas; entradas
  vencidas continuam legíveis com sua idade e são atualizadas em segundo plano. A atualização
  manual marca também a cópia persistida como vencida.
- `views/market_data_status.py` acompanha somente as entradas solicitadas pela sessão. Um fragmento
  verifica suas revisões a cada dois segundos e solicita rerun na thread Streamlit após uma resposta.
  A interface informa idade, atualização, referências provisórias e falhas. Sem todas as cotações,
  patrimônio total, rentabilidade e pesos mostram `N/D`; os gráficos de composição aguardam dados
  completos. Capital e proventos locais continuam disponíveis. A atualização manual do salário
  mínimo mantém o parâmetro atual e salva somente uma resposta válida do BCB na carteira solicitante.
- Em Ativos → Carteira, cada ticker possui uma aba nativa com estado: somente a aba ativa
  executa seu detalhamento, inclusive ao trocar de carteira ou alterar a lista de ativos.
  Em Carteira e no Raio-X, gráficos, históricos e indicadores são preparados
  automaticamente para o ticker selecionado. Os formulários de edição em Carteira ficam em
  expansores independentes, `Registrar movimentação` e `Meta anual deste ativo`, inicialmente
  recolhidos; cada formulário só é preparado quando seu expansor é aberto.
- Os indicadores remotos são consultados com validação estrita no background; consumidores
  headless mantêm os fallbacks anteriores. Cotações/snapshots/intraday usam TTL de 600 segundos,
  históricos de 3600 segundos e indicadores de 2592000 segundos. O modo de diagnóstico existente
  registra durações separadas `atualizacao.mercado.remote_*`, sem chaves nem dados financeiros,
  com `APP_ENV=dev` e `RENDA_PERENE_NAVIGATION_METRICS=true`.
- A cada análise, `MarketAnalysisService` relê do SQLite as correções anuais da carteira ativa fora do cache remoto, mescla-as aos históricos de cinco e dez anos e depois aplica `ValuationService`. Por isso, trocar de carteira ou salvar uma correção altera a chamada seguinte sem nova consulta ao Yahoo Finance e sem limpeza global do cache. Os eventos individuais de proventos continuam representando somente o histórico fornecido pelo Yahoo.
- O dividend yield histórico de cada ano utiliza o último preço de fechamento não ajustado daquele ano, e não a cotação atual.
- `UpdateChecker` consulta o endpoint público de latest release do GitHub uma vez por sessão, em uma thread de fundo. Ele compara somente versões semânticas, seleciona o asset pelo nome padronizado para Windows ou Ubuntu x64 e não acessa nem transmite dados locais. Falhas de rede, resposta e asset apenas geram logs seguros e não interrompem a interface.

Essas integrações permitem o uso local, mas precisam de acesso à rede quando dados atualizados são solicitados. A aplicação não realiza scraping do portal da B3; o próprio usuário importa a planilha oficial da B3.

## Empacotamento

`RendaPerene.spec` é a definição comum do PyInstaller para os builds `onedir`. O entry point é
`run_app.py`, e o bundle contém `app.py`, `core/`, `views/`, `services/`, o catálogo base,
`version.txt` e os recursos/metadados dinâmicos de Streamlit e Plotly. Bancos SQLite, catálogos do
usuário, planilhas, logs e outros arquivos pessoais ou gerados não são adicionados ao bundle.

Os scripts `build_windows.ps1` e `build_linux.sh` são apenas comandos nativos de empacotamento e
criam ambientes virtuais dedicados antes de instalar as dependências. Eles produzem os arquivos ZIP
e TAR.GZ versionados. Cada build valida os recursos do diretório final e
inicia o executável em um diretório de dados temporário para verificar que o servidor Streamlit
chega a responder. O workflow executa os builds em runners Windows e Ubuntu 22.04 separados; tags
de release são rejeitadas quando não correspondem a `version.txt`.

O workflow de distribuição também pode ser executado manualmente para validar os builds sem publicar
um release. Em tags semânticas válidas, ele reutiliza o quality gate, aguarda os dois pacotes nativos,
gera um checksum SHA-256 para cada arquivo e publica um GitHub Release com o `GITHUB_TOKEN` de escopo
mínimo. O job de publicação é o único que recebe permissão `contents: write`; bancos, planilhas,
logs e overlays de catálogo não entram nos artefatos.

## Apresentação

O código, seus identificadores, o SQL e os comentários técnicos estão em inglês. A documentação, os textos da interface, os rótulos dos gráficos, as mensagens de ajuda e as tabelas renderizadas estão em português brasileiro. Valores em BRL exibidos ao usuário utilizam `Formatter.format_currency()`.

- **Dashboard** apresenta o progresso dos aportes anuais, o resumo da carteira, os gráficos, as posições detalhadas e as 10 últimas movimentações, mesmo sem posições atuais.
- **Ativos** coordena três subtelas: detalhes da carteira, monitoramento de mercado e valuation de Bazin (incluindo a consulta Raio-X de todo o catálogo) e operações manuais/importadas da B3. Na tela Mercado, `MarketView` apenas controla a navegação secundária; `MarketMonitoringView` e `AssetDeepDiveView` renderizam uma aba cada.
- **Planejamento** possui as abas internas `Aposentadoria` e `Metas`. `PlanningView` controla os parâmetros e projeções da aposentadoria; `GoalsView` controla a seleção de metas. O usuário pode ativar independentemente o reinvestimento de dividendos e as metas de quantidade por ação. A tabela de metas aparece apenas quando habilitada; cotas e crescimento anual são editáveis e sincronizados, com salvamento automático das alterações válidas no SQLite. O editor é um fragmento Streamlit: cada edição recalcula os indicadores usando um snapshot da tela, sem executar novamente o restante da página nem consultar mercado, posições ou simulação. O serviço valida e persiste apenas os tickers alterados em um lote atômico por `AccumulationGoalPort.upsert_accumulation_goals()`; entrada inválida ou falha de gravação preserva o snapshot anterior e mostra erro. Uma execução completa da página renova o snapshot. A participação no esforço financeiro é informativa.
- **Metas no Dashboard** consolida o progresso das metas por ação em uma barra ponderada pelo esforço anual desde 01/01, recalculado ao carregar, sem depender dos pesos antigos persistidos. Metas concluídas mantêm sua participação; cotações incompletas levam a pesos iguais entre as metas de compra, com indicação na tela. O painel possui detalhes por ticker ao passar o cursor e em uma seção expansível. A barra usa azul até 100% e uma camada verde para o excedente.
- **Backup local**, na barra lateral, permite selecionar uma ou mais carteiras, com todas marcadas por padrão, solicitar senha e baixar opcionalmente uma chave de recuperação separada. A mesma seção lista os pacotes locais mais recentes primeiro, permite enviar um `.rpb` externo, valida por senha ou `.key`, apresenta seus metadados, permite escolher uma carteira e exige confirmação explícita antes da restauração.
- **`ChartThemeAdapter`** aplica aos gráficos do dashboard e do planejamento a paleta compartilhada do Plotly, tipografia, grade, legenda, margens, marcações monetárias e comportamento unificado ao passar o cursor. Também centraliza as cores de fundo e texto das movimentações para os temas claro e escuro. Cada componente de gráfico continua responsável por seus próprios dados e eixos específicos.

O histórico unificado usa `AssetService.get_portfolio_activity(limit=10)` no Dashboard e
`AssetService.get_activity_page()` em Ativos → Operações, com 25 registros por página.
A porta `PortfolioPort.get_activity_records()` é implementada
por uma consulta única de `PortfolioDAO`, com `UNION ALL` entre transações e proventos e os
metadados B3 associados. A consulta lê somente o banco ativo, limita os registros no SQLite e
ordena por data decrescente; empates apresentam transações antes de proventos e IDs decrescentes
em cada origem. O vínculo único entre registro B3 e transação evita linhas duplicadas.
O serviço interpreta custos pendentes, eventos societários, transferências de custódia e os
valores com taxas. Não altera os cálculos de aporte líquido, patrimônio ou metas.
`PortfolioPort.get_activity_page_records()` aplica filtros parametrizados por período inclusivo,
evento e ticker antes de `LIMIT/OFFSET`; a contagem e a página usam a mesma transação de leitura.
A página é ajustada ao intervalo disponível caso os resultados diminuam. A classificação pura
de eventos em `core/activity.py` é compartilhada pelo serviço e por uma função registrada na
conexão SQLite, preservando os mesmos rótulos ao filtrar e exibir, inclusive eventos societários.
`get_activity_tickers()` consulta os tickers distintos das duas origens, sem depender das posições
atuais ou carregar o histórico financeiro. O serviço valida os filtros e prepara valores e
estimativas de quantidade somente para a página retornada. Não há alteração de esquema.
`PortfolioActivityWidget` compartilha a apresentação e os estados vazio/erro entre as duas telas;
valores conhecidos usam `Formatter.format_currency()`. A tabela usa `height="content"` para
exibir todos os registros da página sem rolagem vertical interna.
Não há novo cache de atividades: cada
renderização consulta a carteira ativa, refletindo importações, regularizações e trocas de
carteira. O botão do Dashboard usa um callback de sessão para selecionar Ativos e solicitar
a aba Operações antes de instanciar os controles de navegação no rerun seguinte.
O histórico de Operações é um fragmento Streamlit: filtros e navegação não reexecutam os
formulários de lançamento/importação. Alterar filtros reinicia a página; trocar de carteira
ou restaurar outra geração no mesmo caminho reinicia também os filtros. Períodos invertidos
geram aviso; falhas de leitura geram erro sanitizado. A instrumentação de desenvolvimento
detalha `manual_entry` nas etapas
`manual_catalog`, `manual_ticker_options` e `manual_controls`, sem registrar dados financeiros.
O tempo de `manual_controls` inclui o processamento quando o formulário é enviado.
A apresentação destaca toda a linha com fundos adaptados ao tema em um `Styler`: compra em verde, venda
em vermelho, dividendo em azul, JCP em lilás, rendimento em laranja e os demais em roxo, mantendo
os nomes dos eventos visíveis. `ChartThemeAdapter.activity_row_colors()` centraliza as paletas
e retorna as cores de fundo e texto por evento; a tabela apenas aplica o estilo a toda a linha.
`ChartThemeAdapter.is_dark_theme()` identifica o tema ativo do
cliente: o tema escuro usa fundos escuros com texto claro e o claro usa fundos suaves com texto
escuro. O parser da B3 preserva
quantidade e preço unitário positivos e finitos dos proventos; metadados ausentes ou inválidos
não descartam o recebimento. `AssetService`
prioriza a quantidade informada e, sem ela, calcula Total ÷ Unitário sem arredondamento prévio,
marcando a quantidade como estimada. O unitário prioriza o preço importado, depois o total
dividido pela quantidade informada e, por último, a posição histórica na data do pagamento,
mantendo a regra antiga de Proventos recebidos. A apresentação diferencia quantidades estimadas
e mostra — quando faltam dados; valores estimados não são persistidos.
`AssetService.get_annual_dividends_metrics()` soma os unitários dos recebimentos do ano selecionado
usando a mesma prioridade de `_receipt_unit_value()` da tabela detalhada: preço informado,
total dividido pela quantidade informada e posição histórica como fallback legado.
As quantidades no fim do ano e no fim do ano anterior continuam sendo posições históricas.
`PortfolioDAO.insert_dividend()` usa uma transação com `BEGIN IMMEDIATE` para inserir ou preencher
somente metadados ausentes de um recebimento identificado por data, ticker, tipo e total.
Reimportações idênticas não duplicam registros. Dados já conhecidos não são sobrescritos;
divergências e múltiplas correspondências antigas impedem a complementação. O retorno indica
inserção ou complementação, refletida na contagem de proventos da mensagem de importação.

## Validação

O Pytest usa o `pytest.ini` para disponibilizar a raiz do repositório durante as importações. A fixture compartilhada de testes redireciona a persistência para um banco isolado e configura os adaptadores de teste.

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

O Ruff usa Python 3.10 como versão-alvo, limita as linhas a 100 caracteres e exclui intencionalmente
`tests/`. A configuração inicial do CI ignora `PLR0913` apenas nas interfaces legadas de carteira e
planejamento acompanhadas pelas issues #23 e #24. O GitHub Actions executa lint e formatação no
Ubuntu e a suíte de testes no Ubuntu e no Windows, tanto em pull requests destinados à `main` quanto
em pushes para a `main`.
