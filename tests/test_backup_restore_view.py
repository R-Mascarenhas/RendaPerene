import hashlib
from dataclasses import replace
from datetime import timedelta, timezone
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from core.application_paths import PortfolioRestoreTarget
from services.local_restore_service import RestorePortfolioPreview, RestorePreview
from views.backup_restore_view import _destination_description, _format_local_datetime


def test_backup_datetime_is_shown_in_brazilian_format_with_local_offset():
    local_timezone = timezone(timedelta(hours=-3))

    assert _format_local_datetime("2026-09-22T14:30:45Z", local_timezone) == (
        "22/09/2026 às 11:30:45 (UTC-03:00)"
    )


def test_restore_destination_uses_current_portfolio_label_instead_of_database_filename():
    target = SimpleNamespace(filename="portfolio_family.db", replaces_existing=True)

    assert _destination_description(target, {"portfolio_family.db": "Carteira: Família"}) == (
        "Substituirá a Carteira: Família."
    )
    assert _destination_description(target, {}) == (
        "Substituirá a carteira local correspondente."
    )


def test_restore_destination_describes_a_new_portfolio_without_technical_filename():
    target = SimpleNamespace(
        filename="portfolio_restored_12345678.db",
        replaces_existing=False,
        requested_name=None,
    )

    assert _destination_description(target, {}) == "Será adicionada como nova carteira."


def test_restore_destination_shows_the_chosen_new_portfolio_name():
    target = SimpleNamespace(
        filename="portfolio_joão.db",
        replaces_existing=False,
        requested_name="João",
    )

    assert _destination_description(target, {}) == "Será adicionada como Carteira: João."


class _RestoreScreenService:
    def __init__(self):
        package_sha256 = hashlib.sha256(b"encrypted package").hexdigest()
        target = PortfolioRestoreTarget(
            portfolio_id="f4b8d9bf-3295-4d80-93b1-846095d53c1f",
            filename="portfolio_restored_f4b8d9bf.db",
            expected_generation=None,
            replaces_existing=False,
            last_modified_at_utc=None,
            state_token="new-destination",
        )
        portfolio = RestorePortfolioPreview(
            package_sha256=package_sha256,
            backup_id="b6ce5614-1025-4a90-998a-0d4f2bc97be7",
            portfolio_id=target.portfolio_id,
            display_name="Carteira Principal",
            schema_version=1,
            target=target,
            backup_is_older_than_local=False,
        )
        self.preview = RestorePreview(
            package_sha256=package_sha256,
            backup_id=portfolio.backup_id,
            created_at_utc="2026-09-22T14:30:45Z",
            app_version="1.0",
            installation_id="3a07d9b9-418a-4a41-bb11-ef23c4f5f174",
            portfolios=(portfolio,),
        )

    def list_local_packages(self):
        return ("local.rpb",)

    def read_local_package(self, _filename):
        return b"encrypted package"

    def inspect_package(self, _content, _credential):
        return self.preview

    def choose_new_destination(self, selected, requested_name):
        target = replace(
            selected.target,
            filename=f"portfolio_{requested_name.lower()}.db",
            state_token=requested_name,
            requested_name=requested_name,
        )
        return replace(selected, target=target)


def _render_restore_screen(service):
    from views.backup_restore_view import render_local_restore

    render_local_restore(service, {"portfolio.db": "Carteira Principal"})


def test_restore_screen_requires_a_name_and_shows_one_destination_for_new_identity():
    app = AppTest.from_function(
        _render_restore_screen, args=(_RestoreScreenService(),), default_timeout=30
    ).run()
    password = next(item for item in app.text_input if item.label == "Senha do pacote")
    password.input("senha segura").run()
    validate = next(item for item in app.button if item.label == "Validar pacote")
    validate.click().run()

    assert not app.exception
    assert any(item.label == "Nome da nova carteira" for item in app.text_input)
    restore = next(item for item in app.button if item.label == "Restaurar carteira")
    assert restore.disabled

    new_name = next(item for item in app.text_input if item.label == "Nome da nova carteira")
    new_name.input("João").run()

    assert not app.exception
    assert any("Destino:** Será adicionada como Carteira: João." in item.value for item in app.info)
    assert all("Carteira no backup" not in item.value for item in app.info)
    assert any(
        item.label == "Confirmo a adição desta carteira com o nome escolhido."
        for item in app.checkbox
    )

    confirmation = next(
        item for item in app.checkbox if item.label.startswith("Confirmo a adição")
    )
    confirmation.check().run()
    assert next(item for item in app.button if item.label == "Restaurar carteira").disabled is False

    new_name = next(item for item in app.text_input if item.label == "Nome da nova carteira")
    new_name.input("Maria").run()
    assert next(item for item in app.checkbox if item.label.startswith("Confirmo a adição")).value is False
    assert next(item for item in app.button if item.label == "Restaurar carteira").disabled
