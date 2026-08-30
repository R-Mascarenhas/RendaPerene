# Arquitetura do RendaPerene

## Visão geral

O RendaPerene é uma aplicação Python e Streamlit para acompanhar carteiras de investimentos brasileiros (B3) e planejar a aposentadoria. Os dados das carteiras são mantidos em arquivos SQLite locais; a aplicação importa planilhas da B3, obtém dados de mercado por integrações públicas existentes e apresenta a interface em português brasileiro.

A aplicação prioriza o armazenamento local. Ela não utiliza banco de dados em nuvem, autenticação de usuários, telemetria ou scraping automatizado do portal da B3.

## Execução e composição

O `app.py` é a raiz de composição. Ele:

1. seleciona e inicializa o banco de dados da carteira ativa;
2. configura o Streamlit;
3. conecta os adaptadores de produção da carteira, do planejamento, do processamento da B3 e dos dados de mercado com cache;
4. inicializa o estado da sessão; e
5. direciona para as três telas principais: Dashboard, Ativos e Planejamento.

Em uma execução local normal, o banco ativo é `portfolio.db` ou outro arquivo `portfolio*.db`
selecionado na barra lateral, sempre dentro do diretório gravável do usuário. Quando um ambiente de
hospedagem compartilhada do Streamlit é detectado, a aplicação cria para a sessão um banco clonado
do recurso `database/portfolio_demo.db` em um diretório temporário isolado; esse recurso serve
apenas para demonstração e não representa o modelo principal de persistência.

Execute a aplicação com:

```bash
venv/bin/streamlit run app.py
```

## Camadas e dependências

O repositório possui três camadas principais:

- **`core/`** contém a infraestrutura técnica e os contratos compartilhados. Inclui o `DatabaseManager`, os protocolos de `core/ports.py`, DAOs SQLite, constantes, textos localizados, formatação, gerenciamento de sessão, processamento da B3 e a integração de dados de mercado desacoplada da interface.
- **`services/`** contém as regras de aplicação e de domínio. Os serviços dependem de portas, e não do código de apresentação.
- **`views/`** contém a renderização e as interações do Streamlit. `StreamlitCachedMarketData` é o adaptador da camada de apresentação que adiciona o cache do Streamlit à implementação de dados de mercado desacoplada da interface.

A direção das dependências é `views` → `services` → contratos e adaptadores de `core`. A raiz de composição seleciona os adaptadores concretos. As views não devem conter cálculos de negócio, SQL direto ou regras de processamento das planilhas da B3.

### Serviços de domínio

- `AssetService` é a fonte única da verdade para transações, dividendos, posições dos ativos, evolução histórica, lista de ativos monitorados, registros normalizados do catálogo e definição do dividend yield alvo do modelo de Bazin com base em dados de mercado.
- `SimulationService` controla as configurações de aposentadoria e os cálculos de anuidade antecipada. Os consumidores devem usar `get_current_simulation()` em vez de reimplementar o cálculo dos aportes.
- `GoalService`, em `services/goals_service.py`, controla as metas gerais da carteira, incluindo o reinvestimento opcional de dividendos e o progresso dos aportes anuais. Ele consome os valores planejados de `SimulationService` por meio de `PlanningProviderPort`, sem duplicar os cálculos de aposentadoria.
- `ShareQuantityGoalService`, em `services/share_quantity_goal_service.py`, controla a meta anual de quantidade de cotas por ticker. A base é a quantidade mantida em 1º de janeiro do ano corrente; o progresso mede as aquisições pagas desde essa data, excluindo ações corporativas. O serviço distribui os proventos planejados entre pesos iguais ou personalizados, considera peso zero como inatividade, calcula a meta de cotas a partir do histórico de proventos e informa o crescimento planejado da posição, permitindo progresso acima de 100%.
- `ValuationService` contém as regras puras do dividend yield alvo e do preço-teto de Bazin; não possui dependências do Streamlit, do banco de dados ou dos dados de mercado.

### Portas e adaptadores

O arquivo `core/ports.py` define as fronteiras para persistência da carteira, acesso ao catálogo de ativos, dados de mercado, configuração do planejamento, registro do esquema do banco, processamento das planilhas da B3 e comunicação entre serviços. Os adaptadores de produção são os DAOs SQLite, `MarketData` e `B3ExcelParserAdapter`. Nos testes, essas fronteiras são substituídas por bancos isolados, mocks ou adaptadores injetados.

## Persistência

`ApplicationPaths`, em `core/application_paths.py`, é o módulo profundo que separa os recursos
descartáveis do pacote dos dados graváveis. Sua interface resolve os recursos incluídos no pacote,
a raiz de dados, o diretório das carteiras, o catálogo, os logs e os backups. Também prepara o
layout, inventaria apenas bancos SQLite válidos e concentra a migração das versões antigas. A raiz
de composição `app.py` conecta esses caminhos ao `DatabaseManager`, ao catálogo e aos adaptadores;
as views não calculam caminhos do sistema operacional.

As raízes graváveis padrão são `%LOCALAPPDATA%\RendaPerene` no Windows e
`$XDG_DATA_HOME/RendaPerene` no Linux, com fallback para `~/.local/share/RendaPerene`. O executável
e seus recursos podem ser substituídos sem mover as carteiras. Sessões da demonstração hospedada
usam uma raiz temporária própria por sessão. Os caminhos do banco e do catálogo demo são resolvidos
a cada operação a partir do contexto atual do Streamlit, sem armazenar o identificador de uma
sessão nos singletons compartilhados. O caminho resolvido do catálogo também integra a chave de
cache, impedindo que leituras sejam reutilizadas entre sessões.

Ao preparar o armazenamento gravável, `ApplicationPaths` incorpora primeiro os antigos `assets.csv`
ao lado do executável e nas pastas irmãs `RendaPerene-v*`, em ordem de versão, e depois aplica o
catálogo incluído na versão atual. Assim, a baseline mais nova prevalece para tickers oficiais,
enquanto tickers alternativos existentes apenas nos catálogos legados são preservados.

Quando existem bancos `portfolio*.db` na antiga pasta `database/` ao lado da aplicação ou em pastas
irmãs de releases anteriores chamadas `RendaPerene-v*`, a barra lateral oferece sua importação. Se
mais de uma versão contém o mesmo nome de carteira, a versão mais recente prevalece. A migração
valida a origem, copia (sem mover) um backup para
`backups/legacy-import/`, valida novamente a cópia temporária e somente então publica o banco em
`database/`. A operação é idempotente e recusa qualquer sobrescrita quando há conteúdo diferente.
Bancos principais inicializados automaticamente apenas com os valores padrão podem ser substituídos
durante a importação; qualquer dado ou configuração do usuário torna o destino não substituível. A
cópia recuperável relevante permanece em `backups/legacy-import/`. Ao publicar uma carteira
importada, a raiz de composição invalida o estado da sessão derivado do banco e reinicia a execução
para carregar as configurações persistidas antes que a interface permita novas edições.
Bancos inválidos não ficam disponíveis para seleção. Nomes de arquivos de carteiras e dados
financeiros não são escritos em logs.

O `DatabaseManager` descobre os provedores de esquema em `core/daos/` e solicita que cada DAO
registrado crie ou migre suas tabelas. Todas as tabelas ficam no banco SQLite da carteira ativa; o
catálogo estático incluído no pacote é copiado para o arquivo gravável `catalog/assets.csv` na
primeira execução. Nas versões seguintes, o baseline incluído no novo pacote atualiza metadados e
adiciona tickers, enquanto registros alternativos existentes somente no catálogo do usuário são
preservados pela mesclagem baseada em `CÓDIGO`.

| Armazenamento | Finalidade |
| --- | --- |
| `transactions` | Registro das movimentações da carteira: `id`, `date`, `ticker`, `transaction_type`, `quantity`, `unit_price` e `fees`. Os tipos persistidos pela aplicação são `BUY`, `SELL` e `GROUP`. |
| `dividends` | Proventos recebidos: `id`, `date`, `ticker`, `dividend_type` e `total_value`; os tipos são `DIVIDEND`, `JCP` e `YIELD`. |
| `tracked_market_assets` | Tickers acompanhados manualmente. Os ativos em carteira são combinados com essa lista no monitor de mercado. |
| `dividend_corrections` | Ajustes de dividendos por ticker e por ano, identificados por `(ticker, year)`. |
| `planning_configuration` | Configuração única (`id = 1`): data de nascimento, idade de aposentadoria, dados de renda, taxa de juros anual, salário mínimo, patrimônio inicial, modalidade de renda, parâmetros do modelo de Bazin e data opcional de início do planejamento. |
| `asset_accumulation_goals` | Uma meta de quantidade por ticker: base anual persistida, quantidade-alvo e modalidade, percentual-alvo opcional, peso editável (incluindo zero), estado ativo, média de proventos de cinco anos e data de criação. A aplicação atualiza a base efetiva para 1º de janeiro no carregamento, sem depender de salvar novamente a cada virada de ano. |
| `goal_settings` | Preferências únicas da carteira para reinvestimento de dividendos e metas de quantidade de ações. O reinvestimento é ativado por padrão; as metas por ação permanecem desativadas até serem habilitadas. |
| `catalog/assets.csv` | Cópia gravável do catálogo estático da B3 com metadados dos tickers. Tickers desconhecidos encontrados na importação podem ser adicionados como registros alternativos do catálogo. |

O SQLite não declara chaves estrangeiras entre esses armazenamentos. Os serviços preservam programaticamente a consistência necessária.

## Regras financeiras e de importação

O importador da B3 recebe a planilha selecionada pelo usuário, normaliza suas colunas e datas e produz registros internos de transações e dividendos em inglês.

- Compras atualizam o preço médio ponderado, incluindo as taxas.
- Vendas reduzem a quantidade mantida sem alterar o preço médio da posição restante.
- Desdobramentos e bonificações da B3 são armazenados como transações `BUY` com custo zero.
- Grupamentos são armazenados como transações `GROUP`, que substituem a quantidade atual pela quantidade informada.
- Resgates são armazenados como transações `SELL`.
- Transferências de custódia sem custo são ignoradas; transferências com valor diferente de zero são interpretadas de acordo com sua direção de crédito ou débito.
- Os cálculos dos aportes para aposentadoria usam pagamentos de anuidade antecipada (`type = 1`) por meio de `SimulationService.pmt_annuity_due()`.

## Integrações externas

- O `yfinance` fornece cotações da B3, histórico de preços e dados de dividendos e valuation. Os tickers são consultados com o sufixo `.SA`. Quando a cotação atual está ausente, é zero ou não é finita, a integração utiliza o último fechamento diário positivo e finito antes de aplicar as regras de valuation.
- A integração calcula médias de proventos usando os anos disponíveis desde a listagem; anos listados sem pagamento contam como zero. Sem histórico utilizável, o planejamento mostra uma observação e não inventa uma meta de cotas.
- Os endpoints SGS do Banco Central do Brasil (BCB) fornecem valores de IPCA, Selic e salário mínimo. A integração desacoplada da interface utiliza valores alternativos quando uma requisição falha.
- O adaptador do Streamlit mantém cotações e análises detalhadas dos ativos em cache por 10 minutos, históricos de preço por uma hora e indicadores do BCB por 30 dias. A análise detalhada inclui até dez anos completos do histórico anual de dividendos usado na consulta Raio-X. O dividend yield histórico de cada ano utiliza o último preço de fechamento não ajustado daquele ano, e não a cotação atual.

Essas integrações permitem o uso local, mas precisam de acesso à rede quando dados atualizados são solicitados. A aplicação não realiza scraping do portal da B3; o próprio usuário importa a planilha oficial da B3.

## Apresentação

O código, seus identificadores, o SQL e os comentários técnicos estão em inglês. A documentação, os textos da interface, os rótulos dos gráficos, as mensagens de ajuda e as tabelas renderizadas estão em português brasileiro. Valores em BRL exibidos ao usuário utilizam `Formatter.format_currency()`.

- **Dashboard** apresenta o progresso dos aportes anuais, o resumo da carteira, os gráficos e as posições detalhadas.
- **Ativos** coordena três subtelas: detalhes da carteira, monitoramento de mercado e valuation de Bazin (incluindo a consulta Raio-X de todo o catálogo) e operações manuais/importadas da B3. Na tela Mercado, `MarketView` apenas controla a navegação secundária; `MarketMonitoringView` e `AssetDeepDiveView` renderizam uma aba cada.
- **Planejamento** possui as abas internas `Aposentadoria` e `Metas`. `PlanningView` controla os parâmetros e projeções da aposentadoria; `GoalsView` controla a seleção de metas. O usuário pode ativar independentemente o reinvestimento de dividendos e as metas de quantidade por ação. A tabela de metas aparece apenas quando habilitada, e peso 0% desativa o ativo sem um controle separado por linha.
- **Metas no Dashboard** consolida o progresso das metas por ação em uma barra ponderada pelos pesos, com detalhes por ticker ao passar o cursor e em uma seção expansível. A barra usa azul até 100% e uma camada verde para o excedente.
- **`ChartThemeAdapter`** aplica aos gráficos do dashboard e do planejamento a paleta escura compartilhada do Plotly, tipografia, grade, legenda, margens, marcações monetárias e comportamento unificado ao passar o cursor. Cada componente de gráfico continua responsável por seus próprios dados e eixos específicos.

## Validação

O Pytest usa o `pytest.ini` para disponibilizar a raiz do repositório durante as importações. A fixture compartilhada de testes redireciona a persistência para um banco isolado e configura os adaptadores de teste.

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

O Ruff usa Python 3.10 como versão-alvo, limita as linhas a 100 caracteres e exclui intencionalmente `tests/`. A configuração inicial do CI ignora `PLR0913` apenas nas interfaces legadas de carteira e planejamento acompanhadas pelas issues #23 e #24. O GitHub Actions executa lint, formatação e testes de forma independente em pull requests destinados à `main` e em pushes para a `main`.
