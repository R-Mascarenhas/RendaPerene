from contextlib import closing
from types import SimpleNamespace

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core.daos.portfolio_dao import PortfolioDAO
from services.assets_service import AssetService


def import_app(monkeypatch, frame):
    monkeypatch.setattr(
        st, "file_uploader", lambda *args, **kwargs: SimpleNamespace(name="synthetic.xlsx", size=100)
    )
    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: frame.copy())
    return AppTest.from_string(
        "from views.operations_view import OperationsView\n"
        "OperationsView()._render_b3_import_zone()\n"
    ).run(timeout=15)


def trade(ticker, quantity, price, institution="Corretora Teste"):
    return {
        "Movimentação": "Compra",
        "Data": "2026-10-06",
        "Produto": ticker,
        "Instituição": institution,
        "Quantidade": quantity,
        "Preço unitário": price,
        "Valor da Operação": quantity * price,
        "Entrada/Saída": "Crédito",
    }


@pytest.mark.parametrize("first_choice", [0, 1])
def test_import_requires_explicit_choice_for_every_candidate(monkeypatch, first_choice):
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20)
    assert AssetService.add_transaction("CXSE3", "2026-10-02", "BUY", 10, 15)
    frame = pd.DataFrame([trade("BBAS3", 100, 20), trade("CXSE3", 10, 15)])
    candidates = AssetService.find_b3_manual_trade_candidates(frame)

    app = import_app(monkeypatch, frame)

    assert not app.exception
    assert len(app.selectbox) == 2
    assert all(widget.value is None for widget in app.selectbox)
    assert app.button[0].disabled
    if first_choice == 0:
        app.selectbox[0].select_index(0).run(timeout=15)
    else:
        app.selectbox[0].set_value(candidates[0]["manual_groups"][0]).run(timeout=15)
    assert not app.exception
    assert app.selectbox[1].value is None
    assert app.button[0].disabled
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 0

    app.selectbox[1].set_value(candidates[1]["manual_groups"][0]).run(timeout=15)
    assert not app.exception
    assert not app.button[0].disabled
    app.selectbox[1].set_value(None).run(timeout=15)
    assert not app.exception
    assert app.button[0].disabled
    app.selectbox[1].set_value(candidates[1]["manual_groups"][0]).run(timeout=15)
    assert not app.exception
    assert not app.button[0].disabled
    app.button[0].click().run(timeout=15)
    assert not app.exception
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == (
            3 if first_choice == 0 else 2
        )


def test_confirmation_is_disabled_when_two_lines_reuse_the_same_manual_trade(monkeypatch):
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20)
    frame = pd.DataFrame(
        [trade("BBAS3", 100, 20), trade("BBAS3", 100, 20, "Outra Corretora")]
    )
    candidates = AssetService.find_b3_manual_trade_candidates(frame)
    app = import_app(monkeypatch, frame)
    assert not app.exception
    app.selectbox[0].set_value(candidates[0]["manual_groups"][0]).run(timeout=15)
    app.selectbox[1].set_value(candidates[1]["manual_groups"][0]).run(timeout=15)
    assert not app.exception
    assert app.button[0].disabled
    assert app.error
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 0

    app.selectbox[1].select_index(0).run(timeout=15)
    assert not app.exception
    assert not app.button[0].disabled
