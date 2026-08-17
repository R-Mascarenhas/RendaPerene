from typing import Any

import pandas as pd


class B3ExcelParserAdapter:
    """Concrete implementation of ExcelParserPort to parse raw B3 investment account excel spreadsheet rows,
    normalizing columns, handling splits, corporate events, zero-cost exclusions, and custom corrections.
    """

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

                date_parts = date_str.split("/")
                if len(date_parts) == 3:
                    date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
                else:
                    date = date_str

                raw_product = str(row.get("Código de Negociação", row.get("Produto", ""))).strip()
                ticker = raw_product.split("-")[0].strip()

                if not ticker or len(ticker) < 5 or not ticker[:4].isalpha():
                    continue

                quantity = int(row.get("Quantidade", 0))
                raw_price = row.get("Preço", row.get("Preço unitário", 0.0))
                price = 0.0 if raw_price == "-" else float(raw_price)

                if ticker == "CXSE3" and date == "2021-04-30" and price == 0.0:
                    price = 9.67

                raw_value = row.get("Valor", row.get("Valor da Operação", 0.0))
                total_value = 0.0 if raw_value == "-" else float(raw_value)

                transaction_type = None
                if "Compra" in movement:
                    transaction_type = "BUY"
                elif "Venda" in movement:
                    transaction_type = "SELL"
                elif (
                    "Desdobro" in movement or "Bonificação" in movement or "Bonificacao" in movement
                ):
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
                    # Ignore custodian transfers at zero cost (typically labeled as 'Transferência' or 'Transferência - Liquidação' with zero price)
                    is_transfer = (
                        "Transfer" in movement
                        or "Transferência" in movement
                        or "Transferencia" in movement
                    )
                    if is_transfer and (price == 0.0 or raw_price == "-"):
                        continue
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "BUY"
                    elif "debito" in entry_exit or "débito" in entry_exit:
                        transaction_type = "SELL"
                elif "Resgate" in movement:
                    transaction_type = "SELL"

                if transaction_type in ("BUY", "SELL", "SPLIT", "GROUP"):
                    t_type = "BUY" if transaction_type == "SPLIT" else transaction_type
                    t_price = 0.0 if transaction_type in ("SPLIT", "GROUP") else price
                    transactions_list.append(
                        {
                            "ticker": ticker,
                            "date": date,
                            "transaction_type": t_type,
                            "quantity": quantity,
                            "unit_price": t_price,
                            "fees": 0.0,
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
                columns=["ticker", "date", "transaction_type", "quantity", "unit_price", "fees"],
            )
            if transactions_list
            else pd.DataFrame(
                columns=["ticker", "date", "transaction_type", "quantity", "unit_price", "fees"]
            )
        )
        dividends_df = (
            pd.DataFrame(dividends_list, columns=["ticker", "date", "dividend_type", "total_value"])
            if dividends_list
            else pd.DataFrame(columns=["ticker", "date", "dividend_type", "total_value"])
        )

        return transactions_df, dividends_df
