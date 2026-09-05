<div align="center">

# 💼 RendaPerene

**Acompanhamento local de carteira e planejamento de aposentadoria para investidores brasileiros**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![Pytest](https://img.shields.io/badge/Tested_with-Pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org/)

</div>

## Visão geral

O RendaPerene é uma aplicação Streamlit para registrar carteiras de investimentos brasileiros (B3) e simular a aposentadoria. A carteira e as configurações do planejamento são armazenadas em arquivos SQLite locais, enquanto integrações públicas existentes fornecem dados atuais do mercado e indicadores macroeconômicos.

A interface e a documentação do projeto estão em português brasileiro (PT-BR); o código-fonte, seus identificadores e comentários técnicos permanecem em inglês.

## Funcionalidades

- **Dashboard da carteira:** totais da carteira, progresso dos aportes anuais, indicadores de desempenho, tabelas de posições e gráficos Plotly.
- **Operações manuais e importação da B3:** registro manual de compras, vendas, dividendos, JCP e rendimentos, ou importação do arquivo `.xlsx` oficial da B3.
- **Regras de movimentação:** cálculo do preço médio ponderado incluindo taxas; tratamento de desdobramentos/bonificações, grupamentos, resgates e importações duplicadas.
- **Detalhes dos ativos e monitor de mercado:** acompanhamento dos ativos em carteira e dos selecionados manualmente, histórico de preços e dividendos, modelos de preço-teto de Bazin e consulta Raio-X de todo o catálogo, com indicadores de valuation e dividend yields anuais calculados a partir do preço de fechamento de cada ano.
- **Planejamento de aposentadoria:** cálculo do aporte mensal vitalício e do aporte corrigido ao longo do tempo por meio da fórmula de anuidade antecipada, com projeções baseadas no plano salvo e no histórico da carteira.
- **Metas de investimento:** a tela de Planejamento possui uma aba `Metas` para ativar independentemente o reinvestimento de dividendos e as metas de quantidade por ação. A base anual das metas por ação é a quantidade mantida em 1º de janeiro; o Dashboard exibe uma barra ponderada pelos pesos, com detalhes por ticker ao passar o cursor e em uma seção expansível. Peso 0% desativa o ativo, o progresso pode superar 100% e históricos parciais ou indisponíveis exibem uma observação sem inventar uma meta.
- **Múltiplas carteiras locais:** seleção de uma base de dados existente ou criação de uma nova carteira local pela barra lateral.

## Dados e privacidade

Os dados da carteira são armazenados localmente em bancos SQLite fora da pasta da aplicação.
Assim, uma versão descompactada em uma nova pasta encontra as mesmas carteiras sem exigir cópias
manuais. Os diretórios padrão são:

- Windows: `%LOCALAPPDATA%\RendaPerene`;
- Linux: `$XDG_DATA_HOME/RendaPerene` ou, quando a variável não estiver definida,
  `~/.local/share/RendaPerene`.

Dentro desse diretório, `database/` contém as carteiras, `catalog/assets.csv` contém o catálogo
gravável, `backups/` preserva cópias de recuperação e `logs/` é reservado para registros locais.
A aplicação não utiliza banco de dados em nuvem, contas de usuário ou telemetria, nem realiza
scraping do portal da B3.

Bancos inválidos são ignorados na seleção. Se a carteira ativa for removida ou deixar de ser um
SQLite válido, a aplicação seleciona outra carteira disponível e recarrega suas configurações sem
reutilizar os dados de planejamento da anterior. Se nenhuma carteira válida existir, uma nova
carteira de recuperação é criada com outro nome e o arquivo inválido permanece intacto.

Na primeira execução com o novo layout, a barra lateral oferece a importação de bancos
arquivos `.db` encontrados na antiga pasta `database/`, tanto ao lado da aplicação quanto em
pastas irmãs de releases anteriores chamadas `RendaPerene-v*`. Quando o mesmo nome existe em mais
de uma versão, a cópia válida mais recente é oferecida. A origem é mantida, uma cópia de recuperação
é criada em `backups/legacy-import/` e cada cópia é validada como SQLite antes de ficar disponível.
Repetir a operação é seguro e um arquivo existente com conteúdo diferente nunca é sobrescrito. Caso
o primeiro carregamento já tenha criado uma carteira principal somente com os valores padrão, a
publicação final aguarda as operações em andamento e verifica novamente se ela continua sem dados
do usuário. Caso positivo, ela pode ser substituída com segurança; qualquer dado ou configuração
alterada impede essa substituição. Após uma importação bem-sucedida, a carteira importada é ativada
e seus dados de planejamento são recarregados. Os bancos da demonstração hospedada continuam
isolados por sessão em armazenamento temporário. Bancos demo inválidos são restaurados
automaticamente, e diretórios de sessões inativas há mais de 24 horas são descartados.

Na primeira migração, o catálogo gravável também incorpora os registros alternativos dos
`assets.csv` encontrados na instalação atual e nas pastas de releases anteriores. Depois, ele é
atualizado a partir do catálogo incluído em cada nova versão: metadados e tickers do pacote são
incorporados sem remover registros locais de ativos que ainda não fazem parte do catálogo oficial.
Catálogos antigos sem o cabeçalho esperado são ignorados; se a cópia gravável estiver malformada,
ela é recuperada a partir do catálogo válido incluído no pacote.

O acesso à rede é necessário para obter dados atualizados:

- O Yahoo Finance (`yfinance`) fornece cotações da B3, indicadores de mercado, histórico de preços e dados de dividendos. Se uma cotação em tempo real não estiver disponível, a análise do ativo utiliza o último fechamento diário válido.
- O Banco Central do Brasil (BCB) fornece indicadores de IPCA, Selic e salário mínimo.

A importação da B3 é iniciada pelo usuário: baixe a planilha oficial no Portal do Investidor da B3 e envie-a pela aplicação. Bancos locais e planilhas pessoais são ignorados pelo Git; não faça commit desses arquivos.

Entradas de aquisição, subscrição ou depósito com valor financeiro zero ou ausente ficam com
**custo pendente**. A quantidade permanece na carteira, mas preço médio, custo e rentabilidade
ficam indisponíveis até a regularização em **Ativos → Operações → Custos pendentes da B3**.
Informe o preço unitário ou o valor total da aquisição, sem taxas, e acrescente as taxas
opcionais no campo separado. Consulte o comprovante da oferta, extrato financeiro,
nota/comprovante de liquidação ou declaração de IR. A aplicação não infere custos por
cotações históricas nem usa preços fixos por ativo.

Transferências de custódia não são aportes ou resgates. Pares de **Transferência** com o mesmo
ativo, data e quantidade, sendo um débito e um crédito, representam apenas a troca de corretora
e são ignorados mesmo sem valor financeiro. Uma entrada de **Transferência** sem o par é ignorada
quando o histórico de dias anteriores cobre a quantidade transferida com custo conhecido; sem
cobertura suficiente, permanece como posição com custo pendente. Movimentações de
**Transferência - Liquidação** continuam sendo compras ou vendas conforme a direção. Quando uma
liquidação de crédito não informa valor financeiro, ela é registrada como aquisição com custo
pendente. Desdobramentos, bonificações e grupamentos mantêm suas regras próprias.
O registro de origem e as decisões de importação ficam no SQLite local: reimportar o mesmo
extrato não duplica operações, desfaz correções nem recria transferências ignoradas.
Os registros antigos são preservados; uma reimportação associa movimentações idênticas que
ainda não tenham origem registrada. Históricos anteriores importados posteriormente não
reclassificam automaticamente transferências já processadas.

## Requisitos

- Python 3.10 ou mais recente
- `pip`
- Acesso à rede apenas para consultar dados atualizados do Yahoo Finance ou do BCB

## Instalação

Clone o repositório, crie um ambiente virtual e instale a aplicação:

```bash
git clone https://github.com/R-Mascarenhas/RendaPerene.git
cd RendaPerene

python3 -m venv venv
source venv/bin/activate
python -m pip install .
```

Para desenvolvimento, instale também as dependências opcionais de testes e lint:

```bash
python -m pip install -e ".[dev]"
```

No Windows PowerShell, ative o ambiente com:

```powershell
.\venv\Scripts\Activate.ps1
```

## Execução

Inicie a aplicação Streamlit:

```bash
venv/bin/streamlit run app.py
```

Se o ambiente virtual estiver ativo, `streamlit run app.py` é equivalente. Na primeira execução,
a aplicação cria e inicializa `portfolio.db` no diretório de dados do usuário descrito acima caso
o arquivo ainda não exista.

## Validação

Execute os testes de regressão e as verificações de lint:

```bash
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

O Ruff usa Python 3.10 como versão-alvo, limita as linhas a 100 caracteres e exclui intencionalmente `tests/` do escopo configurado. O GitHub Actions executa os três comandos de validação de forma independente em pull requests destinados à `main` e em pushes para a `main`.

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

## Arquitetura

A aplicação é dividida em três camadas:

- `core/`: infraestrutura de banco de dados, implementações de DAOs, portas, formatação, processamento de arquivos da B3 e integração de dados de mercado desacoplada da interface.
- `services/`: regras de carteira, planejamento e valuation independentes de framework.
- `views/`: telas e componentes de apresentação do Streamlit.

O `app.py` é a raiz de composição: inicializa a persistência, conecta os adaptadores de produção, prepara o estado da sessão e direciona para as telas Dashboard, Ativos e Planejamento. Consulte o [ARCHITECTURE.md](ARCHITECTURE.md) para conhecer o modelo de persistência, os limites entre dependências, as regras financeiras e as integrações.

## Licença

Este projeto é distribuído sob a [GNU Affero General Public License v3.0](LICENSE).
