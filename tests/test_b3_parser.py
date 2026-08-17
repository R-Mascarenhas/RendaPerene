import pytest
import os
import shutil
import pandas as pd
from services.assets_service import AssetService

def test_add_transaction_and_assets_creation():
    """Ensures that the transaction creates the asset using the fallback metadata in the assets csv."""
    if os.path.exists("assets_temp.csv"):
        os.remove("assets_temp.csv")
    shutil.copy("test_assets.csv", "assets.csv")

    AssetService.add_transaction("MOCK4", "2021-04-30", "BUY", 100, 20.00, 5.0)

    df = pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig").set_index("CÓDIGO")
    assert "MOCK4" in df.index
    assert df.loc["MOCK4", "NOME"] == "Asset MOCK4"

    if os.path.exists("assets.csv"):
        os.remove("assets.csv")

def test_b3_excel_importer_logic():
    """Ensures Pandas import logic maps B3 columns and handles liquidations correctly."""
    df_excel = pd.read_excel("tests/b3-mock-transactions.xlsx")

    trans_count, prov_count = AssetService.process_b3_import(df_excel)

    # CDB is ignored, Transfer is ignored.
    # Valid: 1 Buy, 1 Sell, 1 Split (Buy @ 0.0), 1 Redemption (Sell). Total = 4.
    # Dividends: 1 Dividendo, 1 JCP. Total = 2.
    assert trans_count == 4
    assert prov_count == 2

    df_positions = AssetService.calculate_positions()
    assert len(df_positions) == 1
    assert df_positions.loc[0, "quantity"] == 150 # 100 buy + 100 split - 50 sell
    assert round(df_positions.loc[0, "average_price"], 2) == 6.67 # (100 * 20.00 - 50 * 20.00) / 150 = 1000 / 150 = 6.67
    assert df_positions.loc[0, "total_dividends"] == 80.00

def test_b3_importer_deduplication():
    """Ensures running imports consecutively does not duplicate data in SQLite."""
    df_excel = pd.read_excel("tests/b3-mock-transactions.xlsx")

    t1, p1 = AssetService.process_b3_import(df_excel)
    assert t1 == 4
    assert p1 == 2

    t2, p2 = AssetService.process_b3_import(df_excel)
    assert t2 == 0
    assert p2 == 0

    df_positions = AssetService.calculate_positions()
    assert len(df_positions) == 1
    assert df_positions.loc[0, "quantity"] == 150
    assert df_positions.loc[0, "total_dividends"] == 80.00

def test_b3_importer_progress_callback():
    """Ensures progress callback is called during import process."""
    df_excel = pd.read_excel("tests/b3-mock-transactions.xlsx")
    calls = []

    def mock_callback(current, total):
        calls.append((current, total))

    t, p = AssetService.process_b3_import(df_excel, progress_callback=mock_callback)
    assert len(calls) == len(df_excel)
    assert calls[-1][0] == len(df_excel)
    assert calls[-1][1] == len(df_excel)

def test_b3_split_logic():
    """Ensures 'Desdobro' events are imported as zero-cost buys, halving average price."""
    AssetService.add_transaction("BBAS3", "2021-04-30", "BUY", 100, 20.00)

    data_example = {
        "Entrada/Saída": ["Credito"],
        "Movimentação": ["Desdobro"],
        "Data": ["17/04/2024"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A"],
        "Quantidade": [100],
        "Preço unitário": ["-"],
        "Valor da Operação": ["-"]
    }
    df_excel = pd.DataFrame(data_example)

    trans, prov = AssetService.process_b3_import(df_excel)
    assert trans == 1
    assert prov == 0

    df_pos = AssetService.calculate_positions()
    assert len(df_pos) == 1
    assert df_pos.loc[0, "quantity"] == 200
    assert df_pos.loc[0, "average_price"] == 10.00

def test_b3_resgate_logic():
    """Ensures 'Resgate' events are imported as Sells, bringing quantity to zero."""
    AssetService.add_transaction("NUBR33", "2021-12-10", "BUY", 239, 8.36)

    data_example = {
        "Entrada/Saída": ["Debito", "Credito"],
        "Movimentação": ["Transferência - Liquidação", "Resgate"],
        "Data": ["14/12/2021", "15/09/2023"],
        "Produto": ["NUBR33 - NU HOLDINGS LTD.", "NUBR33 - NU HOLDINGS LTD."],
        "Quantidade": [1, 238],
        "Preço unitário": [10.50, 5.981],
        "Valor da Operação": [10.50, 1423.42]
    }
    df_excel = pd.DataFrame(data_example)

    trans, prov = AssetService.process_b3_import(df_excel)
    assert trans == 2
    assert prov == 0

    df_pos = AssetService.calculate_positions()
    assert len(df_pos) == 0

def test_b3_custodian_transfer_ignored():
    """Ensures custodian transfer and deposit events with zero price are ignored."""
    AssetService.add_transaction("BBAS3", "2021-04-30", "BUY", 100, 20.00)

    data_example = {
        "Entrada/Saída": ["Debito", "Credito"],
        "Movimentação": ["Transferência - Liquidação", "Transferência - Liquidação"],
        "Data": ["12/05/2026", "12/05/2026"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A"],
        "Quantidade": [600, 600],
        "Preço unitário": ["-", "-"],
        "Valor da Operação": ["-", "-"]
    }
    df_excel = pd.DataFrame(data_example)

    trans, prov = AssetService.process_b3_import(df_excel)
    assert trans == 0  # Should ignore both transfers
    assert prov == 0

    df_pos = AssetService.calculate_positions()
    assert len(df_pos) == 1
    assert df_pos.loc[0, "quantity"] == 100
    assert df_pos.loc[0, "average_price"] == 20.00

def test_discrepancies_parser():
    """
    TDD Test to verify the parser fixes for the 4 discrepancies reported:
    1. BBDC3 - 100 shares bonus (Bonificação em Ativos) -> quantity should increase from 1000 to 1100.
    2. ITUB3 - 18 + 40 shares bonus (Bonificação em Ativos) -> quantity should increase from 500 to 558.
    3. BBAS3 - 6 shares deposit (Depósito) + 6 shares transfer-out (Transferência Debito) + 6 shares transfer-in (Transferência Credito).
       Net change is +6, quantity should increase from 100 to 106.
    4. IRBR3 - 6000 shares reverse split (Grupamento) to 200 -> quantity should become 200 and PM should adjust to 107.00.
    """
    # Create the mock B3 dataframe
    data = {
        "Entrada/Saída": [
            "Credito", "Credito",  # BBDC3
            "Credito", "Credito", "Credito",  # ITUB3
            "Credito", "Credito", "Debito", "Credito",  # BBAS3
            "Credito", "Credito", "Credito"  # IRBR3
        ],
        "Movimentação": [
            "Compra", "Bonificação em Ativos",  # BBDC3
            "Compra", "Bonificação em Ativos", "Bonificação em Ativos",  # ITUB3
            "Transferência - Liquidação", "Depósito", "Transferência", "Transferência",  # BBAS3
            "Transferência - Liquidação", "Transferência - Liquidação", "Grupamento"  # IRBR3
        ],
        "Data": [
            "01/01/2021", "20/04/2022",  # BBDC3
            "01/01/2021", "19/03/2025", "29/12/2025",  # ITUB3
            "10/07/2024", "30/04/2026", "04/05/2026", "04/05/2026",  # BBAS3
            "11/10/2021", "06/09/2022", "26/01/2023"  # IRBR3
        ],
        "Produto": [
            "BBDC3 - BANCO BRADESCO S/A", "BBDC3 - BANCO BRADESCO S/A",
            "ITUB3 - ITAU UNIBANCO HOLDING S/A", "ITUB3 - ITAU UNIBANCO HOLDING S/A", "ITUB3 - ITAU UNIBANCO HOLDING S/A",
            "BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A",
            "IRBR3 - IRB BRASIL RESSEGUROS S/A", "IRBR3 - IRB BRASIL RESSEGUROS S/A", "IRBR3 - IRB BRASIL RESSEGUROS S/A"
        ],
        "Quantidade": [
            1000, 100,
            500, 40, 18,
            100, 6, 6, 6,
            4000, 2000, 200
        ],
        "Preço unitário": [
            15.00, "-",
            25.00, "-", "-",
            26.25, "-", "-", "-",
            4.85, 1.00, "-"
        ],
        "Valor da Operação": [
            15000.00, "-",
            12500.00, "-", "-",
            2625.00, "-", "-", "-",
            19400.00, 2000.00, "-"
        ]
    }
    df_excel = pd.DataFrame(data)

    trans_count, prov_count = AssetService.process_b3_import(df_excel)

    df_positions = AssetService.calculate_positions()
    df_positions.set_index("ticker", inplace=True)

    # 1. BBDC3 assertions
    assert "BBDC3" in df_positions.index
    assert df_positions.loc["BBDC3", "quantity"] == 1100
    assert round(df_positions.loc["BBDC3", "average_price"], 2) == round(15000.00 / 1100, 2)

    # 2. ITUB3 assertions
    assert "ITUB3" in df_positions.index
    assert df_positions.loc["ITUB3", "quantity"] == 558
    assert round(df_positions.loc["ITUB3", "average_price"], 2) == round(12500.00 / 558, 2)

    # 3. BBAS3 assertions
    assert "BBAS3" in df_positions.index
    assert df_positions.loc["BBAS3", "quantity"] == 106
    # price of extra 6s is 0.0. Chronological PM math:
    # 1. Buy 100 @ 26.25 -> PM = 26.25, Qty = 100
    # 2. Deposit 6 @ 0.0 -> PM = (100 * 26.25) / 106 = 24.764, Qty = 106
    # 3. Transfer Out 6 (Zero-cost custodian transfer) -> Ignored!
    # 4. Transfer In 6 (Zero-cost custodian transfer) -> Ignored!
    assert round(df_positions.loc["BBAS3", "average_price"], 2) == 24.76

    # 4. IRBR3 assertions
    assert "IRBR3" in df_positions.index
    assert df_positions.loc["IRBR3", "quantity"] == 200
    # Cost basis remains 19400 + 2000 = 21400. Average price adjusts to 21400 / 200 = 107.00
    assert round(df_positions.loc["IRBR3", "average_price"], 2) == 107.00

def test_b3_parser_adapter_isolation():
    """Unit test specifically verifying the B3ExcelParserAdapter in isolation,
    asserting it returns clean, standardized DataFrames in English.
    """
    from core.utils.b3_parser import B3ExcelParserAdapter

    data = {
        "Entrada/Saída": ["Credito", "Debito"],
        "Movimentação": ["Compra", "Venda"],
        "Data": ["10/07/2024", "15/07/2024"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A", "VALE3 - VALE S/A"],
        "Quantidade": [100, 50],
        "Preço unitário": [26.25, 60.00],
        "Valor da Operação": [2625.00, 3000.00]
    }
    df_excel = pd.DataFrame(data)

    adapter = B3ExcelParserAdapter()
    transactions_df, dividends_df = adapter.parse_b3_excel(df_excel)

    # Verify transactions DataFrame columns and records
    assert not transactions_df.empty
    assert list(transactions_df.columns) == ['ticker', 'date', 'transaction_type', 'quantity', 'unit_price', 'fees']
    assert transactions_df.loc[0, 'ticker'] == 'BBAS3'
    assert transactions_df.loc[0, 'date'] == '2024-07-10'
    assert transactions_df.loc[0, 'transaction_type'] == 'BUY'
    assert transactions_df.loc[0, 'quantity'] == 100
    assert transactions_df.loc[0, 'unit_price'] == 26.25

    assert transactions_df.loc[1, 'ticker'] == 'VALE3'
    assert transactions_df.loc[1, 'date'] == '2024-07-15'
    assert transactions_df.loc[1, 'transaction_type'] == 'SELL'
    assert transactions_df.loc[1, 'quantity'] == 50
    assert transactions_df.loc[1, 'unit_price'] == 60.00

    # Verify dividends DataFrame is empty
    assert dividends_df.empty


def test_b3_parser_column_variants():
    """Unit test verifying that B3ExcelParserAdapter supports alternative column names correctly."""
    from core.utils.b3_parser import B3ExcelParserAdapter
    # Set up data with alternative column headers (e.g. 'Movimentação' instead of 'Tipo de Movimentação' and 'Preço' instead of 'Preço unitário')
    data = {
        "Entrada/Saída": ["Credito", "Debito"],
        "Movimentação": ["Compra", "Venda"],
        "Data": ["10/07/2024", "15/07/2024"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A", "VALE3 - VALE S/A"],
        "Quantidade": [100, 50],
        "Preço": [26.25, 60.00],
        "Valor": [2625.00, 3000.00]
    }
    df_excel = pd.DataFrame(data)
    adapter = B3ExcelParserAdapter()
    transactions_df, dividends_df = adapter.parse_b3_excel(df_excel)

    assert not transactions_df.empty
    assert transactions_df.loc[0, 'ticker'] == 'BBAS3'
    assert transactions_df.loc[0, 'transaction_type'] == 'BUY'
    assert transactions_df.loc[0, 'unit_price'] == 26.25
    assert transactions_df.loc[1, 'ticker'] == 'VALE3'
    assert transactions_df.loc[1, 'transaction_type'] == 'SELL'
    assert transactions_df.loc[1, 'unit_price'] == 60.00


def test_b3_parser_corporate_events_and_dividends():
    """Unit test verifying that Desdobro, Bonificação, Grupamento, Dividendo, Juros, and Rendimento are mapped correctly."""
    from core.utils.b3_parser import B3ExcelParserAdapter
    data = {
        "Entrada/Saída": ["Credito", "Credito", "Credito", "Credito", "Credito", "Credito"],
        "Movimentação": [
            "Desdobro",
            "Bonificação em Ativos",
            "Grupamento",
            "Dividendo",
            "Juros Sobre Capital Próprio",
            "Rendimento"
        ],
        "Data": ["10/07/2024", "11/07/2024", "12/07/2024", "13/07/2024", "14/07/2024", "15/07/2024"],
        "Produto": ["BBAS3", "VALE3", "PETR4", "BBAS3", "VALE3", "MXRF11"],
        "Quantidade": [100, 50, 10, 0, 0, 0],
        "Preço unitário": ["-", "-", "-", "-", "-", "-"],
        "Valor da Operação": ["-", "-", "-", 120.00, 50.00, 8.50]
    }
    df_excel = pd.DataFrame(data)
    adapter = B3ExcelParserAdapter()
    transactions_df, dividends_df = adapter.parse_b3_excel(df_excel)

    assert len(transactions_df) == 3
    # Desdobro -> BUY, unit_price = 0.0
    assert transactions_df.loc[0, 'ticker'] == 'BBAS3'
    assert transactions_df.loc[0, 'transaction_type'] == 'BUY'
    assert transactions_df.loc[0, 'unit_price'] == 0.0

    # Bonificação em Ativos -> BUY, unit_price = 0.0
    assert transactions_df.loc[1, 'ticker'] == 'VALE3'
    assert transactions_df.loc[1, 'transaction_type'] == 'BUY'
    assert transactions_df.loc[1, 'unit_price'] == 0.0

    # Grupamento -> GROUP, unit_price = 0.0
    assert transactions_df.loc[2, 'ticker'] == 'PETR4'
    assert transactions_df.loc[2, 'transaction_type'] == 'GROUP'
    assert transactions_df.loc[2, 'unit_price'] == 0.0

    assert len(dividends_df) == 3
    # Dividendo -> DIVIDEND
    assert dividends_df.loc[0, 'ticker'] == 'BBAS3'
    assert dividends_df.loc[0, 'dividend_type'] == 'DIVIDEND'
    assert dividends_df.loc[0, 'total_value'] == 120.00

    # Juros -> JCP
    assert dividends_df.loc[1, 'ticker'] == 'VALE3'
    assert dividends_df.loc[1, 'dividend_type'] == 'JCP'
    assert dividends_df.loc[1, 'total_value'] == 50.00

    # Rendimento -> YIELD
    assert dividends_df.loc[2, 'ticker'] == 'MXRF11'
    assert dividends_df.loc[2, 'dividend_type'] == 'YIELD'
    assert dividends_df.loc[2, 'total_value'] == 8.50


def test_b3_parser_zero_cost_transfers_and_exclusions():
    """Unit test verifying custodian transfers are excluded if price is zero, but recorded if price is positive."""
    from core.utils.b3_parser import B3ExcelParserAdapter
    data = {
        "Entrada/Saída": ["Credito", "Debito", "Credito"],
        "Movimentação": ["Transferência", "Transferência", "Transferência"],
        "Data": ["10/07/2024", "11/07/2024", "12/07/2024"],
        "Produto": ["BBAS3", "VALE3", "PETR4"],
        "Quantidade": [100, 50, 10],
        "Preço unitário": ["-", "-", 25.00],
        "Valor da Operação": ["-", "-", 250.00]
    }
    df_excel = pd.DataFrame(data)
    adapter = B3ExcelParserAdapter()
    transactions_df, dividends_df = adapter.parse_b3_excel(df_excel)

    # Only PETR4 has positive price, other transfers are zero-cost and should be excluded.
    assert len(transactions_df) == 1
    assert transactions_df.loc[0, 'ticker'] == 'PETR4'
    assert transactions_df.loc[0, 'transaction_type'] == 'BUY'
    assert transactions_df.loc[0, 'unit_price'] == 25.00


def test_b3_parser_cxse3_price_correction():
    """Unit test verifying that zero-cost CXSE3 on 2021-04-30 gets its unit price corrected to 9.67."""
    from core.utils.b3_parser import B3ExcelParserAdapter
    data = {
        "Entrada/Saída": ["Credito"],
        "Movimentação": ["Compra"],
        "Data": ["30/04/2021"],
        "Produto": ["CXSE3"],
        "Quantidade": [100],
        "Preço unitário": ["-"],
        "Valor da Operação": ["-"]
    }
    df_excel = pd.DataFrame(data)
    adapter = B3ExcelParserAdapter()
    transactions_df, dividends_df = adapter.parse_b3_excel(df_excel)

    assert len(transactions_df) == 1
    assert transactions_df.loc[0, 'ticker'] == 'CXSE3'
    assert transactions_df.loc[0, 'unit_price'] == 9.67


def test_assets_service_injected_parser_delegation():
    """Unit test verifying AssetService handles custom injected ExcelParserPort implementation."""
    from core.ports import ExcelParserPort
    from services.assets_service import AssetService

    class FakeExcelParser(ExcelParserPort):
        def parse_b3_excel(self, df: pd.DataFrame, progress_callback = None):
            # Custom hardcoded parse output
            tx_data = [{
                'ticker': 'FAKE4', 'date': '2026-08-17', 'transaction_type': 'BUY',
                'quantity': 200, 'unit_price': 10.00, 'fees': 0.0
            }]
            div_data = []
            return pd.DataFrame(tx_data), pd.DataFrame(div_data)

    fake_parser = FakeExcelParser()

    # Create a fresh isolated AssetService instance
    service = AssetService(excel_parser=fake_parser)
    assert service._excel_parser is fake_parser

    # Try processing
    dummy_df = pd.DataFrame({"dummy": [1]})
    tx_count, div_count = service.process_b3_import(dummy_df)

    assert tx_count == 1
    assert div_count == 0

    df_positions = service.calculate_positions()
    df_positions.set_index("ticker", inplace=True)
    assert "FAKE4" in df_positions.index
    assert df_positions.loc["FAKE4", "quantity"] == 200
    assert df_positions.loc["FAKE4", "average_price"] == 10.00
