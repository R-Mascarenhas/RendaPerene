import os

import pandas as pd


class AssetsCatalogDAO:
    """Data Access Object (DAO) for read-only access to the static assets.csv catalog."""

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
