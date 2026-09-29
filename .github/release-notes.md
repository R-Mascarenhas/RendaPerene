## Novidades em 0.11.0

- O histórico de movimentações reúne transações e proventos da carteira, com filtros por período,
  evento e ticker e páginas de até 25 registros. As cores acompanham o tema da interface.
  A importação da B3 preserva a quantidade e o preço unitário dos proventos, usados também nos
  indicadores anuais por cota.
- As metas anuais por ativo agora são independentes dos proventos planejados e podem ser editadas
  por cotas ou crescimento percentual sobre a posição de 1º de janeiro, com salvamento automático.
  Metas antigas são convertidas em cotas fixas, preservando os alvos salvos. O acompanhamento
  apresenta esforço anual estimado, valor restante e aporte externo necessário.
- Em **Ativos → Carteira**, o detalhamento do ativo permite registrar movimentações e editar sua
  meta anual diretamente. A meta individual fica sincronizada com a aba **Metas**, mesmo com o
  acompanhamento geral desativado.
- O histórico mensal e as metas anuais passam a considerar aportes líquidos: compras com taxas
  menos vendas líquidas de taxas. Retiradas aparecem como valores negativos; transferências de
  custódia ficam fora do cálculo.
- O patrimônio inicial foi corrigido nos históricos de planejamento e na Simulação Rápida.
  Os gráficos de projeção incluem o marcador **Hoje**, e as referências do mês zero foram ajustadas.
- A navegação reutiliza projeções locais enquanto a carteira não muda, com invalidação por revisão
  do banco e métricas de desempenho. Também foi corrigida a disputa de bloqueio durante migrações
  concorrentes no Windows.

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
