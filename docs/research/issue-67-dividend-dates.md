# Issue #67: datas dos proventos e confirmação

Pesquisa realizada em 08/10/2026. Apenas investigação; nenhuma implementação.

## O que o yfinance fornece

O histórico `Ticker.dividends` usa **data-ex**, e não data-com nem data de pagamento. A discussão mantida no repositório do yfinance explicita essa distinção. O código de `get_dividends()` lê o histórico diário; `parse_actions()` transforma a data do evento Yahoo em índice e o valor em `Dividends`. Essa série não representa comprovantes de recebimento. Fontes: [discussão yfinance #568](https://github.com/ranaroussi/yfinance/issues/568), [history.py](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py), [utils.py](https://github.com/ranaroussi/yfinance/blob/main/yfinance/utils.py).

Existe uma alternativa limitada: `Ticker.calendar` pode expor `Dividend Date` e `Ex-Dividend Date`, quando o Yahoo envia esses campos. O código faz o mapeamento de campos singulares, sem fornecer uma agenda histórica por evento ou parcelas. Portanto, não resolve a associação entre cada lançamento histórico e seu pagamento. Não foi verificada a disponibilidade desses campos especificamente para CMIG4 nesta pesquisa. Fontes: [quote.py, `_fetch_calendar()`](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/quote.py), [discussão yfinance #568](https://github.com/ranaroussi/yfinance/issues/568).

O contrato dessa série também não separa JCP de dividendos, nem fornece um campo que declare bruto/líquido ou imposto retido. Não se deve inferir essas características somente do nome `Dividends`, nem tratar diferenças de arredondamento como prova de eventos distintos. Isso é uma limitação inferida da estrutura dos dados consumidos pelo adaptador, não uma afirmação de que todos os valores Yahoo são brutos ou líquidos. Fonte: [utils.py, `parse_actions()`](https://github.com/ranaroussi/yfinance/blob/main/yfinance/utils.py).

## Exemplo CMIG4 confirmado na fonte primária

O aviso da Cemig de 17/09/2026 informa:

| Campo | Informação |
| --- | --- |
| Tipo | JCP |
| Data-com | 22/09/2026 |
| Data-ex | 23/09/2026 |
| Valor bruto total por ação | R$ 0,06991340114 |
| Pagamento | Duas parcelas iguais: primeira até 30/06/2027; segunda até 30/12/2027 |

Cada parcela corresponde, por divisão do valor declarado, a **R$ 0,03495670057 bruto por ação**, compatível com os oito decimais mencionados pelo usuário. As duas parcelas compartilham data-com e valor; não são duplicatas. O aviso usa prazos “até”, portanto essas datas não comprovam que o dinheiro já foi recebido. Fonte: [aviso oficial da Cemig](https://ri.cemig.com.br/docs/Aviso-aos-Acionistas-Cemig-2026-09-17-jPMwLQ66.pdf). O [histórico oficial](https://ri.cemig.com.br/informacoes-financeiras/dividendos) também distingue record, ex e pagamentos.

## Consequências para a decisão de produto

Recomendação de desenho, sujeita à especificação da issue: detecção deve produzir uma proposta para confirmação, sem criar automaticamente um recebimento. Mostrar a natureza de cada data e manter separados anúncio/direito, parcelas previstas e recebimento confirmado.

A prioridade da importação B3 é requisito do usuário. Deve-se aplicá-la preservando a semântica do relatório importado. A B3 oferece posição, movimentações e proventos na Área do Investidor; não há fundamento nesta pesquisa para generalizar que toda coluna de data de todos os seus relatórios seja data-com. A definição exata depende do relatório e cabeçalho fornecidos. Fonte: [descrição oficial da Área do Investidor](https://borainvestir.b3.com.br/objetivos-financeiros/organizar-as-contas/o-que-e-a-area-do-investidor-da-b3/).

Na reconciliação, igualdade de ticker/data/valor não basta para decidir duplicidade, como mostram as parcelas Cemig. Quando não houver identificação segura do evento e da parcela, apresentar os registros ao usuário e pedir que confirme a associação; depois, os dados B3 prevalecem sobre a estimativa Yahoo. Esta é uma recomendação derivada do exemplo confirmado e do requisito de prioridade, não uma garantia fornecida pelo yfinance.
