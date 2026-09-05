import hashlib
import json
import math
import unicodedata
from typing import Any

import pandas as pd


class B3ExcelParserAdapter:
    """Concrete implementation of ExcelParserPort to parse raw B3 investment account excel spreadsheet rows,
    normalizing columns and preserving source identity and cost classification.
    """

    @staticmethod
    def _number(value) -> float:
        if pd.isna(value) or str(value).strip() in ("", "-"):
            return 0.0
        result = float(value)
        return result if math.isfinite(result) else 0.0

    def parse_b3_excel(
        self, df: pd.DataFrame, progress_callback: Any = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Parses raw B3 investment account excel spreadsheet rows, returning a standardized (transactions_df, dividends_df) tuple in English."""
        df.columns = df.columns.str.strip()

        transactions_list = []
        dividends_list = []
        total_rows = len(df)

        for idx, (_, row) in enumerate(df.iterrows()):
            if progress_callback and total_rows > 0:
                progress_callback(idx + 1, total_rows)
            try:
                movement = str(row.get("Tipo de Movimentação", row.get("Movimentação", ""))).strip()
                entry_exit = str(row.get("Entrada/Saída", "")).strip().lower()
                date_str = str(row.get("Data do Negócio", row.get("Data", ""))).strip()

                date = pd.to_datetime(date_str, dayfirst="/" in date_str).strftime("%Y-%m-%d")

                raw_product = str(row.get("Código de Negociação", row.get("Produto", ""))).strip()
                ticker = raw_product.split("-")[0].strip().upper()

                if not ticker or len(ticker) < 5 or not ticker[:4].isalpha():
                    continue

                quantity = int(row.get("Quantidade", 0))
                raw_price = row.get("Preço", row.get("Preço unitário", 0.0))
                price = self._number(raw_price)

                raw_value = row.get("Valor", row.get("Valor da Operação", 0.0))
                total_value = self._number(raw_value)
                normalized = (
                    unicodedata.normalize("NFKD", movement)
                    .encode("ascii", "ignore")
                    .decode()
                    .lower()
                )
                is_credit = entry_exit in ("credito", "crédito")
                is_custody = "transfer" in normalized and "liquidacao" not in normalized

                transaction_type = None
                if "Compra" in movement or "aquisicao" in normalized or "subscricao" in normalized:
                    transaction_type = "BUY"
                elif "Venda" in movement:
                    transaction_type = "SELL"
                elif "desdobr" in normalized or "bonificacao" in normalized:
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "SPLIT"
                elif "Grupamento" in movement:
                    transaction_type = "GROUP"
                elif (
                    "Transferência - Liquidação" in movement
                    or "Transferência" in movement
                    or "Transferencia" in movement
                    or "Depósito" in movement
                    or "Deposito" in movement
                ):
                    if is_custody:
                        transaction_type = "TRANSFER_IN" if is_credit else "TRANSFER_OUT"
                    elif "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "BUY"
                    elif "debito" in entry_exit or "débito" in entry_exit:
                        transaction_type = "SELL"
                elif "Resgate" in movement:
                    transaction_type = "SELL"

                if (
                    transaction_type
                    in ("BUY", "SELL", "SPLIT", "GROUP", "TRANSFER_IN", "TRANSFER_OUT")
                    and quantity > 0
                ):
                    corporate = transaction_type in ("SPLIT", "GROUP")
                    pending = not corporate and (
                        transaction_type == "TRANSFER_IN"
                        or (transaction_type == "BUY" and total_value <= 0)
                    )
                    t_type = (
                        "BUY" if transaction_type in ("SPLIT", "TRANSFER_IN") else transaction_type
                    )
                    t_price = (
                        0.0
                        if corporate or pending
                        else (price if price > 0 else total_value / quantity)
                    )
                    source = {
                        "date": date,
                        "ticker": ticker,
                        "movement": movement,
                        "direction": entry_exit,
                        "quantity": quantity,
                        "price": price,
                        "value": total_value,
                        "institution": str(row.get("Instituição", "")).strip(),
                    }
                    source_json = json.dumps(source, ensure_ascii=False, sort_keys=True)
                    transactions_list.append(
                        {
                            "ticker": ticker,
                            "date": date,
                            "transaction_type": t_type,
                            "quantity": quantity,
                            "unit_price": t_price,
                            "fees": 0.0,
                            "cost_status": "PENDING" if pending else "KNOWN",
                            "event_kind": "CUSTODY"
                            if is_custody
                            else "CORPORATE"
                            if corporate
                            else "TRADE",
                            "source_key": hashlib.sha256(source_json.encode()).hexdigest(),
                            "source_record": source_json,
                            "matched_custody_transfer": False,
                        }
                    )
                elif any(term in movement for term in ["Dividendo", "Juros", "Rendimento"]):
                    dividend_type = "DIVIDEND" if "Dividendo" in movement else "JCP"
                    if "Rendimento" in movement:
                        dividend_type = "YIELD"
                    dividends_list.append(
                        {
                            "ticker": ticker,
                            "date": date,
                            "dividend_type": dividend_type,
                            "total_value": total_value,
                        }
                    )

            except Exception:
                continue

        transactions_df = (
            pd.DataFrame(
                transactions_list,
                columns=[
                    "ticker",
                    "date",
                    "transaction_type",
                    "quantity",
                    "unit_price",
                    "fees",
                    "cost_status",
                    "event_kind",
                    "source_key",
                    "source_record",
                    "matched_custody_transfer",
                ],
            )
            if transactions_list
            else pd.DataFrame(
                columns=["ticker", "date", "transaction_type", "quantity", "unit_price", "fees"]
            )
        )
        if not transactions_df.empty:
            custody = transactions_df[transactions_df["event_kind"] == "CUSTODY"]
            for _, group in custody.groupby(["ticker", "date", "quantity"], sort=False):
                credits = group[group["transaction_type"] == "BUY"].index.tolist()
                debits = group[group["transaction_type"] == "TRANSFER_OUT"].index.tolist()
                pair_count = min(len(credits), len(debits))
                matched = credits[:pair_count] + debits[:pair_count]
                transactions_df.loc[matched, "matched_custody_transfer"] = True
        dividends_df = (
            pd.DataFrame(dividends_list, columns=["ticker", "date", "dividend_type", "total_value"])
            if dividends_list
            else pd.DataFrame(columns=["ticker", "date", "dividend_type", "total_value"])
        )

        return transactions_df, dividends_df
