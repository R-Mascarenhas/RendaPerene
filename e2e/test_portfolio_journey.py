"""Operations must survive navigation, new browser sessions and a server restart."""

import re
import sqlite3

import pytest
from playwright.sync_api import expect
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

pytestmark = pytest.mark.e2e


def combobox(page, label):
    # Streamlit includes the current selection in the input's accessible name.
    return page.get_by_role("combobox", name=re.compile(re.escape(label) + r"$"))


def wait_idle(page):
    expect(page.get_by_test_id("stApp")).to_have_attribute("data-test-script-state", "notRunning")


def run_action(page, action, *, full_run=False):
    def finished(payload):
        message = ForwardMsg()
        message.ParseFromString(payload)
        return message.WhichOneof("type") == "script_finished" and (
            message.script_finished == ForwardMsg.FINISHED_SUCCESSFULLY
            or (
                not full_run
                and message.script_finished == ForwardMsg.FINISHED_FRAGMENT_RUN_SUCCESSFULLY
            )
        )

    # Idle alone can still describe the previous run while a click is in flight.
    # Wait for the server's completion frame, including redirects via st.rerun().
    with page.streamlit_socket.expect_event("framereceived", predicate=finished, timeout=30000):
        action()
    wait_idle(page)


def navigate(page, label):
    wait_idle(page)
    button = page.get_by_role("button", name=label, exact=True)
    # Clear an existing selection before selecting the route explicitly. A
    # fragment's full rerun can reset server navigation while the old button
    # still looks selected in the browser.
    if button.get_attribute("kind") == "segmented_controlActive":
        run_action(page, button.click, full_run=True)
    run_action(page, button.click, full_run=True)
    wait_idle(page)


def select_option(page, label, option):
    combobox(page, label).click()
    combobox(page, label).fill(option)
    run_action(
        page,
        page.get_by_role("option", name=option, exact=True).click,
        full_run=label == "Selecione a Carteira Ativa",
    )


def open_operations(page):
    navigate(page, "Ativos")
    navigate(page, "Operações")
    expect(page.get_by_role("button", name="Registrar Lançamento", exact=True)).to_be_visible()


def enter_trade(page, quantity, price, fees):
    select_option(page, "Selecione o Ativo", "BBAS3 - Banco do Brasil SA")
    for label, value in [
        ("Quantidade", quantity),
        ("Preço Unitário (R$)", price),
        ("Taxas/Corretagem (R$)", fees),
    ]:
        field = page.get_by_role("spinbutton", name=label, exact=True)
        if not field.input_value() or float(field.input_value()) != value:

            def change_field():
                field.fill(str(value))
                field.press("Tab")

            run_action(page, change_field)
        expect(field).to_have_value(re.compile(rf"^{value}(?:\.0+)?$"))
    run_action(
        page,
        page.get_by_role("button", name="Registrar Lançamento", exact=True).click,
        full_run=True,
    )


def assert_position(page, database, quantity):
    navigate(page, "Ativos")
    navigate(page, "Meus Ativos")
    expect(page.get_by_role("tab", name="BBAS3", exact=True)).to_be_visible()
    average_price = page.get_by_test_id("stMetric").filter(
        has=page.get_by_text("Preço Médio (PM)", exact=True)
    )
    expect(average_price.get_by_test_id("stMetricValue")).to_have_text("R$ 20,50")
    expect(page.get_by_test_id("stException")).to_have_count(0)
    # Read-only evidence complements the displayed metric without using services
    # or seeding records outside the browser journey.
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT transaction_type, quantity, unit_price, fees FROM transactions ORDER BY id"
        ).fetchall()
    assert rows[0] == ("BUY", 10, 20.0, 5.0)
    if quantity == 6:
        assert rows == [("BUY", 10, 20.0, 5.0), ("SELL", 4, 30.0, 0.0)]
    else:
        assert len(rows) == 1
    assert sum(qty if kind == "BUY" else -qty for kind, qty, _, _ in rows) == quantity

    # With a fixed quote of R$21, this also detects stale displayed quantities
    # after the sale (the average price alone must stay unchanged).
    navigate(page, "Dashboard")
    equity = page.get_by_test_id("stMetric").filter(
        has=page.get_by_text("Patrimônio Atual", exact=True)
    )
    expect(equity.get_by_test_id("stMetricValue")).to_have_text(
        "R$ 210,00" if quantity == 10 else "R$ 126,00"
    )
    expect(page.get_by_test_id("stException")).to_have_count(0)
    navigate(page, "Ativos")


def test_buy_sell_and_restart_preserve_portfolio(local_page, app_server, new_context):
    page = local_page
    page.get_by_role("textbox", name="Nome da Nova Carteira", exact=True).fill("Jornada E2E")
    run_action(
        page,
        page.get_by_role("button", name="Criar Nova Carteira", exact=True).click,
        full_run=True,
    )
    expect(combobox(page, "Selecione a Carteira Ativa")).to_have_attribute(
        "aria-label", re.compile("jornadae2e", re.IGNORECASE)
    )
    database = app_server.sandbox / "data" / "database" / "portfolio_jornadae2e.db"
    open_operations(page)
    enter_trade(page, 10, 20, 5)
    assert_position(page, database, 10)

    navigate(page, "Operações")
    select_option(page, "Tipo de Lançamento", "Venda (Resgate)")
    enter_trade(page, 4, 30, 0)
    assert_position(page, database, 6)

    # The new session must select the portfolio from persisted files alone.
    page.close()
    app_server.restart()
    context = new_context()
    try:
        context.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(app_server.url + "/")
                else route.abort()
            ),
        )
        fresh_page = context.new_page()
        fresh_page.set_default_timeout(15000)
        fresh_page.on(
            "websocket", lambda connection: setattr(fresh_page, "streamlit_socket", connection)
        )
        fresh_page.goto(app_server.url)
        fresh_page.get_by_role("textbox", name="Nome da Nova Carteira", exact=True).wait_for(
            timeout=60000
        )
        expect(fresh_page.get_by_test_id("stApp")).to_have_attribute(
            "data-test-script-state", "notRunning", timeout=60000
        )
        select_option(fresh_page, "Selecione a Carteira Ativa", "Carteira: Jornadae2E")
        assert_position(fresh_page, database, 6)
    finally:
        context.close()
