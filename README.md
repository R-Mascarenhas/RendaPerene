<div align="center">

# 💼 RendaPerene

**Acompanhamento local de carteira e planejamento de aposentadoria para investidores brasileiros**

[![Python 3.10–3.14](https://img.shields.io/badge/python-3.10--3.14-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![Pytest](https://img.shields.io/badge/Tested_with-Pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org/)

</div>

## Visão geral

O RendaPerene é uma aplicação Streamlit para registrar carteiras de investimentos brasileiros (B3) e simular a aposentadoria. A carteira e as configurações do planejamento são armazenadas em arquivos SQLite locais, enquanto integrações públicas existentes fornecem dados atuais do mercado e indicadores macroeconômicos.

A interface e a documentação do projeto estão em português brasileiro (PT-BR); o código-fonte, seus identificadores e comentários técnicos permanecem em inglês.

## Download

Baixe o pacote mais recente para Windows ou Ubuntu na página de
[Releases do RendaPerene](https://github.com/R-Mascarenhas/RendaPerene/releases/latest). A aplicação
é executada localmente e abre a interface Streamlit no navegador do próprio computador.

## Funcionalidades

- **Dashboard da carteira:** totais da carteira, progresso dos aportes anuais, indicadores de desempenho, tabelas de posições, gráficos Plotly e as 10 últimas movimentações da carteira ativa.
- **Operações manuais e importação da B3:** registro manual de compras, vendas, dividendos, JCP e rendimentos, ou importação do arquivo `.xlsx` oficial da B3. A aba **Ativos → Operações** também reúne o histórico de movimentações em páginas de 25 registros, com filtros por período, evento e ticker, acessível pelo botão no Dashboard.
- **Ações no detalhamento da carteira:** em **Ativos → Carteira**, os blocos **Registrar movimentação** e **Meta anual deste ativo** ficam vinculados ao ticker selecionado. O formulário reutiliza as regras de Operações para compras, vendas, proventos, desdobros/bonificações e grupamentos. Cotas e crescimento sobre a posição de 01/01 aparecem lado a lado. Alterações são salvas automaticamente ao confirmar com Enter ou sair do campo, sem botão de salvar; editar um campo atualiza o outro. Sem posição em 01/01, o percentual fica desabilitado com uma explicação e a meta continua editável por cotas. Metas individuais aparecem na aba **Metas** mesmo com o acompanhamento geral desativado e compartilham os mesmos registros. Com o acompanhamento ativo, o detalhamento mostra progresso anual e valor restante estimado. Salvar atualiza os dados na próxima renderização; cotação indisponível aparece como N/D sem impedir salvar a meta.
- **Regras de movimentação:** cálculo do preço médio ponderado incluindo taxas; tratamento de desdobramentos/bonificações, grupamentos, resgates e importações duplicadas.
- **Detalhes dos ativos e monitor de mercado:** acompanhamento dos ativos em carteira e dos selecionados manualmente, histórico de preços e dividendos, modelos de preço-teto de Bazin e consulta Raio-X de todo o catálogo, com indicadores de valuation e dividend yields anuais calculados a partir do preço de fechamento de cada ano.
- **Planejamento de aposentadoria:** cálculo do aporte mensal vitalício e do aporte corrigido ao longo do tempo por meio da fórmula de anuidade antecipada, com projeções baseadas no plano salvo e no histórico da carteira.
- **Metas de investimento:** a tela de Planejamento possui uma aba `Metas` para ativar independentemente o reinvestimento de dividendos e as metas de quantidade por ação. A meta anual de cada ação pode ser editada por quantidade de cotas ou crescimento percentual, com a quantidade de 1º de janeiro como base fixa. Edições válidas são salvas automaticamente ao confirmar a célula, sem botão de salvar. Durante a edição, os indicadores usam os dados já carregados; recarregar a tela atualiza cotações e posições. Crescimento de 0% mantém a posição; percentuais negativos reduzem e −100% corresponde a zero cotas. Metas de redução permanecem visíveis após a venda total. Ao abrir uma carteira antiga, as metas por proventos ou percentual são convertidas automaticamente em cotas fixas, preservando os alvos já salvos. O percentual continua disponível na interface, calculado sobre a posição de 01/01. As metas independem dos proventos planejados; o plano mostra esforço anual estimado desde 01/01, participação nesse esforço, valor restante para investir pela posição atual, proventos projetados e aporte externo anual necessário. O esforço usa a cotação atual e não diminui com as compras realizadas; o aporte externo anual desconta os proventos anuais projetados para a posição-alvo desse esforço, sem considerar vendas planejadas como recursos. As explicações ficam no ícone de informação de cada indicador. Os proventos projetados pressupõem a posição-alvo mantida durante um ano; o aporte externo pressupõe seu reinvestimento. O aporte anual previsto no planejamento de aposentadoria serve para comparação. A falta de cotação ou de histórico de proventos aparece como N/D sem impedir salvar. O Dashboard exibe o progresso por ticker e uma barra consolidada com pesos recalculados pelo esforço anual, incluindo metas já concluídas. Quando faltam cotações, usa pesos iguais entre as metas de compra; o progresso pode superar 100%.
- **Múltiplas carteiras locais:** seleção, criação e exclusão recuperável de carteiras pela barra lateral.
- **Backup local consistente:** seleção de uma ou mais carteiras para criar um único conjunto de backup, inclusive quando o SQLite está em uso ou opera com WAL.

## Dados e privacidade

Os dados da carteira são armazenados localmente em bancos SQLite fora da pasta da aplicação.
Assim, uma versão descompactada em uma nova pasta encontra as mesmas carteiras sem exigir cópias
manuais. Os diretórios padrão são:

- Windows: `%LOCALAPPDATA%\RendaPerene`;
- Linux: `$XDG_DATA_HOME/RendaPerene` ou, quando a variável não estiver definida,
  `~/.local/share/RendaPerene`.

Dentro desse diretório, `database/` contém as carteiras, `backups/` preserva cópias de recuperação
e `logs/` é reservado para registros locais. O catálogo `assets.csv` é um recurso somente leitura
incluído na aplicação, não um dado da carteira. A aplicação não utiliza banco de dados em nuvem,
contas de usuário ou telemetria, nem realiza scraping do portal da B3.

A seção **Backup local** da barra lateral permite selecionar uma ou mais carteiras; todas aparecem
marcadas por padrão. O backup é publicado como um único pacote `.rpb` somente depois de todos os
snapshots consistentes, hashes e metadados internos serem criados e cifrados. Cada carteira representa
um estado SQLite consistente, mas carteiras diferentes do mesmo pacote podem corresponder a instantes
ligeiramente distintos. Falhas, carteiras inválidas ou bloqueadas não publicam pacote parcial.
O nome do arquivo começa com a data e hora UTC da criação, por exemplo
`2026-09-22_14-30-45_123456_UTC_rendaperene_<identificador>.rpb`. O identificador final evita
sobrescrever outro backup, e os pacotes antigos com nome apenas UUID continuam restauráveis.

Os backups são pacotes `.rpb` criptografados por senha. A senha deve ter ao menos quatro
caracteres; senhas longas são recomendadas. Após a criação, a aplicação também oferece uma chave de
recuperação `.key`, que deve ser guardada separadamente do pacote e de futuros uploads. Perder a
senha e a chave impede recuperar aquele backup, mas não afeta a carteira SQLite ativa, que continua
sem criptografia nesta versão.
Ao baixar a chave, ela recebe o mesmo nome-base do pacote `.rpb`, com extensão `.key`, para facilitar
a identificação do par. A correspondência é verificada pelo identificador interno, não pelo nome.

Na mesma seção, **Restaurar backup** lista os pacotes `.rpb` salvos nesta instalação, com os mais
recentes primeiro. Também é possível enviar um pacote de outra instalação. O seletor de arquivos do
navegador não permite abrir automaticamente na pasta de backups; para pacotes locais, escolha um item
da lista. A restauração exige a senha ou chave `.key`. Depois de autenticar o pacote, a aplicação
mostra a data e hora do backup no fuso local (ou em UTC se a conversão não for representável), a
carteira do pacote e qual carteira local será substituída ou adicionada, sem expor dados financeiros.
Pacotes com várias carteiras são restaurados uma carteira por vez. Quando a identidade já existe nesta
instalação, a carteira correspondente é substituída. Para uma identidade nova, o usuário escolhe um
nome local de até 60 caracteres, usando
letras, números, espaços, hífen ou sublinhado; nomes já ocupados são recusados e nenhuma outra
carteira é sobrescrita. Caracteres que usam vários bytes podem exigir um nome menor devido ao limite
do sistema de arquivos. O nome escolhido aparece na lista de carteiras, sem alterar o pacote
original. A restauração recusa hash, SQLite, identidade, metadados ou schema incompatíveis antes de
alterar `database/`.

Quando a data autenticada do backup é anterior à modificação mais recente do SQLite ou WAL local, a
interface avisa que mudanças mais novas podem ser perdidas. Esse aviso não decide qual versão é a
correta, pois relógios de dispositivos diferentes podem divergir. Se a carteira mudar depois da
prévia, a confirmação perde a validade. Antes de uma substituição bem-sucedida, o banco, seus
auxiliares e sua geração anteriores ficam preservados em **backups/pre-restore/**.
Se a carteira for restaurada mas a limpeza dos arquivos temporários falhar, a aplicação mostrará
o caminho da pasta privada `.restore-*` remanescente. Feche o aplicativo e remova essa pasta
manualmente depois de confirmar que a carteira restaurada está acessível.
O mesmo aviso aparece se a limpeza falhar durante a validação ou após uma restauração malsucedida.

Para recuperação manual, feche todas as janelas da aplicação, localize a pasta correspondente em
**backups/pre-restore/**, mova a versão atual para outro local e copie de volta o banco, o WAL/SHM e
o arquivo `.generation` preservados. Se existir o marcador oculto
**.nome-da-carteira.db.deleted**, remova-o somente depois de confirmar que a cópia recuperada é um
SQLite válido. A restauração não mescla registros nem escolhe automaticamente entre versões.

Bancos inválidos são ignorados na seleção. Se a carteira ativa for removida ou deixar de ser um
SQLite válido, a aplicação seleciona outra carteira disponível e recarrega suas configurações sem
reutilizar os dados de planejamento da anterior. Se nenhuma carteira válida existir, uma nova
carteira de recuperação é criada com outro nome e o arquivo inválido permanece intacto.

A exclusão de uma carteira local exige que o nome completo do arquivo seja digitado e nunca permite
remover a última carteira válida. A carteira a excluir é escolhida em um seletor próprio e não
precisa ser a carteira ativa. O banco e seus arquivos auxiliares SQLite são movidos para uma
pasta exclusiva em **backups/deleted-portfolios/**; esses backups não expiram nem são removidos
automaticamente. Para restaurar uma carteira, feche a aplicação e copie o banco e os auxiliares
preservados nessa pasta de volta para **database/**; remova também o marcador oculto
**.nome-da-carteira.db.deleted** correspondente. Bancos inválidos não podem ser removidos por esse
fluxo.

Se uma nova carteira reutilizar o nome de uma carteira excluída, as demais sessões abertas com esse
nome são reiniciadas antes de acessar o novo banco, evitando que dados mantidos em memória sejam
gravados na carteira substituta. Uma confirmação de exclusão já preenchida também perde a validade
quando a carteira selecionada é substituída e precisa ser digitada novamente.

Na primeira execução com o novo layout, a barra lateral oferece a importação de bancos
arquivos `.db` encontrados na antiga pasta `database/`, tanto ao lado da aplicação quanto em
pastas irmãs de releases anteriores chamadas `RendaPerene-v*`. Quando o mesmo nome existe em mais
de uma versão, a cópia válida mais recente é oferecida. A origem é mantida, uma cópia de recuperação
é criada em `backups/legacy-import/` e cada cópia é validada como SQLite antes de ficar disponível.
Repetir a operação é seguro e um arquivo existente com conteúdo diferente nunca é sobrescrito. Caso
o primeiro carregamento já tenha criado uma carteira principal somente com os valores padrão, a
publicação final aguarda as operações em andamento e verifica novamente se ela continua sem dados
do usuário. Caso positivo, ela pode ser substituída com segurança; qualquer dado ou configuração
alterada impede essa substituição. Quando já existe uma carteira diferente com o mesmo nome, a barra
lateral sugere um nome alternativo editável para importar e preservar as duas carteiras. O nome deve
ser um arquivo `.db` local ainda não utilizado; a conclusão fica associada ao destino escolhido para
que a carteira antiga não seja oferecida novamente. Após uma importação bem-sucedida, a carteira
importada é ativada e seus dados de planejamento são recarregados.

Uma carteira antiga desatualizada também pode ser marcada como **não oferecer novamente** sem ser
importada, movida ou excluída. A preferência local é vinculada ao conteúdo do arquivo: se a origem
mudar, ela volta a ser oferecida. A seção **Carteiras antigas ignoradas** permite desfazer a decisão.

Cada versão lê diretamente o catálogo `assets.csv` incluído no pacote. Uma nova versão pode
substituí-lo sem migração ou mesclagem com arquivos anteriores. Tickers ausentes do catálogo
continuam válidos quando aparecem em transações da carteira: o ticker permanece no banco local e a
interface apresenta metadados neutros sem criar uma entrada de catálogo. Cópias graváveis ou
catálogos legados deixados por versões anteriores são preservados no disco, mas ignorados.

O acesso à rede é necessário para obter dados atualizados:

- O Yahoo Finance (`yfinance`) fornece cotações da B3, indicadores de mercado, histórico de preços e dados de dividendos. Se uma cotação em tempo real não estiver disponível, a análise do ativo utiliza o último fechamento diário válido.
- O Banco Central do Brasil (BCB) fornece indicadores de IPCA, Selic e salário mínimo.
- O GitHub Releases é consultado uma vez por sessão para avisar sobre uma versão mais nova. A consulta não envia dados da carteira, não bloqueia a abertura da aplicação e só oferece o pacote publicado para Windows ou Ubuntu x64.

Os snapshots do Yahoo Finance são armazenados em cache sem dados da carteira. As correções anuais de
proventos permanecem no SQLite local, são relidas a cada análise e aplicadas antes do cálculo do
dividend yield histórico e do preço-teto de Bazin. Assim, trocar de carteira ou salvar uma correção
atualiza a análise seguinte sem enviar dados pessoais ao Yahoo nem limpar o cache remoto.

Consultas de mercado ocorrem em segundo plano: a carteira abre com dados locais e o último dado
remoto válido, inclusive após a expiração do cache ou uma falha de rede. No primeiro acesso,
campos dependentes de cotações mostram `N/D` até a resposta; patrimônio total, rentabilidade,
pesos e gráficos de composição aguardam cotações completas. Os indicadores econômicos usam
referências provisórias quando ainda não há resposta, identificadas na tela. A interface acompanha
as atualizações a cada dois segundos e mostra a idade dos dados usados.

Cotações e análises têm validade de 10 minutos, históricos de uma hora e indicadores econômicos
de 30 dias. O último dado válido também fica em um arquivo SQLite local e descartável na pasta
`cache` dos dados da aplicação. Ao reabrir, dados vencidos permanecem visíveis com sua idade
enquanto uma atualização ocorre em segundo plano. O arquivo não é uma carteira nem entra nos
backups; se estiver indisponível, a aplicação continua usando o cache em memória.
O botão de atualização do salário mínimo consulta o BCB sem bloquear a tela e mantém o valor
atual até receber uma resposta válida; somente essa resposta é salva no planejamento.
Para medir consultas remotas separadamente em desenvolvimento, use `APP_ENV=dev` e
`RENDA_PERENE_NAVIGATION_METRICS=true`. As métricas não contêm dados da carteira.

Posições e agregados locais reutilizam projeções temporárias, inclusive após reiniciar a aplicação.
Cada alteração relevante avança uma revisão interna do SQLite; por isso, dados de uma carteira,
ou de uma versão restaurada dela, não são reutilizados em outra. Essas projeções não substituem
o banco local nem alteram os backups. Em **Ativos → Carteira** e no **Raio-X**, gráficos,
históricos e indicadores detalhados aparecem automaticamente para o ativo selecionado.
Na Carteira, cada ticker tem uma aba; só o conteúdo da aba ativa é calculado.
As informações, gráficos e históricos aparecem automaticamente; os formulários **Registrar
movimentação** e **Meta anual deste ativo** ficam em blocos expansíveis e só são preparados
quando abertos.
A importação da B3 é iniciada pelo usuário: baixe a planilha oficial no Portal do Investidor da B3 e envie-a pela aplicação. Bancos locais e planilhas pessoais são ignorados pelo Git; não faça commit desses arquivos.

Entradas de aquisição ou subscrição com valor financeiro zero ou ausente ficam com
**custo pendente**. A quantidade permanece na carteira e o capital de custo já conhecido
continua visível, mas preço médio e rentabilidade ficam indisponíveis até a regularização em
**Ativos → Operações → Custos pendentes da B3**. Entradas de **Depósito** representam ações
recebidas e são registradas como compras a R$ 0,00, sem custo pendente.
Informe o preço unitário ou o valor total da aquisição, sem taxas, e acrescente as taxas
opcionais no campo separado. Consulte o comprovante da oferta, extrato financeiro,
nota/comprovante de liquidação ou declaração de IR. A aplicação não infere custos por
cotações históricas nem usa preços fixos por ativo.

O histórico de movimentações combina transações e proventos registrados na carteira ativa,
da data mais recente para a mais antiga, inclusive quando não há mais posições.
Em Operações, a consulta retorna páginas de até 25 registros. Os filtros por data inicial e final
(ambas inclusivas), evento e ticker podem ser combinados; sem seleção, incluem todo o histórico.
Os tickers incluem ativos já vendidos. Alterar filtros volta à primeira página; trocar de carteira
reinicia os filtros. Os botões **Anterior** e **Próxima** navegam pelos resultados, com indicação
da página e da quantidade encontrada. O histórico permanece integralmente salvo no banco local.
Todos os registros da página ficam visíveis na tabela, sem rolagem vertical interna.
A interação com o histórico atualiza somente essa seção, sem remontar os formulários de lançamento
e importação. Cada linha mostra data, evento, ticker, quantidade quando aplicável e valor em BRL. Compras incluem taxas;
vendas descontam taxas; proventos mostram o valor recebido. Desdobros, bonificações e grupamentos
têm valor financeiro zero; em grupamentos, a quantidade é o total final. Transferências de
custódia mostram **—** no valor, pois não representam dinheiro recebido. Aquisições sem custo
conhecido mostram **Custo pendente**. Eventos manuais sem distinção entre desdobro e bonificação
mantêm o rótulo conjunto. A lista é informativa e não altera aportes, patrimônio ou metas.
As linhas inteiras são destacadas por evento: compra em verde, venda em
vermelho, dividendo em azul, JCP em lilás, rendimento em laranja e os demais em roxo.
Os fundos usam tons suaves com texto escuro no tema claro e tons escuros com texto claro no
tema escuro, acompanhando o tema ativo da interface. Para proventos, a importação preserva
a quantidade e o preço unitário informados pela B3, sem recalcular o Valor da Operação.
O histórico usa essa quantidade; quando ela falta, mostra **Total ÷ Unitário** como quantidade
**estimada**, usando valores sem arredondamento prévio. Em registros antigos, o unitário é
calculado pela posição na data do pagamento, que pode diferir da quantidade remunerada.
Sem unitário válido nem histórico suficiente, a quantidade permanece como **—**.
Reimporte a planilha para completar os campos ausentes de proventos já registrados, sem duplicar
recebimentos nem alterar seus totais. Campos conhecidos são preservados; registros divergentes
ou correspondências antigas ambíguas não são complementados. A mensagem de importação conta
proventos adicionados ou complementados. **Proventos recebidos** e a métrica anual de proventos
por cota priorizam o preço unitário importado, depois o total dividido pela quantidade informada
e, na ausência desses metadados, a posição histórica na data do pagamento.
A migração automática adiciona campos opcionais ao banco local e mantém os registros
existentes; backups antigos continuam sendo aceitos e atualizados ao restaurar.

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

O histórico mensal e o acumulado de aportes usado na meta anual consideram **aportes líquidos**:
compras com taxas menos vendas líquidas de taxas. Vender R$ 10.000 e comprar R$ 10.000 no mesmo
mês, sem taxas, resulta em aporte líquido de R$ 0. Retiradas líquidas aparecem como valores
negativos e aumentam o valor restante para atingir a meta anual. Eventos de custódia ficam fora
desse cálculo; custos pendentes de negociação no período mantêm os totais indisponíveis até a
regularização.

Ao selecionar uma data de início do planejamento, o capital real acumulado nos gráficos inclui
o **Patrimônio Inicial** e os aportes líquidos registrados a partir da data escolhida. O valor
inicial pode ser calculado automaticamente ou informado manualmente, inclusive como zero.
No mês 0, os aportes planejados correspondem ao aporte mensal necessário e os proventos
planejados são zero. A curva de aportes planejados acumula apenas os aportes mensais; o patrimônio
inicial integra a base de cálculo dos proventos planejados a partir do mês 1. Proventos recebidos
antes da data permanecem fora do histórico.

Os gráficos de projeção acumulada a longo prazo e de aporte constante versus juros crescentes
mostram uma linha pontilhada **Hoje** na idade atual, além dos marcos de juros ou rendimentos
iguais ou superiores aos aportes.

Na Simulação Rápida, o patrimônio inicial aparece no ano zero da projeção acumulada, com
juros acumulados iguais a zero, e compõe a base de crescimento do patrimônio e dos rendimentos.
Também reduz o aporte mensal necessário. Os valores dessa simulação não alteram o plano salvo.

## Requisitos

- Python 3.10 a 3.14
- `pip`
- Acesso à rede apenas para consultar dados atualizados do Yahoo Finance ou do BCB

## Instalação

O Streamlit mínimo suportado é 1.55.0, necessário para abas com carregamento apenas da
aba ativa, `width="stretch"` nos componentes e `height="content"` no histórico de
movimentações. A instalação abaixo garante esse mínimo.
Para atualizar um ambiente existente, execute `python -m pip install --upgrade .`.

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

### Logging

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
própria; os dados persistentes ficam nos diretórios descritos em [Dados e privacidade](#dados-e-privacidade)
e não são incluídos nos artefatos.

## Arquitetura

A aplicação é dividida em três camadas:

- `core/`: infraestrutura de banco de dados, implementações de DAOs, portas, formatação, processamento de arquivos da B3 e integração de dados de mercado desacoplada da interface.
- `services/`: regras de carteira, planejamento e valuation independentes de framework.
- `views/`: telas e componentes de apresentação do Streamlit.

O `app.py` é a raiz de composição: inicializa a persistência, conecta os adaptadores de produção, prepara o estado da sessão e direciona para as telas Dashboard, Ativos e Planejamento. Consulte o [ARCHITECTURE.md](ARCHITECTURE.md) para conhecer o modelo de persistência, os limites entre dependências, as regras financeiras e as integrações.

## Licença

Este projeto é distribuído sob a [GNU Affero General Public License v3.0](LICENSE).
