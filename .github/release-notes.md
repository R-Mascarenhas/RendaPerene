## Novidades em 0.11.1

- Cotações, históricos e indicadores econômicos são atualizados em segundo plano, sem bloquear
  a navegação. A carteira abre com os dados locais e o último dado de mercado válido; a interface
  informa a idade dos dados, as atualizações em andamento e eventuais falhas de conexão.
- Enquanto faltam cotações, campos dependentes delas mostram **N/D**, e patrimônio total,
  rentabilidade, pesos e gráficos de composição aguardam dados completos. Indicadores econômicos
  sem resposta usam referências provisórias identificadas na tela. A atualização do salário mínimo
  pelo BCB mantém o valor atual até receber e salvar uma resposta válida.
- O cache de mercado e as projeções locais passam a ser reutilizados após reiniciar a aplicação,
  reduzindo consultas e recálculos. O cache é local, descartável e fica fora dos backups da carteira.
- Em **Ativos → Carteira**, cada ticker tem uma aba, e apenas o ativo selecionado é carregado.
  Os formulários **Registrar movimentação** e **Meta anual deste ativo** são preparados ao abrir
  seus blocos expansíveis; indicadores, gráficos e históricos aparecem automaticamente.
- A importação da B3 permite conciliar uma operação consolidada com um ou mais lançamentos
  manuais correspondentes, evitando duplicidade mediante confirmação. As sugestões comparam
  ticker, tipo, datas, quantidade total e preço médio ponderado. Você escolhe os lançamentos
  existentes ou **Importar como nova operação** antes de confirmar; datas, taxas e origem manual
  são preservadas, e um lançamento não pode ser vinculado a mais de uma linha B3.
- As escolhas da conciliação reutilizam a prévia da planilha e são revalidadas na confirmação.
  Sugestões são renovadas ao mudar o arquivo ou a carteira. Se houver combinações demais para
  comparar com segurança, a importação é interrompida antes de gravar a planilha.

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
