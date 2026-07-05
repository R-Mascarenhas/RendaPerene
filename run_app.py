# run_app.py
import os
import sys
import shutil
import sqlite3

# Força o PyInstaller a rastrear e embutir todo o grafo de dependências das bibliotecas do projeto
import streamlit as st
import pandas as pd
import yfinance as yf
import openpyxl
import plotly

import streamlit.web.cli as stcli

def resolve_path(relative_path: str) -> str:
    """
    Resolve o caminho absoluto para recursos embutidos.
    Funciona tanto em modo de desenvolvimento quanto congelado (PyInstaller).
    """
    try:
        # Quando executado de dentro de um binário PyInstaller,
        # sys._MEIPASS aponta para a pasta temporária de descompactação.
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    # Define o diretório de trabalho para onde o executável principal está localizado.
    # ISSO É CRÍTICO para persistência local dos dados (database/portfolio.db e assets.csv).
    # Caso contrário, arquivos seriam gravados na pasta temporária e deletados ao fechar.
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.abspath(".")
    
    os.chdir(exe_dir)
    
    # Cria a estrutura de pastas necessária para o banco de dados SQLite local
    os.makedirs("database", exist_ok=True)
    
    # Auto-seeding: Se o arquivo assets.csv não existir localmente no PC do usuário,
    # copia o catálogo padrão de +6000 ativos embutido dentro do executável para a pasta de uso dele.
    local_assets_csv = "assets.csv"
    if not os.path.exists(local_assets_csv):
        try:
            bundled_assets_csv = resolve_path("assets.csv")
            if os.path.exists(bundled_assets_csv):
                shutil.copy(bundled_assets_csv, local_assets_csv)
        except Exception as e:
            sys.stderr.write(f"Erro ao inicializar arquivo assets.csv: {e}\n")

    # Resolve o caminho do script Streamlit principal (app.py) que está dentro do executável
    script_path = resolve_path("app.py")

    # Configura os argumentos de linha de comando para inicializar o Streamlit programaticamente
    sys.argv = [
        "streamlit",
        "run",
        script_path,
        "--global.developmentMode=false",
        "--server.port=8501",
        "--server.headless=false",  # Abre automaticamente o navegador do usuário
        "--server.showEmailPrompt=false",  # Ignora a pergunta de e-mail na primeira execução!
        "--browser.gatherUsageStats=false"  # Desativa a coleta de telemetria
    ]
    
    sys.exit(stcli.main())
