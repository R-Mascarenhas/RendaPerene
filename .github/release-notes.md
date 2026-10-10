## Novidades em 0.12.0

- Em **Ativos → Operações**, proventos detectados no Yahoo Finance passam por confirmação
  antes de entrar na carteira. A data do Yahoo é apresentada como data-ex; você confere o tipo,
  a quantidade remunerada, o valor por ação e as datas de pagamento de cada parcela antes de salvar.
  Também é possível associar um pagamento existente ou ignorar o evento, preservando as decisões
  na carteira. Novas consultas ficam disponíveis pelo botão **Buscar proventos no Yahoo Finance**.
- Pagamentos com datas futuras aparecem como **a receber** e só entram nos indicadores de
  proventos recebidos na data informada. Se houver adiamento, a data pode ser ajustada em
  **Ativos → Operações**, mantendo a quantidade e o valor cadastrados.
- A importação da B3 permite associar proventos a parcelas já cadastradas, inclusive pagamentos
  confirmados a partir do Yahoo com tipo diferente. A associação atualiza os dados da parcela
  com as informações da B3, evitando um novo recebimento. Transferências de direitos a proventos
  entre custodiantes deixam de ser tratadas como pagamentos.
- O planejamento automático de carteiras sem movimentações começa na data atual, permitindo
  simular a aposentadoria antes de registrar o primeiro investimento.
- As leituras da carteira, os cenários de planejamento e a observação dos dados de mercado
  passam a usar fluxos compartilhados. A edição de metas anuais mantém as mesmas regras em
  Planejamento e no detalhe do ativo, e os formulários de movimentação manual foram simplificados.
- A conciliação de operações B3 usa as mesmas regras na sugestão e na confirmação, revalidando
  os lançamentos sob bloqueio do banco local para rejeitar vínculos que deixaram de corresponder
  à operação ou já foram utilizados.

## Sistemas suportados

- Windows 10 ou posterior, 64 bits.
- Ubuntu 22.04 ou posterior, 64 bits.

## Instalação

Baixe o arquivo correspondente ao seu sistema operacional e extraia-o em uma pasta própria.
Execute o aplicativo dentro da pasta extraída. Os arquivos `.sha256` permitem verificar a
integridade do download com uma ferramenta compatível com SHA-256.

## Dados persistentes

As carteiras ficam fora da pasta do aplicativo:

- Windows: `%LOCALAPPDATA%\\RendaPerene`;
- Linux: `$XDG_DATA_HOME/RendaPerene` ou `~/.local/share/RendaPerene`.

Antes de substituir uma versão instalada, preserve uma cópia da pasta de dados. A aplicação
detecta bancos legados e oferece a migração para o layout atual na primeira execução.

Os backups criados pela interface são criptografados e a restauração é feita nela própria. A senha
ou chave de recuperação não é armazenada pela aplicação; perder ambas impede recuperar o pacote.

## Limitações conhecidas

- O aplicativo não atualiza instalações existentes automaticamente.
- Dados de mercado dependem de acesso à rede e das integrações públicas configuradas.
- O aplicativo não é assinado digitalmente e não é distribuído por lojas de aplicativos.
