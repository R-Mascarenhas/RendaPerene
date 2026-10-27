# Plano aprovado: instaladores nativos (#109 e #110)

Contrato: issues #109 (Windows) e #110 (Ubuntu). Downloads e checksums continuam no
GitHub Releases. Sem atualização automática ou repositório APT. Primeira migração
dos pacotes antigos é manual, pois o detector antigo exige ZIP/TAR.GZ.

## Entrega Windows — #109

1. `core/update_checker.py` e `tests/test_update_checker.py`: selecionar o instalador
   `.exe` Windows pelo nome exato, preservando Linux nesta entrega. Testar seleção,
   ausência do instalador e rejeição de URLs externas pela interface existente.
2. `RendaPerene.spec`, `scripts/windows_mutex_hook.py` e
   `scripts/windows_installer.iss`: manter o bundle Windows e o executável com nome
   fixo; criar instalador Inno Setup por usuário, com destino padrão
   `%LOCALAPPDATA%\Programs\RendaPerene`, pasta editável e identidade estável.
   Preservar a pasta em upgrades e os atalhos. Bloquear instalação/desinstalação
   enquanto o aplicativo estiver aberto. Limpar apenas dependências privadas antigas.
3. `scripts/build_windows.ps1` e `scripts/test_windows_installer.ps1`: gerar e
   validar o instalador, instalar versão anterior sintética e atualizar para a atual;
   verificar destino padrão/personalizado, atalhos, bloqueio com processo aberto,
   limpeza de dependências obsoletas e preservação de arquivos sintéticos.
   Iniciar o aplicativo instalado com `scripts/smoke_bundle.py`.
4. `.github/workflows/package.yml`: publicar EXE/checksum em lugar de ZIP, executar
   validação nativa e impedir publicação em caso de falha. Atualizar `README.md`,
   `ARCHITECTURE.md`, `docs/release.md` e `.github/release-notes.md`.

## Entrega Ubuntu — #110

1. `scripts/build_linux.sh` e `scripts/build_deb.py`: empacotar o bundle em
   `/opt/rendaperene`, comando estável e entrada de menu, metadados amd64 e
   dependências nativas. Arquivos gerenciados pelo dpkg, sem gravação em dados pessoais.
2. `scripts/test_deb.sh` e testes do construtor: verificar conteúdo/metadados,
   instalação, upgrade e remoção com dados sintéticos; executar o smoke test instalado.
3. `core/update_checker.py`, seus testes e `.github/workflows/package.yml`:
   trocar TAR.GZ por DEB e checksum; preservar a entrega Windows. Atualizar a mesma
   documentação com instalação via `apt install ./...deb`.

## Verificação e limites

Sem alteração de schema, regras financeiras, cache, sessão, OAuth ou credenciais.
Dados locais e tokens permanecem fora da instalação. Testes de atualização usam
somente dados sintéticos. Executar testes direcionados, `venv/bin/pytest`,
`venv/bin/ruff check .` e `venv/bin/ruff format --check .`.
Builds e testes nativos que não possam rodar neste ambiente devem ser executados
nos runners correspondentes; registrar essa limitação sem afirmar validação nativa.
Implementar as entregas em commits separados, com Ubuntu sobre Windows, permitindo
revisão e publicação de PRs em sequência. Não publicar release durante o trabalho.
