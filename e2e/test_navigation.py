"""Switching screens must remove the previous dashboard and its charts."""

import pytest
from playwright.sync_api import expect
from test_portfolio_journey import (
    enter_trade,
    navigate,
    navigation_control,
    open_operations,
    run_action,
)

pytestmark = pytest.mark.e2e


def assert_dashboard_removed(page):
    for heading in (
        "Resumo Patrimonial",
        "📈 Evolução Patrimonial Histórica & Planejamento",
        "📊 Histórico de Aportes Líquidos por Ano e Mês",
        "Ativos em Custódia (Detalhado)",
    ):
        expect(page.get_by_role("heading", name=heading, exact=True)).to_have_count(0)
    for title in (
        "Divisão do Patrimônio por Setor",
        "Evolução por ativo",
        "Aportes Líquidos Mensais",
        "Histórico de Evolução Patrimonial: Real vs. Planejado",
    ):
        expect(page.get_by_text(title, exact=True)).to_have_count(0)


def test_dashboard_content_is_removed_from_an_empty_portfolio(local_page):
    page = local_page
    expect(page.get_by_role("heading", name="Resumo Patrimonial", exact=True)).to_be_visible()
    run_action(page, navigation_control(page, "Ativos").click, full_run=True)
    expect(
        page.get_by_role("heading", name="📁 Detalhamento de Ativos em Carteira", exact=True)
    ).to_be_visible()
    assert_dashboard_removed(page)


def test_dashboard_charts_are_removed_when_switching_screens(local_page):
    page = local_page
    open_operations(page)
    enter_trade(page, 10, 20, 5)
    navigate(page, "Dashboard")
    expect(page.get_by_role("heading", name="Resumo Patrimonial", exact=True)).to_be_visible()
    expect(page.get_by_test_id("stPlotlyChart")).to_have_count(4)

    run_action(page, navigation_control(page, "Ativos").click, full_run=True)
    expect(page.get_by_role("tab", name="BBAS3", exact=True)).to_be_visible()
    assert_dashboard_removed(page)
    # Native packages may still be loading price history, so the asset chart
    # can be absent; none of the four dashboard charts may remain.
    assert page.get_by_test_id("stPlotlyChart").count() <= 1

    run_action(page, navigation_control(page, "Operações").click, full_run=True)
    expect(page.get_by_role("button", name="Registrar Lançamento", exact=True)).to_be_visible()
    assert_dashboard_removed(page)
    expect(page.get_by_test_id("stPlotlyChart")).to_have_count(0)

    run_action(page, navigation_control(page, "Planejamento").click, full_run=True)
    expect(
        page.get_by_role(
            "heading",
            name="🎯 Planejamento de Aposentadoria e Independência Financeira",
            exact=True,
        )
    ).to_be_visible()
    assert_dashboard_removed(page)
    expect(page.get_by_test_id("stException")).to_have_count(0)
