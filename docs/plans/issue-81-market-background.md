# Issue #81: atualização de mercado em segundo plano

Contrato e desenho aprovados na conversa. A leitura de mercado na interface retorna o último
dado válido ou indica indisponibilidade imediatamente; somente tarefas de background consultam
as fontes remotas. A pedido do usuário, respostas válidas e projeções locais também são guardadas
no cache SQLite descartável descrito em `persistent-screen-cache.md`, separado da carteira.

1. `core/market_data_cache.py`: cache limitado, TTL, deduplicação, fila limitada, resultados
   copiados, estado consultável e descarte de respostas invalidadas. Verificar pela interface
   pública em `tests/test_market_data_cache.py` usando relógio e fontes controlados.
2. `core/ports.py`, `core/utils/market_data.py`, `core/performance.py`: contratos de atualização,
   distinção entre falha e resultado válido e métricas sanitizadas. Preservar os fallbacks dos
   consumidores headless existentes; testar falhas e validação de indicadores.
3. `views/cached_market_data.py`, `app.py`: recurso compartilhado e protegido para dados remotos;
   preservar caches locais. Testar cache frio/quente, normalização e isolamento de correções.
4. `services/market_analysis_service.py`, `services/assets_service.py`: agendar snapshots em lote,
   combinar correções somente na thread da aplicação e sinalizar métricas incompletas. Verificar
   cálculos conhecidos e ausência de cotações sem produzir patrimônio zero artificial.
5. `views/dashboard_view.py`, `views/components/patrimony_summary.py`,
   `views/components/detailed_holdings.py`, `views/planning_view.py` e apresentação de status:
   atualização da tela na thread Streamlit e atualização manual do salário mínimo somente após
   resposta válida. Verificar navegação e renderização com consultas remotas bloqueadas.
   `core/utils/session.py` cancela solicitações pendentes na troca/restauração de carteira;
   uma edição manual posterior do salário mínimo prevalece sobre uma resposta em background.
6. `README.md`, `ARCHITECTURE.md`: documentar TTL, atualização, diagnóstico e limites. Executar
   testes relevantes, suíte completa, Ruff e formatação; revisar o diff completo.

Sem migração, escrita em dados pessoais ou alteração automática dos parâmetros persistidos do
planejamento. Workers não acessam banco, sessão ou UI. Medir I/O controlado antes de definir o
paralelismo; manter limites conservadores e não adicionar um backend separado.

## Entrega e validação

Arquivos alterados:

- Cache e fonte remota: `core/market_data_cache.py`, `core/background_market_data.py`,
  `core/ports.py`, `core/utils/market_data.py`.
- Composição e sessão: `app.py`, `core/utils/session.py`, `views/cached_market_data.py`,
  `views/market_data_status.py`.
- Serviços: `services/assets_service.py`, `services/market_analysis_service.py`.
- Apresentação: `views/components/charts.py`, `views/components/detailed_holdings.py`,
  `views/components/patrimony_summary.py`, `views/planning_view.py`.
- Testes: `tests/conftest.py`, `tests/test_market_data.py`, `tests/test_market_data_cache.py`,
  `tests/test_views.py`.
- Documentação: `README.md`, `ARCHITECTURE.md` e este plano.

Validação final: `venv/bin/pytest` (636 testes passaram), `venv/bin/ruff check .`,
`venv/bin/ruff format --check .` e `git diff --check` sem erros.
O Dashboard e a atualização do salário mínimo foram exercitados com AppTest e fontes controladas.
Não foi executada uma sessão manual de `streamlit run app.py`, para não inicializar ou migrar
bancos pessoais. Falhas intermediárias de isolamento dos testes foram corrigidas antes da suíte final.
