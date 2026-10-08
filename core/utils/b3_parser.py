import hashlib
import json
import math
import unicodedata
from typing import Any

import pandas as pd

from core.utils.ticker import normalize_b3_ticker


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

    @staticmethod
    def _optional_positive_number(value) -> float | None:
        """Keep absent or invalid receipt metadata separate from a reported zero."""
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result > 0 else None

    @staticmethod
    def _canonical_text(value) -> str:
        """Normalizes human-readable B3 fields before generating source identities."""
        return (
            unicodedata.normalize("NFKD", str(value).strip())
            .encode("ascii", "ignore")
            .decode()
            .casefold()
        )

    def parse_b3_excel(
        self, df: pd.DataFrame, progress_callback: Any = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Parses raw B3 investment account excel spreadsheet rows, returning a standardized (transactions_df, dividends_df) tuple in English."""
        df.columns = df.columns.str.strip()

        transactions_list = []
        dividends_list = []
        occurrence_counts = {}
        identity_occurrence_counts = {}
        total_rows = len(df)

        for idx, (_, row) in enumerate(df.iterrows()):
            if progress_callback and total_rows > 0:
                progress_callback(idx + 1, total_rows)
            try:
                movement = str(row.get("Tipo de Movimentação", row.get("Movimentação", ""))).strip()
                raw_entry_exit = row.get("Entrada/Saída", "")
                entry_exit = "" if pd.isna(raw_entry_exit) else str(raw_entry_exit).strip().lower()
                date_column = next(
                    (
                        column
                        for column in ("Data do Negócio", "Data", "Data de Liquidação")
                        if pd.notna(row.get(column))
                        and str(row.get(column)).strip() not in ("", "-")
                    ),
                    None,
                )
                if date_column is None:
                    continue
                date_text = str(row[date_column]).strip()
                date = pd.to_datetime(date_text, dayfirst="/" in date_text).strftime("%Y-%m-%d")

                raw_product = str(row.get("Código de Negociação", row.get("Produto", ""))).strip()
                try:
                    ticker = normalize_b3_ticker(raw_product.split("-")[0])
                except ValueError:
                    continue

                is_dividend = any(term in movement for term in ["Dividendo", "Juros", "Rendimento"])
                if is_dividend and "transfer" in self._canonical_text(movement):
                    # Moving a dividend entitlement between custodians is not a cash receipt.
                    continue
                quantity = (
                    self._optional_positive_number(row.get("Quantidade"))
                    if is_dividend
                    else int(row.get("Quantidade", 0))
                )
                raw_price = row.get("Preço", row.get("Preço unitário", 0.0))
                price = (
                    self._optional_positive_number(raw_price)
                    if is_dividend
                    else self._number(raw_price)
                )

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
                is_zero_cost_deposit = "deposito" in normalized

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
                        or (
                            transaction_type == "BUY"
                            and total_value <= 0
                            and not is_zero_cost_deposit
                        )
                    )
                    t_type = (
                        "BUY" if transaction_type in ("SPLIT", "TRANSFER_IN") else transaction_type
                    )
                    t_price = (
                        0.0
                        if corporate or pending or is_zero_cost_deposit
                        else (price if price > 0 else total_value / quantity)
                    )
                    raw_institution = row.get("Instituição", "")
                    institution = "" if pd.isna(raw_institution) else str(raw_institution).strip()
                    source = {
                        "date": date,
                        "ticker": ticker,
                        "movement": movement,
                        "direction": entry_exit,
                        "quantity": quantity,
                        "price": price,
                        "value": total_value,
                        "institution": institution,
                    }
                    occurrence_key = (
                        date,
                        ticker,
                        self._canonical_text(movement),
                        self._canonical_text(entry_exit),
                        quantity,
                        self._canonical_text(source["institution"]),
                        t_type,
                    )
                    occurrence_counts[occurrence_key] = occurrence_counts.get(occurrence_key, 0) + 1
                    identity_occurrence_key = occurrence_key + (
                        (price, total_value) if not pending else (0.0, 0.0),
                    )
                    identity_occurrence_counts[identity_occurrence_key] = (
                        identity_occurrence_counts.get(identity_occurrence_key, 0) + 1
                    )
                    source["occurrence"] = occurrence_counts[occurrence_key]
                    source["identity_occurrence"] = identity_occurrence_counts[
                        identity_occurrence_key
                    ]
                    source_json = json.dumps(source, ensure_ascii=False, sort_keys=True)
                    source_identity = {
                        **source,
                        **{
                            field: self._canonical_text(source[field])
                            for field in ("movement", "direction", "institution")
                        },
                    }
                    if not pending:
                        source_identity["occurrence"] = source["identity_occurrence"]
                    source_identity_json = json.dumps(
                        source_identity, ensure_ascii=False, sort_keys=True
                    )
                    transactions_list.append(
                        {
                            "ticker": ticker,
                            "date": date,
                            "date_is_business": date_column == "Data do Negócio",
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
                            "source_key": hashlib.sha256(source_identity_json.encode()).hexdigest(),
                            "source_record": source_json,
                            "matched_custody_transfer": False,
                        }
                    )
                elif is_dividend:
                    dividend_type = "DIVIDEND" if "Dividendo" in movement else "JCP"
                    if "Rendimento" in movement:
                        dividend_type = "YIELD"
                    dividends_list.append(
                        {
                            "ticker": ticker,
                            "date": date,
                            "dividend_type": dividend_type,
                            "total_value": total_value,
                            "quantity": quantity,
                            "unit_price": price,
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
                    "date_is_business",
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
                columns=[
                    "ticker",
                    "date",
                    "transaction_type",
                    "quantity",
                    "unit_price",
                    "fees",
                ]
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
        dividends_df = pd.DataFrame(
            dividends_list,
            columns=["ticker", "date", "dividend_type", "total_value", "quantity", "unit_price"],
        )

        return transactions_df, dividends_df
