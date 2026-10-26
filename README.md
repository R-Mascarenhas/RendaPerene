# 💼 RendaPerene

Aplicativo local para acompanhar uma carteira de investimentos brasileiros (B3) e
planejar a aposentadoria. Permite registrar operações, importar arquivos da B3,
acompanhar proventos e simular aportes e metas.

A interface é em português e abre no navegador do próprio computador. As carteiras
ficam em bancos SQLite locais, sem conta obrigatória ou telemetria. O backup no
Google Drive é opcional.

Os parâmetros de avaliação de Bazin podem ser editados preservando as configurações do
planejamento. A busca de proventos começa automaticamente ao abrir o aplicativo e ocorre em
segundo plano, sem botão de busca manual; cadastrar pagamentos exige revisão e confirmação explícita.
Ao confirmar ou ignorar um evento, a revisão segue pelos proventos já encontrados, sem repetir
a consulta ao Yahoo Finance.

Nos lançamentos manuais de compra e venda, escolher o ativo e a data busca o fechamento
diário do Yahoo Finance em segundo plano, sem bloquear a página. O preço continua editável;
uma resposta da consulta não substitui o valor digitado. Sem cotação, informe o preço
manualmente. O valor de hoje pode ser provisório e o histórico pode refletir ajustes por
desdobramentos feitos pelo Yahoo: confirme sempre o preço da sua negociação.

## Instalar o aplicativo

Baixe a versão mais recente nas
[releases](https://github.com/R-Mascarenhas/RendaPerene/releases/latest):

- **Windows 10 ou posterior, 64 bits:** pacote `.zip`.
- **Ubuntu 22.04 ou posterior, 64 bits:** pacote `.tar.gz`.

Extraia o pacote em uma pasta própria e execute o aplicativo dentro dela. Os pacotes
incluem o ambiente necessário, sem exigir instalação separada de Python.

É necessário um navegador. Consultas de mercado, verificação de atualizações e backup
no Drive precisam de internet; seus registros continuam locais.

## Executar pelo código-fonte

Requisitos: **Python 3.10 a 3.14**, `pip` e Git para clonar o repositório.
As dependências, incluindo Streamlit, são instaladas pelo comando abaixo.

```bash
git clone https://github.com/R-Mascarenhas/RendaPerene.git
cd RendaPerene
```

No Linux:

```bash
python3 -m venv venv
venv/bin/python -m pip install .
venv/bin/streamlit run app.py
```

No Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install .
.\venv\Scripts\streamlit.exe run app.py
```

Na primeira execução, o aplicativo inicializa a carteira no diretório de dados do
usuário. Novas versões usam esse mesmo diretório.

## Documentação

- [Guia de uso, dados e backups](docs/user-guide.md).
- [Backup opcional no Google Drive](docs/google-drive-setup.md).
- [Desenvolvimento e validação](docs/development.md) e [arquitetura](ARCHITECTURE.md).
- [Publicação de releases](docs/release.md).
- [Site público e configuração do GitHub Pages](docs/github-pages-setup.md).

## Licença

Distribuído sob a [GNU Affero General Public License v3.0](LICENSE).
