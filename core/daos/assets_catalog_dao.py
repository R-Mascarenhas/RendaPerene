import os
import pandas as pd
import streamlit as st

class AssetsCatalogDAO:
    """Data Access Object (DAO) for managing read/write access to the static assets.csv catalog."""

    @staticmethod
    def load_catalog() -> pd.DataFrame:
        """Loads the static assets catalog from assets.csv."""
        if os.path.exists("assets.csv"):
            df = pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig")
            # Strip columns to avoid whitespace issues
            df.columns = df.columns.str.strip()
            return df.set_index("CÓDIGO")
        return pd.DataFrame()

    @staticmethod
    def add_fallback_asset(ticker: str) -> None:
        """Saves a fallback asset to the CSV file if it does not already exist."""
        if os.path.exists("assets.csv"):
            df = pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            if ticker not in df['CÓDIGO'].values:
                new_row = pd.DataFrame([{
                    "CÓDIGO": ticker,
                    "NOME": f"Asset {ticker}",
                    "IMAGEM": "",
                    "CNPJ": "",
                    "SETOR ECONÔMICO": "Outros",
                    "SUBSETOR": "",
                    "SEGMENTO / ADM / PAÍS": "",
                    "TIPO": "Ação",
                    "SEGMENTO": ""
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv("assets.csv", index=False, encoding="utf-8-sig")
                st.cache_data.clear()
