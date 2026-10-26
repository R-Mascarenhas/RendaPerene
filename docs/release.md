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

No Windows, instale o Inno Setup 6 para executar `build_windows_exe.bat` localmente.
O build gera `dist/RendaPerene-vX.Y.Z-windows-x64-setup.exe`, sem ZIP. O executável instalado
tem nome fixo `RendaPerene.exe`. O destino padrão é `%LOCALAPPDATA%\Programs\RendaPerene`,
com pasta editável e reaproveitada nos upgrades. A instalação é por usuário e não exige
administrador para gravar no destino padrão.

O compilador é localizado por `INNO_SETUP_COMPILER`, pelo `PATH`, pelo registro de instalação
do Inno Setup 6 ou pelas pastas padrão de programas do sistema e do usuário. Isso inclui
`%LOCALAPPDATA%\Programs\Inno Setup 6` para instalação sem administrador.
Para uma instalação personalizada não detectada, informe o caminho completo no PowerShell:

```powershell
$env:INNO_SETUP_COMPILER = "D:\Ferramentas\Inno Setup 6\ISCC.exe"
.\build_windows_exe.bat
```

A localização é verificada antes do build. `scripts/test_windows_compiler.ps1` valida as opções
de descoberta usando arquivos temporários, sem modificar o registro nem a instalação do compilador.
A pipeline executa
`scripts/test_windows_installer.ps1` em ambiente descartável para validar instalação padrão e
personalizada, upgrade, atalhos, aplicativo aberto e preservação de arquivos sintéticos.
Esse teste modifica a instalação do usuário do runner e não deve rodar em uma máquina pessoal.
Use a execução manual do workflow para comprovar o instalador nativo antes de criar uma tag.

As versões antigas procuram o ZIP pelo nome e não reconhecerão a release contendo somente EXE.
Informe nas notas que a primeira migração exige baixar o instalador manualmente no GitHub;
depois dela, o aviso existente passa a oferecer o instalador.

No Ubuntu, execute `bash scripts/build_linux.sh` com `dpkg-deb` disponível. O resultado é
`dist/RendaPerene-vX.Y.Z-ubuntu-x64.deb`, sem TAR.GZ. O pacote é instalado pelo gerenciador
ou com `sudo apt install ./RendaPerene-vX.Y.Z-ubuntu-x64.deb`, e o usuário abre `rendaperene`
sem `sudo`. A instalação fica em `/opt/rendaperene`; o dpkg gerencia seus arquivos e preserva
os dados externos à instalação. Feche o aplicativo antes de atualizar ou remover.

`scripts/test_deb.sh` instala, atualiza e remove pacotes reais com `sudo`, somente em runner
Ubuntu descartável. Ele verifica processo aberto, arquivos obsoletos, menu e dados sintéticos.
O build mantém Ubuntu 22.04 como base para compatibilidade com versões posteriores.
As versões TAR.GZ antigas também exigem primeira migração manual pelo GitHub, pois procuram
o nome do arquivo antigo. Releases novas publicam somente EXE, DEB e respectivos checksums.

O job de publicação usa somente o `GITHUB_TOKEN` com permissão `contents: write`. Os demais jobs
mantêm permissão somente de leitura.
