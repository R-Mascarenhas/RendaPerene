# Issue #23: leitura da carteira

Contrato e design aprovados na conversa em 04/10/2026.

1. `core/portfolio_read.py`, `core/ports.py` e `core/daos/portfolio_dao.py`: definir
   resultados nomeados e carregar o ledger completo numa transação de leitura. Sem
   migração; conexões ficam no DAO. Verificar ordenação e isolamento com SQLite temporário.
2. `services/portfolio_read_service.py`: concentrar posições, resumo, holdings,
   detalhe, proventos e histórico atrás de quatro operações. Verificar taxas, vendas,
   eventos corporativos, custos pendentes, catálogo ausente e mercado incompleto.
3. `services/assets_service.py`, `services/planning_service.py`,
   `services/goals_service.py`, `services/share_quantity_goal_service.py` e `app.py`:
   migrar leituras e injeção; manter escritas e cálculos de aposentadoria em seus donos.
   Migrar regressões existentes e conferir capital inicial e metas.
4. `views/cached_market_data.py`, `views/dashboard_view.py`, `views/portfolio_view.py`,
   `views/planning_view.py` e widgets consumidores: renderizar resultados completos,
   sem mutação compartilhada. Cache local separado das cotações, com identidade,
   geração e revisão da carteira; filtros de período são aplicados após a recuperação
   do ledger. Verificar troca de carteira e invalidação após escrita.
5. `tests/conftest.py`, testes afetados, `README.md` e `ARCHITECTURE.md`: migrar
   contratos e documentação, revisar o diff completo e executar pytest, Ruff e
   formatação. Não acessar ou modificar bancos e planilhas pessoais.

## Arquivos da entrega

- Composição: `app.py`.
- Contratos e persistência: `core/portfolio_read.py`, `core/ports.py`,
  `core/daos/portfolio_dao.py`.
- Leituras: `services/portfolio_read_service.py`, `services/_portfolio_projection.py`.
- Serviços consumidores: `services/assets_service.py`, `services/planning_service.py`,
  `services/goals_service.py`, `services/share_quantity_goal_service.py`.
- Apresentação: `views/cached_market_data.py`, `views/dashboard_view.py`,
  `views/portfolio_view.py`, `views/planning_view.py`, `views/components/charts.py`,
  `views/components/detailed_holdings.py`, `views/components/patrimony_summary.py`.
- Testes: `tests/conftest.py`, `tests/test_portfolio_read.py`,
  `tests/test_accumulation_goals.py`, `tests/test_asset_detail_actions.py`,
  `tests/test_b3_parser.py`, `tests/test_b3_pending_costs.py`,
  `tests/test_dividend_receipt_metadata.py`, `tests/test_market_data.py`,
  `tests/test_market_data_cache.py`, `tests/test_net_contributions.py`,
  `tests/test_planning_service.py`, `tests/test_portfolio_activity.py`,
  `tests/test_portfolio_activity_view.py`, `tests/test_portfolio_service.py`,
  `tests/test_views.py`.
- Documentação: `README.md`, `ARCHITECTURE.md` e este plano.

As regressões de B3, custos pendentes, proventos, aposentadoria, metas e telas foram
migradas para os resultados da nova interface. Os três testes do cache antigo foram
substituídos por cenários com persistência isolada que exercitam recuperação em disco,
invalidação após escrita, atualização de cotações e isolamento por carteira e geração.
Os testes novos também cobrem leitura durante uma gravação concorrente, agregação de
tipos legados de recebimentos e correções da carteira na análise pública de mercado.

Não há migração de schema. A versão da chave do cache local foi alterada; os snapshots
são reconstruídos automaticamente. A revisão incluiu o diff completo e os cálculos
movidos para o módulo interno. Os testes novos foram mantidos como regressões duráveis.

## Validação final

- `venv/bin/pytest -q --tb=short`: 673 testes passaram.
- `venv/bin/pytest tests/test_portfolio_read.py tests/test_dividend_receipt_metadata.py -q --tb=short`:
  31 testes passaram.
- `venv/bin/ruff check .`: passou.
- `venv/bin/ruff format --check .`: passou, 85 arquivos formatados.
- `git diff --check`: passou.

As falhas intermediárias foram resolvidas: mocks da interface antiga foram migrados,
o cenário de gravação concorrente recebeu a importação de Pandas e o cenário de Bazin
usa um ticker sem correções pré-carregadas. O teste de recebimentos legados reproduziu
uma sobrescrita na agregação anual; a implementação agora acumula todos os tipos.

`venv/bin/streamlit run app.py` não foi executado para inspeção manual no navegador.
As telas e os reruns foram verificados pela suíte com AppTest e persistência isolada.
