# Publicação de releases

Este documento é destinado aos mantenedores do RendaPerene.

## Criar uma versão

Atualize `version.txt` com uma versão semântica, faça commit na `main` e crie a tag correspondente:

```bash
git add version.txt
git commit -m "chore: bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

A tag precisa seguir o formato `vX.Y.Z` e corresponder exatamente ao conteúdo de `version.txt`.

## Workflow

O workflow de distribuição executa o quality gate, cria os pacotes nativos nos runners Windows e
Ubuntu, gera checksums SHA-256 e publica um GitHub Release somente quando os dois pacotes passam na
validação. A execução manual do workflow serve apenas para testar os builds e não publica um release.

O job de publicação usa somente o `GITHUB_TOKEN` com permissão `contents: write`. Os demais jobs
mantêm permissão somente de leitura.
