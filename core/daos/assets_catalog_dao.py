import os

import pandas as pd
import streamlit as st

from core.application_paths import ApplicationPaths


class AssetsCatalogDAO:
    """Data Access Object (DAO) for managing read/write access to the static assets.csv catalog."""

    def __init__(self, csv_path="assets.csv"):
        self.csv_path = csv_path

    def _resolve_csv_path(self):
        """Resolve a static or context-aware catalog path for the current operation."""
        return self.csv_path() if callable(self.csv_path) else self.csv_path

    def load_catalog(self) -> pd.DataFrame:
        """Loads the static assets catalog from assets.csv."""
        csv_path = self._resolve_csv_path()
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            return df.set_index("CÓDIGO")
        return pd.DataFrame()

    def add_fallback_asset(self, ticker: str) -> None:
        """Saves a fallback asset to the CSV file if it does not already exist."""
        csv_path = self._resolve_csv_path()
        if os.path.exists(csv_path):
            with ApplicationPaths._catalog_lock(csv_path):
                self._add_fallback_asset_locked(csv_path, ticker)

    def _add_fallback_asset_locked(self, csv_path, ticker: str) -> None:
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            if ticker not in df["CÓDIGO"].values:
                new_row = pd.DataFrame(
                    [
                        {
                            "CÓDIGO": ticker,
                            "NOME": f"Asset {ticker}",
                            "IMAGEM": "",
                            "CNPJ": "",
                            "SETOR ECONÔMICO": "Outros",
                            "SUBSETOR": "",
                            "SEGMENTO / ADM / PAÍS": "",
                            "TIPO": "Ação",
                            "SEGMENTO": "",
                        }
                    ]
                )
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                st.cache_data.clear()
