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
