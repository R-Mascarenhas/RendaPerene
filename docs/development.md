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

## Distribuição nativa

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
