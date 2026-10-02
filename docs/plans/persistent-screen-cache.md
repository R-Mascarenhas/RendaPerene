# Cache persistente das telas

Contrato aprovado em conversa: Ativos e Dashboard devem recuperar resultados válidos
depois de reiniciar a aplicação, indicar a idade de dados remotos vencidos e atualizar
estes em segundo plano. Projeções locais nunca substituem o SQLite da carteira.

## Implementação

1. `core/application_paths.py`, `core/ports.py`, `core/screen_cache.py`:
   criar um arquivo SQLite descartável fora de `database/` e um módulo de leitura/gravação
   com esquema versionado, JSON tipado, integridade, limite de tamanho e falha aberta.
   Testar reabertura, corrupção, permissões e isolamento em `tests/test_screen_cache.py`.
2. `core/market_data_cache.py`, `views/cached_market_data.py`, `app.py`:
   hidratar o cache remoto compartilhado do arquivo e persistir somente respostas
   válidas concluídas; manter refresh e falhas sem bloquear a interface. Testar TTL,
   dados vencidos, concorrência e reinício em `tests/test_market_data_cache.py`.
3. `views/cached_market_data.py` e telas consumidoras: recuperar as projeções locais
   preparadas por `AssetService` com chave incluindo identidade/geração/revisão da
   carteira, parâmetros, catálogo e data. Resultados que combinam carteira e mercado
   continuam nos serviços a partir das fontes válidas, sem salvar composição parcial.
   Testar troca, alteração, restauração e ausência de dados em `tests/test_views.py`.
4. `views/portfolio_view.py`, `views/asset_deep_dive_view.py`:
   mostrar automaticamente gráficos, históricos e indicadores do ticker selecionado.
   Adiar somente formulários de edição. Testar a visibilidade automática e que
   formulários fechados não executam cálculos em `tests/test_views.py`.
5. `README.md`, `ARCHITECTURE.md`: explicar localização, descarte, idade, atualização
   e privacidade. Rodar testes relevantes, suíte completa e Ruff; revisar todo o diff.

O cache não entra em backups, não migra dados pessoais e pode operar somente em memória
se o arquivo não estiver disponível. O esquema de cache é reconstruível e incompatibilidades
de versão são ignoradas, sem migração da carteira.
