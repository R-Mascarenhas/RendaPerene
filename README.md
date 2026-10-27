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

- **Windows 10 ou posterior, 64 bits:** instalador `.exe`.
- **Ubuntu 22.04 ou posterior, 64 bits:** pacote `.deb`.

No Windows, execute o instalador. O destino sugerido é
`%LOCALAPPDATA%\Programs\RendaPerene`, sem exigir administrador; você pode escolher outra pasta.
Use o atalho criado no menu Iniciar ou, opcionalmente, na área de trabalho. Para atualizar,
feche o aplicativo e execute o novo instalador: ele reutiliza a pasta escolhida e mantém os
mesmos atalhos, preservando carteiras, configurações e backups.

No Ubuntu, instale o `.deb` pelo gerenciador de aplicativos ou pelo terminal:

```bash
sudo apt install ./RendaPerene-vX.Y.Z-ubuntu-x64.deb
```

Abra **RendaPerene** no menu de aplicativos ou execute `rendaperene` no terminal, sem `sudo`.
Para atualizar, feche o aplicativo e instale o novo `.deb` da mesma forma: a entrada no menu e
os dados são preservados. A instalação usa `/opt/rendaperene`, gerenciada pelo sistema.
As distribuições incluem o ambiente necessário, sem exigir instalação separada de Python.

Se você usa um ZIP ou TAR.GZ antigo, baixe o primeiro instalador manualmente nas releases:
o aviso das versões antigas procura apenas os formatos anteriores. Depois, passe a usar o
atalho da instalação; uma cópia antiga do executável continuará abrindo a versão antiga.

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
