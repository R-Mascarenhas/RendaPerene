# Site público no GitHub Pages

O site da [issue #102](https://github.com/R-Mascarenhas/RendaPerene/issues/102) fica em
`site/`: apresentação, política de privacidade e termos em HTML/CSS, com uma ilustração
SVG de dados fictícios. Não exige compilação, JavaScript, serviços de login ou recursos
externos para renderizar. O aplicativo continua executando localmente.

## Revisão e visualização local

Na raiz do repositório:

```bash
venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory site
```

Abra `http://127.0.0.1:8000/`. Confira as três páginas em larguras de 320, 375, 768 e
1280 pixels, zoom de 200%, Tab/Shift+Tab, foco visível e o link Pular para o conteúdo.
Os gráficos são ilustrativos; não gere imagens a partir de carteiras pessoais.

```bash
venv/bin/pytest tests/test_public_site.py -q
venv/bin/pytest
venv/bin/ruff check .
venv/bin/ruff format --check .
```

Os testes verificam links internos, âncoras, recursos locais e limites dos arquivos a
publicar. Eles não comprovam contraste, layout no navegador ou disponibilidade pública.
O workflow executa os testes do site com `--noconftest`, sem inicializar os adaptadores
e bancos do aplicativo e instalando apenas pytest.

## Habilitar publicação

1. Em **Settings → Pages → Build and deployment**, selecione **GitHub Actions**.
2. Confira o ambiente **github-pages** e suas regras de publicação. Permita deploy
   somente a partir de `main`; preserve revisões obrigatórias se o repositório as usar.
3. Integre a mudança na `main`. O workflow **Public website** valida os documentos,
   envia somente `site/` como artefato e publica. PRs executam apenas a validação.
   Para repetir um deploy, use **Actions → Public website → Run workflow**, na `main`.
4. Aguarde o sucesso do job de deploy e consulte o endereço do ambiente. O endereço
   padrão esperado é `https://r-mascarenhas.github.io/RendaPerene/`; confirme o endereço
   efetivo em Settings → Pages antes de usá-lo em outros serviços.
5. Verifique em janela anônima, sem login:

   | Página | Endereço inicial esperado |
   | --- | --- |
   | Inicial | `https://r-mascarenhas.github.io/RendaPerene/` |
   | Privacidade | `https://r-mascarenhas.github.io/RendaPerene/privacidade.html` |
   | Termos | `https://r-mascarenhas.github.io/RendaPerene/termos.html` |

O deploy usa o token temporário do GitHub Actions: leitura do repositório, `pages: write`
e `id-token: write` somente no job de publicação. Não exige PAT ou credenciais pessoais
versionadas. Falhas aparecem no workflow; não anuncie publicação antes do sucesso e da
conferência HTTPS. O site não publica código Python, documentos internos, carteiras,
planilhas nem configuração OAuth.

## Domínio próprio, DNS e HTTPS

Escolha e aquisição do domínio são decisões do mantenedor. Não existe domínio definitivo
configurado nesta entrega, e não há `CNAME` com valor provisório.

1. Adquira o domínio e mantenha acesso administrativo à zona DNS. Antes de apontar os
   registros, [verifique o domínio na conta GitHub](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages)
   usando o TXT fornecido pelo GitHub, para reduzir o risco de tomada do domínio.
2. Em Settings → Pages → **Custom domain**, informe o hostname escolhido. Para este
   workflow, a configuração do domínio é feita em Settings; o artefato não depende de
   arquivo `CNAME`. Se mudar futuramente para publicação por branch, siga as regras de
   `CNAME` dessa modalidade.
3. Para um subdomínio, crie um registro DNS `CNAME` apontando para
   `r-mascarenhas.github.io`, sem `/RendaPerene/`. Para o domínio raiz, use os registros
   `A`/`AAAA` ou `ALIAS`/`ANAME` recomendados na
   [documentação atual do GitHub](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).
   Consulte os valores oficiais na configuração; não use registros wildcard.
4. Aguarde a propagação, a verificação DNS e a emissão do certificado. Ative **Enforce
   HTTPS** quando disponível. Confira as três páginas, os recursos e os links no novo
   endereço, sem depender de redirecionamentos para outro domínio.
5. Antes de abandonar a hospedagem ou mover o repositório, remova os apontamentos DNS
   que ficarem sem destino e ajuste a configuração de domínio.

Os links relativos das páginas funcionam no subdiretório inicial e na raiz do domínio.
O site não inventa URLs canônicas ou contatos para um domínio ainda não escolhido.

## Comprovação no Google e cadastro OAuth

O domínio próprio verificado é a direção prevista para a configuração definitiva.
O endereço do repositório ou o deploy inicial no Pages não substituem a comprovação de
propriedade exigida pelo Google. Confira os
[requisitos da página inicial](https://support.google.com/cloud/answer/13807376?hl=en)
e as [opções de Branding](https://support.google.com/cloud/answer/15549049?hl=en)
vigentes antes de submeter o aplicativo.

1. No [Google Search Console](https://search.google.com/search-console), adicione uma
   propriedade do tipo **Domínio** para o domínio adquirido. Publique o TXT fornecido
   pelo Google no DNS e confirme a propriedade. Preserve o registro. Use uma conta
   com acesso apropriado ao projeto OAuth e ao domínio.
2. No **Google Auth Platform → Branding**, configure RendaPerene e um e-mail de suporte
   monitorado que esteja entre as opções aceitas pelo Google (conta ou grupo autorizado).
   O contato público pelo GitHub Issues não substitui esse campo. Informe também o
   e-mail de contato do desenvolvedor quando solicitado.
3. Cadastre o domínio registrável em **Authorized domains**. Preencha os links com o
   endereço HTTPS definitivo, exatamente como aparece no navegador:

   | Campo | Valor a preencher |
   | --- | --- |
   | Application home page | URL pública da página inicial no domínio escolhido |
   | Application privacy policy link | URL pública terminada em `/privacidade.html` |
   | Application terms of service link | URL pública terminada em `/termos.html` |

4. Abra esses links sem login e confirme que a política está visível na página inicial
   e corresponde à versão distribuída. Não use links encurtados ou URLs que redirecionem
   para outro domínio. Mantenha os mesmos links na tela de consentimento e no site.
5. Preserve o cliente OAuth **Desktop app**, o escopo `drive.file` e o retorno loopback
   do aplicativo. O site não é um servidor de callback OAuth e não recebe tokens.
   Continue a configuração pelo [guia do Drive](google-drive-setup.md).

A aprovação do aplicativo pelo Google não é automática e não é comprovada pelo deploy.
Termos são incluídos nesta entrega independentemente das diferenças entre os guias
quanto à obrigatoriedade desse link.

## Checklist antes do domínio definitivo

- Revisar os textos com o comportamento da release, incluindo `.rpb` versus `.rpbc`,
  cofre, exclusão de cópias e integrações. Confirmar licença e data das páginas.
- Confirmar contato público com o mantenedor. O site usa o perfil e as issues reais;
  se for adotado um e-mail público, atualizar as três páginas sem inventar endereços.
- Preencher os contatos obrigatórios no Google Auth Platform; não publicar credenciais.
- Conferir domínio final, DNS, HTTPS e propriedade no GitHub e Search Console.
- Conferir todas as URLs públicas e releases em sessão sem login, em tela pequena e
  usando teclado. Remover qualquer placeholder introduzido durante a configuração.
- Registrar URL, commit publicado, data e resultados. Até isso acontecer, o aceite
  de disponibilidade pública HTTPS permanece pendente.

## Fontes oficiais

- [Workflow do GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
- [HTTPS no Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https).
- [Verificação no Search Console](https://support.google.com/webmasters/answer/9008080?hl=pt-BR).
- [Privacidade do GitHub](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

Referências consultadas em 14/10/2026. A hospedagem pode tratar registros técnicos de
visitas; a ausência de telemetria do aplicativo não significa ausência desses registros.
