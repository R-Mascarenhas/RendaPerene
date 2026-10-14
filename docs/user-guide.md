# Guia de uso do RendaPerene

Este guia reúne as funcionalidades e os procedimentos de carteira, planejamento,
importação e recuperação. Para instalar e iniciar o aplicativo, consulte o
[README](../README.md).

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

O seletor de ativos nas operações manuais prepara o catálogo em uma única passagem, inclusive
quando há códigos repetidos. No detalhamento da carteira, **Registrar movimentação** usa o
ticker do ativo exibido e dispensa a preparação da lista completa de ativos.

Os editores de metas na tabela e no detalhamento compartilham a meta salva. Se uma edição
falhar, a apresentação volta ao último alvo salvo e permite tentar novamente; o erro desaparece
após uma gravação bem-sucedida. Salvar em um editor atualiza o outro na próxima renderização.
Movimentações manuais, importações da B3, regularização de custos, troca de carteira e
restauração descartam os estados derivados dos editores.

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

O **backup opcional no Google Drive** permite conectar sua conta Google, escolher carteiras
para backup automático e recuperar cópias em outro computador. Cada máquina atualiza seu próprio
arquivo na pasta visível `RendaPerene`, a cada 10 minutos enquanto a aplicação estiver aberta.
Salvar a seleção com o backup ativado autoriza os envios, inclusive após reiniciar a aplicação.
As cópias disponíveis para recuperação podem ser ignoradas sem bloquear o backup automático.
Alterar ou substituir um arquivo remoto provoca novo envio para reparar a cópia desta máquina.
O pacote inclui o banco completo da carteira, com pagamentos e decisões sobre proventos.

A recuperação pede confirmação: para uma carteira ainda não instalada, escolha entre substituir
uma carteira local (inclusive a Principal) ou criar uma nova. A substituição preserva uma cópia
anterior em `backups/pre-restore`. A aplicação não mescla alterações entre computadores.

O pacote `.rpbc` usa a proteção padrão do Drive, sem senha ou criptografia própria do RendaPerene:
o Google e quem tiver acesso ao arquivo podem ler os dados. Os tokens ficam no cofre do sistema;
sem cofre ou configuração OAuth, o uso e os backups locais continuam disponíveis.

Consulte o [guia do Google Drive](google-drive-setup.md) para conexão, configuração das
releases e diagnóstico. As escolhas de segurança e funcionamento estão na
[ADR-0001](adr/0001-optional-google-drive-backup.md).

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
as atualizações a cada dois segundos e mostra a idade dos dados usados. Cada sessão acompanha
os pedidos da tela atual, incluindo respostas concluídas durante sua preparação; falhas permitem
nova tentativa automática após o intervalo de espera existente.

Cotações e análises têm validade de 10 minutos, históricos de uma hora e indicadores econômicos
de 30 dias. O último dado válido também fica em um arquivo SQLite local e descartável na pasta
`cache` dos dados da aplicação. Ao reabrir, dados vencidos permanecem visíveis com sua idade
enquanto uma atualização ocorre em segundo plano. O arquivo não é uma carteira nem entra nos
backups; se estiver indisponível, a aplicação continua usando o cache em memória.
O botão de atualização do salário mínimo consulta o BCB sem bloquear a tela e mantém o valor
atual até receber uma resposta válida; somente essa resposta é salva no planejamento da carteira
solicitante. Editar o valor manualmente, trocar de carteira ou restaurá-la cancela a atualização
pendente, sem limpar os dados remotos compartilhados.
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
A importação da B3 é iniciada pelo usuário: baixe a planilha oficial no Portal do Investidor da B3 e envie-a pela aplicação. Quando houver operações manuais do mesmo ticker, tipo e data cuja quantidade total e média ponderada correspondam à linha consolidada da B3, a aplicação pede confirmação se a data B3 estiver dois a seis dias corridos depois, ou na mesma data quando a planilha explicitar o negócio. A instituição B3 aparece como referência para a decisão. Cada sugestão começa sem seleção: escolha o lançamento existente ou **Importar como nova operação** em todas as linhas antes de confirmar. O botão permanece desabilitado enquanto houver escolhas pendentes ou um lançamento manual repetido entre linhas. Os lançamentos, datas e taxas individuais são preservados na conciliação; a data da planilha fica no registro de origem da importação. Ao escolher importar como nova, a linha B3 entra como operação separada com a data informada pela B3. Bancos locais e planilhas pessoais são ignorados pelo Git; não faça commit desses arquivos.

Durante a revisão, alterar uma escolha atualiza apenas o bloco de importação e reutiliza a
planilha e as sugestões já preparadas. Se o arquivo ou a carteira mudar, as sugestões são
renovadas e as escolhas anteriores são limpas. Todos os vínculos são revalidados ao confirmar.
Quando várias linhas da B3 podem ser conciliadas sem reutilizar lançamentos manuais, as opções
preservam uma combinação compatível entre essas linhas. Você continua escolhendo cada uma
individualmente, sem seleção automática.

Se houver combinações demais para concluir a comparação com segurança, a aplicação interrompe
a importação e pede a revisão dos lançamentos. Nenhuma linha dessa planilha é gravada nesse caso.

Sugestão e confirmação usam a mesma política de compatibilidade. Ao confirmar, a aplicação
relê os lançamentos sob bloqueio SQLite e rejeita escolhas que deixaram de corresponder à
linha B3 ou já foram vinculadas. Cada linha é gravada atomicamente; se uma linha posterior
falhar, as anteriores permanecem gravadas e a reimportação não as duplica.

Os lançamentos manuais conciliados mantêm a origem `MANUAL`; o vínculo com a B3 registra a
confirmação da importação. Ao abrir a carteira, a aplicação corrige a origem das operações que
foram marcadas como `B3` pela versão anterior e possuem esse vínculo, preservando datas e valores.

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
Movimentos de proventos classificados como **Transferido**, como **Juros Sobre Capital Próprio -
Transferido**, representam transferência do direito entre instituições e são ignorados na
importação: não geram recebimentos nem alteram a posição em ações. Pagamentos de dividendos,
JCP e rendimentos continuam sendo importados normalmente. O filtro vale para novas importações;
registros antigos não são removidos automaticamente, pois não preservam a descrição original
necessária para identificar esses movimentos com segurança.
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

### Detectar proventos e informar pagamentos

Ao abrir a carteira, o aplicativo verifica novos proventos em segundo plano, sem bloquear a
navegação, e mostra um aviso com os ativos
encontrados acima da navegação. Abra **Detectar proventos e informar pagamentos** para revisar.
A verificação é reutilizada durante a sessão e repetida ao mudar o dia ou a carteira, ou após
uma alteração nos registros. Para consultar novamente, clique em **Buscar proventos no Yahoo
Finance**. Falhas do Yahoo são informadas apenas para ativos com posição atual positiva e não
impedem usar a carteira offline. A consulta apresenta apenas
sugestões: a data do Yahoo é a **data-ex**, e não a data-com ou a data de pagamento. O Yahoo
também não distingue JCP de dividendos nem informa as parcelas ou os impostos de cada crédito.
Eventos já confirmados ou ignorados não aparecem novamente. Possíveis correspondências com
pagamentos cadastrados também são omitidas da análise, sem aviso de duplicidade nem gravação
de uma decisão. O filtro considera o mesmo ativo, pagamento igual ou posterior à data-ex e
valor por ação compatível, inclusive parcelas, valores líquidos e arredondamento. Como esses
indícios não comprovam a identidade do evento, o filtro pode ocultar eventos distintos; os
pagamentos existentes são preservados. Eventos sem correspondência continuam disponíveis para
confirmação ou para ignorar. A aba de detecção aparece somente quando há eventos pendentes. O botão
**Buscar proventos no Yahoo Finance** permanece disponível após uma busca vazia ou uma falha,
permitindo consultar novamente eventos publicados durante o dia.

Confirme o tipo, a quantidade remunerada, o valor por ação de cada parcela e suas datas de
pagamento. A quantidade histórica é uma sugestão; confira seus comprovantes, inclusive quando
houver desdobramentos ou transferência de custódia. Você pode corrigir o valor por ação para
representar o crédito líquido. Use **Revisar parcelas**, confira os totais arredondados em
centavos e escolha **Confirmar e salvar pagamentos**. Se o pagamento já estiver cadastrado,
associe-o para evitar duplicidade; seus valores existentes serão preservados. Também é possível
ignorar um evento. As decisões são preservadas na carteira, inclusive depois de fechar o app.

Datas futuras aparecem como **JCP - a receber**, **Dividendo - a receber** ou **Rendimento - a
receber** nas movimentações e no detalhe do ativo. Esses valores não entram nos recebidos do
ano, últimos 12 meses, YoC, preço ajustado, histórico ou meta de reinvestimento. Na data
informada, passam automaticamente a recebidos, sem confirmação adicional do crédito. Se houver
adiamento, use **Ajustar data de pagamento de provento cadastrado** em **Ativos → Operações**;
o ajuste mantém quantidade
e valor. A classificação é refeita nas leituras, usando o dia local, sem gravar um novo status.

Ao importar a B3, possíveis correspondências com parcelas cadastradas exigem uma escolha:
associar ao pagamento existente ou importar separadamente. Pagamentos confirmados a partir do
Yahoo também são oferecidos quando o tipo informado pela B3 difere do confirmado. A associação
aplica o tipo, a data, o total
e os metadados disponíveis da B3 à parcela escolhida, sem criar outro recebimento. Cada parcela
só pode ser associada a uma linha da mesma importação. Alterações da carteira durante a revisão
exigem conferir novamente. Mudanças posteriores do Yahoo não sobrescrevem pagamentos confirmados;
falhas de consulta são informadas e não impedem o uso offline da carteira.

Este fluxo reutiliza as tabelas existentes, sem nova migração. A data-ex e o valor original
ficam no registro de origem; `dividends.date` guarda exclusivamente a data de pagamento
confirmada pelo usuário ou informada pela B3. Os eventos do Yahoo não alimentam diretamente
os totais financeiros da carteira.

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

Sem operações e sem uma data de início escolhida, o planejamento usa a data de hoje e exibe
**Planejamento iniciado Hoje**. Os prazos e aportes são recalculados a partir do dia atual até
o registro de uma operação; depois, o início automático usa a primeira data do histórico.
Uma data de início escolhida manualmente continua sendo respeitada.

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

O plano salvo e a Simulação Rápida usam o mesmo cálculo de anuidade antecipada e a mesma
estrutura de resultados. A tela encaminha uma configuração única ao módulo de planejamento,
que também prepara os dados dos gráficos e consulta o capital anterior pelo provedor da carteira.
Os campos continuam mantendo seus valores na sessão, e a Simulação Rápida não substitui o aporte
do plano salvo usado pelos demais indicadores. As leituras reutilizam o ledger em memória,
renovado quando mudam os dados, a carteira ou sua geração; os cálculos financeiros usam sempre
as entradas atuais. Essa organização não exige migração dos bancos existentes.
