# Issue #24 — cenários de planejamento

Especificação e desenho aprovados na conversa: concentrar configuração, cálculo e
projeções no planejamento, mantendo a anuidade antecipada, a interface em PT-BR,
o sandbox em memória e a reutilização do ledger em cache.

1. `core/planning.py`: definir configuração, entrada de cenário, resultado compatível
   com as chaves atuais e datasets de projeção. Sem alteração de schema.
   Verificação: paridade dos resultados pelo contrato público.
2. `services/planning_service.py`: salvar uma configuração coesa, normalizar datas,
   consultar capital anterior pelo provedor injetado e compartilhar o cálculo entre
   `get_current_simulation()` e o sandbox. Preparar datasets dentro do módulo.
   Preservar chamadas legadas, parâmetros de valuation e regras de custos pendentes.
   Verificação: testes em `tests/test_planning_service.py` e
   `tests/test_planning_scenarios.py`, com adaptadores injetados e banco isolado.
3. `views/planning_view.py` e `views/components/projection_chart.py`: consumir os
   modelos/resultados e renderizar o sandbox por método público. Manter estado de
   widgets, cache do aporte salvo e cache do ledger com identidade, geração e revisão.
   Verificação: `tests/test_views.py` e regressões do cache em
   `tests/test_portfolio_read.py` e `tests/test_screen_cache.py`.
4. `ARCHITECTURE.md` e `README.md`: documentar os casos de uso e o comportamento
   de memória/cache, sem afirmar que as projeções financeiras já possuem cache.
5. Revisar o diff completo, executar a suíte completa, Ruff e formatação.

Não modificar bancos pessoais, planilhas ou artefatos gerados. Não adicionar integrações.
