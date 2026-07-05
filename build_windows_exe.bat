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
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias do requirements.txt.
    goto :error
)

echo [INFO] Instalando ferramenta de compilacao PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [ERRO] Falha ao instalar o PyInstaller.
    goto :error
)

echo [INFO] Finalizando instancias anteriores do RendaPerene (evita bloqueio de arquivos)...
taskkill /f /im RendaPerene.exe >nul 2>&1

echo [INFO] Compilando aplicativo com PyInstaller...
:: Flags explicadas:
:: --onedir: Gera uma pasta com o executavel principal e sub-arquivos. Muito mais rapido para iniciar!
:: --windowed: Oculta a janela de prompt de comando preta em segundo plano, deixando apenas a interface web aberta.
:: --copy-metadata/--collect-all: Coleta metadados essenciais e assets estaticos do Streamlit e Plotly.
:: --add-data: Embuti os codigos-fonte, visualizacoes, servicos e o catalogo de ativos padrão no executavel.
pyinstaller --noconfirm --onedir --windowed ^
    --name "RendaPerene" ^
    --copy-metadata streamlit ^
    --collect-all streamlit ^
    --collect-all plotly ^
    --add-data "app.py;." ^
    --add-data "core;core" ^
    --add-data "views;views" ^
    --add-data "services;services" ^
    --add-data "assets.csv;." ^
    run_app.py

if errorlevel 1 (
    echo [ERRO] Falha na compilacao pelo PyInstaller.
    goto :error
)

echo.
echo =====================================================================
echo    PROCESSO CONCLUIDO COM SUCESSO!
echo =====================================================================
echo.
echo O seu aplicativo compilado foi gerado na pasta:
echo   =^>  dist\RendaPerene\
echo.
echo Para executar o aplicativo:
echo   1. Abra a pasta 'dist\RendaPerene\'
echo   2. Execute o arquivo 'RendaPerene.exe'
echo.
echo Para enviar para outras pessoas:
echo   - Compacte (ZIP) a pasta 'RendaPerene' inteira dentro de 'dist' e envie.
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
