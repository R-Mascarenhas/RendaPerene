# RendaPerene

O RendaPerene acompanha uma carteira de investimentos brasileira e usa referências de mercado
sem confundi-las com os registros financeiros pertencentes ao usuário.

## Linguagem

**Catálogo de ativos**:
Referência versionada de tickers conhecidos e seus metadados descritivos. Não contém dados da
carteira nem incorpora informações criadas pelo usuário.
_Evitar_: Catálogo pessoal, cadastro de ativos da carteira

**Ticker da carteira**:
Identificador de um ativo mencionado pelos registros financeiros da carteira. Sua validade não
depende de existir no catálogo de ativos.
_Evitar_: Entrada do catálogo

**Ativo não catalogado**:
Ativo cujo ticker pertence à carteira, mas não aparece no catálogo de ativos da versão atual. Seus
metadados neutros servem apenas para apresentação e não representam informações oficiais.
_Evitar_: Ativo inválido, ativo alternativo
