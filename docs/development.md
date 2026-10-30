# Desenvolvimento e distribuição

Para instalar e executar a partir do código, siga o [README](../README.md).
O código-fonte, seus identificadores e comentários técnicos permanecem em inglês;
a interface e a documentação do projeto estão em português brasileiro (PT-BR).

## Ambiente de desenvolvimento

Instale as dependências opcionais no ambiente virtual:

```bash
venv/bin/python -m pip install -e ".[dev]"
```

No Windows PowerShell:

```powershell
.\venv\Scripts\python.exe -m pip install -e ".[dev]"
```

O Streamlit mínimo suportado é 1.55.0, necessário para abas com carregamento apenas da
aba ativa, `width="stretch"` nos componentes e `height="content"` no histórico de
movimentações. A instalação pelas dependências declaradas garante esse mínimo.
Para atualizar um ambiente existente, execute `python -m pip install --upgrade .`
com o ambiente ativado ou o executável Python do ambiente virtual.

Os comandos abaixo usam os executáveis de `venv/bin/`; no Windows, use os equivalentes
em `venv\Scripts\`. Os dados persistentes e seus diretórios estão descritos no
[guia de uso](user-guide.md#dados-e-privacidade).

Execute a partir da raiz do repositório para carregar `.streamlit/config.toml`, que
desativa as estatísticas de uso do Streamlit com `browser.gatherUsageStats=false`.
O launcher das distribuições nativas também desativa essa opção explicitamente.

## Logging

A aplicação sempre envia logs para a saída padrão. O comportamento pode ser ajustado por variáveis
de ambiente:

- `APP_ENV=dev` habilita mensagens a partir de `DEBUG`;
- `APP_ENV=prod` mantém mensagens a partir de `INFO`;
- `LOG_TO_FILE=true` também grava em `logs/rendaperene.log`, dentro do diretório de dados local;
- `LOG_TO_FILE=false` não cria arquivos de log.

Valores ausentes ou desconhecidos usam os padrões seguros `APP_ENV=prod` e `LOG_TO_FILE=false`.
Quando habilitado, o arquivo gira ao atingir 5 MiB e mantém até três backups. Uma falha ao abrir o
arquivo não interrompe a aplicação: os registros continuam disponíveis na saída padrão. Nenhum log
é enviado para serviços externos. Os destinos configurados pela aplicação aceitam somente eventos
dos módulos do RendaPerene; detalhes internos de dependências, como `yfinance` e `peewee`, são
descartados. Tickers, quantidades, valores financeiros, nomes de carteiras e identificadores de
sessão não são registrados, inclusive em `DEBUG`. Em `APP_ENV=dev`, falhas de limpeza de temporários
da restauração registram o caminho absoluto e o traceback em `DEBUG` para diagnóstico; o aviso em
`WARNING` não inclui o caminho. Em sistemas POSIX, o diretório de logs usa permissão `0700` e os
arquivos ativos e rotacionados usam `0600`.

## Validação

As leituras de carteira são concentradas em `PortfolioReadService`: posições, resumo,
holdings, detalhe do ativo, proventos e evolução histórica usam o mesmo ledger local.
`AssetService` mantém lançamentos, importação B3, regularização, watchlist e catálogo;
`SimulationService` mantém os cálculos de aposentadoria. A conexão SQLite permanece no DAO.
O cache local guarda snapshots descartáveis por carteira, geração e revisão, separados
das cotações. Alterações de mercado atualizam os resultados sem exigir limpeza do ledger.
Essa organização não altera o schema dos bancos existentes.

Para validar especificamente o contrato de leitura e o isolamento do cache:

```bash
venv/bin/pytest tests/test_portfolio_read.py
```

Para validar as interações da tela de Planejamento com widgets reais, callbacks e
persistência em um banco temporário, execute:

```bash
venv/bin/pytest tests/test_planning_ui.py -v
```

Esses testes usam o `AppTest` do Streamlit e verificam a edição do plano, o isolamento
da Simulação Rápida e o patrimônio inicial automático/manual. Não exigem iniciar o
servidor nem abrir o navegador; a aparência visual dos gráficos requer conferência manual.

### Testes ponta a ponta (E2E)

Instale a dependência opcional e o Chromium do Playwright:

```bash
venv/bin/python -m pip install -e ".[dev,e2e]"
venv/bin/python -m playwright install chromium
venv/bin/pytest e2e --browser chromium --tracing retain-on-failure --screenshot only-on-failure
```

Em Linux, caso faltem bibliotecas do sistema, use
`venv/bin/python -m playwright install --with-deps chromium`.
Acrescente `--headed` ao comando de teste para acompanhar o navegador visualmente.

A jornada cria uma carteira pela interface, compra 10 cotas de BBAS3 a R$ 20,00 com
R$ 5,00 de taxas, confere o preço médio de R$ 20,50, vende 4 cotas e verifica as
6 restantes após reiniciar o servidor e abrir uma sessão nova. Os lançamentos são feitos
somente pela interface; consultas SQLite somente de leitura complementam as verificações
dos valores exibidos. Com uma cotação controlada de R$ 21,00, o Dashboard deve mostrar
R$ 210,00 após a compra e R$ 126,00 após a venda e a reinicialização.

O servidor executa o `app.py` completo em subprocesso com recursos copiados e diretórios
temporários para bancos, backups, caches e descoberta de carteiras antigas. As fontes
externas recebem respostas controladas no processo servidor; o navegador bloqueia URLs
externas, e chamadas externas via `socket.create_connection` são rejeitadas no servidor.
O cenário não usa credenciais OAuth ou carteiras pessoais. O servidor é encerrado também
em caso de falha; os diretórios ficam sob o armazenamento temporário gerenciado pelo pytest.

O teste `e2e/test_navigation.py` verifica a remoção do conteúdo e dos gráficos do Dashboard
ao mudar para Ativos, Operações e Planejamento, inclusive com carteira vazia.
Para validar um pacote Windows com o Edge instalado, execute no PowerShell:

```powershell
.\venv\Scripts\python.exe -m pytest e2e/test_navigation.py --e2e-executable "C:\caminho\RendaPerene\RendaPerene.exe" --browser chromium --browser-channel msedge --tracing retain-on-failure --screenshot only-on-failure
```

Esse modo exige um pacote com suporte aos overrides `WIN_PD_OVERRIDE_*` do `platformdirs`;
o pacote 0.13.2 foi validado com esse suporte. Ele usa armazenamento temporário separado,
outra porta e configuração OAuth ausente. A origem do pacote deve estar sem diretório
legado `database` e fora de um diretório com nome `RendaPerene-v...`, evitando descoberta
de carteiras antigas. As fontes de mercado do executável continuam sendo as do pacote.

`venv/bin/pytest` continua executando apenas `tests/`, sem exigir navegador. Execute
`venv/bin/pytest e2e` explicitamente para a suíte de navegador. Não coloque esses testes
dentro de `tests/`: a fixture global dessa pasta configura adaptadores no processo do
pytest, enquanto o servidor E2E precisa de seu próprio isolamento.

O job separado E2E do CI executa Chromium no Ubuntu. Em falhas, o artefato
`e2e-diagnostics` guarda os logs do servidor e as capturas/traces disponíveis em
`test-results/`, por sete dias. Para examinar um trace localmente:

```bash
venv/bin/python -m playwright show-trace test-results/<teste>/trace.zip
```

### Medição de navegação

Para medir sem registrar dados pessoais, execute `APP_ENV=dev RENDA_PERENE_NAVIGATION_METRICS=true venv/bin/streamlit run app.py`. Com uma carteira de teste, visite Dashboard, Ativos e Monitoramento uma vez para a medição fria e repita a mesma navegação sem mutações para a medição quente. Os logs seguem o formato `identificador.técnico duration: <ms> ms` e não incluem carteira, ticker, valores, caminhos ou identificadores. Os nomes são técnicos e hierárquicos, como `ativos.carteira.price_history.total` e `planejamento.projection_chart`: `total` mede um render completo e as demais fases isolam seus módulos. A instrumentação fica desabilitada fora desse modo explícito de desenvolvimento.

Para comparar resultados, descarte a primeira inicialização do servidor, faça três repetições de cada estado e registre a mediana por tela. Uma mutação de transação, provento, correção, importação ou troca de carteira inicia uma nova medição fria da projeção local.


Execute os testes de regressão e as verificações de lint:

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

O Ruff usa Python 3.10 como versão-alvo, limita as linhas a 100 caracteres e exclui intencionalmente
`tests/` do escopo configurado. O GitHub Actions executa lint e formatação no Ubuntu e a suíte de
testes com Python 3.10 e 3.14 no Ubuntu e no Windows, tanto em pull requests destinados à `main`
quanto em pushes para a `main`.
Os jobs Windows têm limite de 30 minutos, para acomodar a variação de tempo dos runners;
os demais mantêm o limite de 15 minutos.

## Distribuição nativa

Para validar isoladamente a limpeza de runtime do instalador no Windows, com Inno Setup
instalado, execute:

```powershell
.\scripts\test_windows_runtime_cleanup.ps1
```

O teste cria somente uma instalação sintética em `out/`, sem atalhos nem registro de
desinstalação. Ele confirma que atualizações removem diretórios vazios `.dist-info` antigos,
preservam os metadados atuais e diretórios não vazios e não seguem junctions. Os artefatos
ficam em `out/runtime-cleanup-tests/` para diagnóstico. O teste completo de ciclo de vida
`scripts/test_windows_installer.ps1` continua restrito a CI Windows descartável.
No CI, ele também executa `e2e/test_navigation.py` no `.exe` instalado após cada atualização,
usando Edge headless e dependências opcionais `dev,e2e` em `venv_dist`.

Os pacotes são compilados pelo PyInstaller em seu próprio sistema operacional, sempre no modo
`onedir`. A definição comum está em `RendaPerene.spec`; ela inclui o código da aplicação, o
catálogo base, `version.txt` e os recursos de Streamlit/Plotly, mas nenhum banco pessoal ou arquivo
gerado.

No Windows, execute `build_windows_exe.bat` em um checkout com Python instalado. No Ubuntu 22.04 ou
mais recente, execute `bash scripts/build_linux.sh`. Os comandos instalam as dependências declaradas
em `pyproject.toml` (incluindo a dependência opcional `packaging` do PyInstaller) em ambientes
virtuais dedicados, criam
respectivamente `RendaPerene-v<versão>-windows-x64.zip` ou
`RendaPerene-v<versão>-ubuntu-x64.tar.gz` e executam uma verificação de recursos e um smoke check do
servidor Streamlit. O arquivo `.tar.gz` preserva as permissões executáveis.

O workflow `Package native distributions` repete esses passos em runners nativos Windows e Ubuntu
22.04. Em builds de tags, o nome da tag (por exemplo, `v0.7.0`) precisa corresponder ao conteúdo de
`version.txt`; uma divergência interrompe o build.

Escolha o ZIP para Windows 64 bits ou o `tar.gz` para Ubuntu 64 bits. Extraia o pacote em uma pasta
própria; os dados persistentes ficam nos diretórios descritos em [Dados e privacidade](user-guide.md#dados-e-privacidade)
e não são incluídos nos artefatos.

## Arquitetura

A aplicação é dividida em três camadas:

- `core/`: infraestrutura de banco de dados, implementações de DAOs, portas, formatação, processamento de arquivos da B3 e integração de dados de mercado desacoplada da interface.
- `services/`: regras de carteira, planejamento e valuation independentes de framework.
- `views/`: telas e componentes de apresentação do Streamlit.

O `app.py` é a raiz de composição: inicializa a persistência, conecta os adaptadores de produção, prepara o estado da sessão e direciona para as telas Dashboard, Ativos e Planejamento. Consulte o [ARCHITECTURE.md](../ARCHITECTURE.md) para conhecer o modelo de persistência, os limites entre dependências, as regras financeiras e as integrações.


Para criar e publicar uma versão, consulte o [guia de releases](release.md).
