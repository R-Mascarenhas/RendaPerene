@echo off
:: Desativa eco de comandos para visualizacao limpa
echo =====================================================================
echo    Compilador Automatizado de Executavel Windows (RendaPerene App)
echo =====================================================================
echo.

:: Garante a criacao de um ambiente virtual Python limpo para producao.
:: Isso evita embutir bibliotecas de desenvolvimento desnecessarias, mantendo o executavel menor.
if not exist venv_dist (
    echo [INFO] Criando ambiente virtual isolado venv_dist...
    python -m venv venv_dist
    if errorlevel 1 (
        echo [ERRO] Falha ao criar o ambiente virtual. Certifique-se de que o Python esta no PATH.
        goto :error
    )
)

echo [INFO] Ativando ambiente virtual...
call venv_dist\Scripts\activate
if errorlevel 1 (
    echo [ERRO] Falha ao ativar o ambiente virtual.
    goto :error
)

echo [INFO] Atualizando gerenciador de pacotes pip...
python -m pip install --upgrade pip

echo [INFO] Instalando dependencias de producao do projeto...
pip install .
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias declaradas no pyproject.toml.
    goto :error
)

echo [INFO] Instalando ferramenta de compilacao PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [ERRO] Falha ao instalar o PyInstaller.
    goto :error
)

echo [INFO] Lendo a versao atual do aplicativo de version.txt...
if not exist version.txt (
    echo [ERRO] O arquivo version.txt nao foi encontrado!
    goto :error
)
set /p APP_VERSION=<version.txt
echo [INFO] Versao detectada: %APP_VERSION%

echo [INFO] Finalizando instancias anteriores do RendaPerene (evita bloqueio de arquivos)...
taskkill /f /fi "IMAGENAME eq RendaPerene*" >nul 2>&1

:: Proactive cleanup of the output directory before PyInstaller begins, preventing locked .pyd issues
if exist "dist\RendaPerene-v%APP_VERSION%" (
    echo [INFO] Limpando diretorio de build anterior para evitar bloqueios de arquivo...
    rmdir /s /q "dist\RendaPerene-v%APP_VERSION%" >nul 2>&1
    if exist "dist\RendaPerene-v%APP_VERSION%" (
        echo.
        echo =====================================================================
        echo [ERRO] Nao foi possivel remover a pasta 'dist\RendaPerene-v%APP_VERSION%'.
        echo Ela esta sendo usada por outro processo como navegador ou prompt.
        echo.
        echo Por favor:
        echo   1. Feche o navegador ou aplicativo RendaPerene.
        echo   2. Verifique se nao ha terminais abertos dentro da pasta 'dist'.
        echo   3. Se o erro persistir, reinicie o computador para liberar as travas.
        echo =====================================================================
        echo.
        goto :error
    )
)

echo [INFO] Compilando aplicativo com PyInstaller...
:: Flags explicadas:
:: --onedir: Gera uma pasta com o executavel principal e sub-arquivos. Muito mais rapido para iniciar!
:: --windowed: Oculta a janela de prompt de comando preta em segundo plano, deixando apenas a interface web aberta.
:: --copy-metadata/--collect-all: Coleta metadados essenciais e assets estaticos do Streamlit e Plotly.
:: --add-data: Embuti os codigos-fonte, visualizacoes, servicos e o catalogo de ativos padrão no executavel.
pyinstaller --noconfirm --onedir --windowed ^
    --name "RendaPerene-v%APP_VERSION%" ^
    --copy-metadata streamlit ^
    --collect-all streamlit ^
    --collect-all plotly ^
    --add-data "app.py;." ^
    --add-data "core;core" ^
    --add-data "views;views" ^
    --add-data "services;services" ^
    --add-data "assets.csv;." ^
    --add-data "database\portfolio_demo.db;database" ^
    --add-data "version.txt;." ^
    run_app.py

if errorlevel 1 (
    echo [ERRO] Falha na compilacao pelo PyInstaller.
    goto :error
)

echo [INFO] Criando arquivo compactado (ZIP) para distribuicao...
if exist "dist\RendaPerene-v%APP_VERSION%.zip" (
    del "dist\RendaPerene-v%APP_VERSION%.zip" >nul 2>&1
)
powershell -Command "Compress-Archive -Path 'dist\RendaPerene-v%APP_VERSION%' -DestinationPath 'dist\RendaPerene-v%APP_VERSION%.zip' -Force"
if errorlevel 1 (
    echo [AVISO] Falha ao criar o arquivo ZIP automaticamente.
) else (
    echo [INFO] Arquivo ZIP criado com sucesso: dist\RendaPerene-v%APP_VERSION%.zip
)

echo.
echo =====================================================================
echo    PROCESSO CONCLUIDO COM SUCESSO!
echo =====================================================================
echo.
echo O seu aplicativo compilado foi gerado na pasta:
echo   =^>  dist\RendaPerene-v%APP_VERSION%\
echo.
echo Arquivo ZIP pronto para distribuicao:
echo   =^>  dist\RendaPerene-v%APP_VERSION%.zip
echo.
echo Para executar o aplicativo localmente:
echo   1. Abra a pasta 'dist\RendaPerene-v%APP_VERSION%\'
echo   2. Execute o arquivo 'RendaPerene-v%APP_VERSION%.exe'
echo.
echo Para enviar para outras pessoas:
echo   - Envie diretamente o arquivo 'dist\RendaPerene-v%APP_VERSION%.zip' gerado.
echo     (As outras pessoas NAO precisam ter Python instalado para rodar!)
echo.
echo =====================================================================
pause
exit /b 0

:error
echo.
echo =====================================================================
echo    [FALHA] Ocorreu um erro inesperado durante a execucao do script.
echo =====================================================================
pause
exit /b 1
