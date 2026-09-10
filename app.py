import os
import sys
import uuid

import streamlit as st

from core.application_paths import ApplicationPaths
from core.constants import (
    SESSION_PORTFOLIO_DELETION_SUCCESS,
    WIDGET_PORTFOLIO_DELETE_CONFIRMATION,
    WIDGET_PORTFOLIO_DELETION_TARGET,
)
from core.daos.assets_catalog_dao import AssetsCatalogDAO
from core.database import DatabaseManager, db
from core.utils import SessionManager, get_app_version
from core.utils.market_data import MarketData

# Detect if running in public shared cloud environments. Native packaged builds
# are always local, even when launched from a mounted directory.
is_frozen = getattr(sys, "frozen", False)
is_cloud = not is_frozen and (
    "STREAMLIT_SHARING_MODE" in os.environ
    or os.path.abspath(".").startswith("/mount")
    or "/mount/" in os.path.abspath(".")
)

runtime_paths = ApplicationPaths.discover()
app_paths = runtime_paths
if is_cloud:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    runtime_paths.cleanup_demo_sessions(st.session_state["session_id"])
    app_paths = app_paths.for_demo_session(st.session_state["session_id"])
    recovered_database = app_paths.prepare(app_paths.bundled_resource("database/portfolio_demo.db"))
    if recovered_database:
        SessionManager.reset_portfolio_state()
        st.rerun()
else:
    app_paths.prepare()

    legacy_sources = list(app_paths.migration_candidates())
    if legacy_sources:
        st.sidebar.warning(
            "Carteiras de uma versão anterior foram encontradas. "
            "Você pode copiá-las com segurança para o novo armazenamento local."
        )
        selected_legacy = st.sidebar.multiselect(
            "Carteiras antigas para importar",
            options=legacy_sources,
            default=legacy_sources,
            format_func=lambda path: path.name,
        )
        if st.sidebar.button("Importar carteiras antigas", use_container_width=True):
            migrated_databases = []
            for source in selected_legacy:
                result = app_paths.migrate_legacy_database(source)
                if result.migrated:
                    migrated_databases.append(source.name)
                    st.sidebar.success(f"{source.name}: {result.message}")
                else:
                    st.sidebar.error(f"{source.name}: {result.message}")
            if migrated_databases:
                requested_db = st.session_state.get("active_db", "portfolio.db")
                st.session_state["active_db"] = (
                    requested_db if requested_db in migrated_databases else migrated_databases[0]
                )
                SessionManager.reset_portfolio_state()
                st.rerun()

inventory = app_paths.inspect_portfolios()
if inventory.invalid:
    invalid_names = ", ".join(path.name for path in inventory.invalid)
    st.sidebar.error(
        f"Bancos SQLite inválidos foram ignorados: {invalid_names}. "
        "Restaure uma cópia válida a partir da pasta de backups."
    )

db_files = list(app_paths.portfolio_options(inventory))
recovery_database = next(
    (
        filename
        for filename in db_files
        if filename.startswith("portfolio_recovery")
        and not app_paths.portfolio_database(filename).exists()
    ),
    None,
)
if recovery_database:
    st.sidebar.warning(
        "Nenhuma carteira válida está disponível. Uma nova carteira de recuperação será criada; "
        "o arquivo inválido será preservado para restauração manual ou por backup."
    )

if not is_cloud:
    # 2. Sidebar Selector
    st.sidebar.markdown("### 🗃️ Gerenciar Carteiras")
    deletion_success = st.session_state.pop(SESSION_PORTFOLIO_DELETION_SUCCESS, None)
    if deletion_success:
        st.sidebar.success(deletion_success)

    requested_db = st.session_state.get("active_db", "portfolio.db")
    active_db = app_paths.choose_portfolio(requested_db, db_files)
    if active_db != requested_db:
        SessionManager.switch_portfolio(active_db)
        st.rerun()
    if not app_paths.portfolio_database(active_db).exists():
        SessionManager.reset_portfolio_state()

    # User-friendly labels mapping for files
    labels = {
        f: (
            "Carteira Principal"
            if f == "portfolio.db"
            else "Carteira de Recuperação"
            if f.startswith("portfolio_recovery")
            else f"Carteira: {f[10:-3].title()}"
            if f.startswith("portfolio_")
            else f
        )
        for f in db_files
    }

    selected_db = st.sidebar.selectbox(
        "Selecione a Carteira Ativa",
        options=db_files,
        format_func=lambda x: labels.get(x, x),
        index=db_files.index(active_db),
    )

    # Switch before rendering destructive controls so their target is unambiguous.
    if selected_db != active_db:
        SessionManager.switch_portfolio(selected_db)
        st.rerun()

    # Option to create a new database
    st.sidebar.markdown("---")
    st.sidebar.markdown("#### ➕ Nova Carteira")
    new_db_name = st.sidebar.text_input(
        "Nome da Nova Carteira", placeholder="Ex: compania, esposa", label_visibility="collapsed"
    )
    if st.sidebar.button("Criar Nova Carteira", use_container_width=True) and new_db_name:
        clean_name = "".join([c for c in new_db_name if c.isalnum() or c in ("_", "-")]).strip()
        if clean_name:
            new_filename = f"portfolio_{clean_name.lower()}.db"
            new_filepath = app_paths.portfolio_database(new_filename)
            # Initialize tables
            app_paths.prepare_portfolio_creation(new_filename)
            temp_db = DatabaseManager(personal_db=new_filepath)
            temp_db.init_personal_db()
            SessionManager.switch_portfolio(new_filename)
            st.toast(f"✅ Carteira '{clean_name}' criada com sucesso!")
            st.rerun()

    st.sidebar.markdown("---")
    with st.sidebar.expander("🗑️ Excluir carteira"):
        deletion_target = st.selectbox(
            "Selecione a carteira para excluir",
            options=db_files,
            format_func=lambda filename: labels.get(filename, filename),
            index=db_files.index(active_db),
            key=WIDGET_PORTFOLIO_DELETION_TARGET,
            on_change=lambda: st.session_state.pop(
                WIDGET_PORTFOLIO_DELETE_CONFIRMATION,
                None,
            ),
        )
        st.write(f"**Arquivo:** {deletion_target}")
        st.warning(
            "A carteira e seus arquivos auxiliares serão movidos para um backup local. "
            "Esse backup será mantido até que você o remova manualmente."
        )
        st.markdown(f"Digite **{deletion_target}** para confirmar")
        deletion_confirmation = st.text_input(
            "Confirmação da exclusão",
            key=WIDGET_PORTFOLIO_DELETE_CONFIRMATION,
            label_visibility="collapsed",
        )
        is_last_portfolio = len(db_files) <= 1
        if is_last_portfolio:
            st.info("A última carteira válida não pode ser excluída.")
        if st.button(
            "Mover carteira para backup",
            key=f"delete_portfolio_{deletion_target}",
            type="primary",
            disabled=is_last_portfolio,
            use_container_width=True,
        ):
            deletion_result = app_paths.delete_portfolio(
                deletion_target,
                deletion_confirmation,
            )
            if deletion_result.deleted:
                remaining_files = list(app_paths.portfolio_options(app_paths.inspect_portfolios()))
                next_active_db = app_paths.choose_portfolio(active_db, remaining_files)
                SessionManager.switch_portfolio(next_active_db)
                st.session_state.pop(WIDGET_PORTFOLIO_DELETION_TARGET, None)
                st.session_state.pop(WIDGET_PORTFOLIO_DELETE_CONFIRMATION, None)
                st.session_state[SESSION_PORTFOLIO_DELETION_SUCCESS] = (
                    f"{deletion_result.message} Local: {deletion_result.backup_dir}"
                )
                st.rerun()
            else:
                st.error(deletion_result.message)

    current_active_db = active_db
else:
    current_active_db = "portfolio.db"

if is_cloud:

    def resolve_demo_database():
        """Resolve the database from the Streamlit context of the current connection."""
        session_paths = runtime_paths.for_demo_session(st.session_state["session_id"])
        return session_paths.portfolio_database("portfolio.db")

    db.personal_db = resolve_demo_database

    def resolve_demo_catalog():
        """Resolve the catalog from the Streamlit context of the current operation."""
        session_paths = runtime_paths.for_demo_session(st.session_state["session_id"])
        return session_paths.catalog_file

    catalog_path = resolve_demo_catalog
else:
    db.personal_db = app_paths.portfolio_database(current_active_db)
    catalog_path = app_paths.catalog_file
MarketData.configure_catalog(catalog_path)


def guard_portfolio_generation(database_path):
    """Restart stale sessions before they can access a replacement portfolio."""
    generation = ApplicationPaths.database_generation(database_path)
    if SessionManager.refresh_portfolio_generation(generation):
        st.rerun()


db.connection_guard = guard_portfolio_generation
db.init_personal_db()

st.set_page_config(page_title=f"Renda Perene v{get_app_version()}", page_icon="💼", layout="wide")

# Configure dependency injection adapters for Streamlit presentation environment
from core.utils.b3_parser import B3ExcelParserAdapter
from services.assets_service import AssetService
from services.goals_service import GoalService
from services.planning_service import SimulationService
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.cached_market_data import StreamlitCachedMarketData

AssetService.set_adapters(
    catalog_repo=AssetsCatalogDAO(catalog_path),
    market_data_api=StreamlitCachedMarketData,
    excel_parser=B3ExcelParserAdapter(),
    planning_provider=SimulationService.get_default(),
)
SimulationService.set_adapters(portfolio_provider=AssetService.get_default())
GoalService.set_adapters(
    portfolio_provider=AssetService.get_default(),
    planning_provider=SimulationService.get_default(),
)
ShareQuantityGoalService.set_adapters(
    portfolio_provider=AssetService.get_default(),
    market_data_api=StreamlitCachedMarketData,
    planning_provider=SimulationService.get_default(),
)

# Session state must be initialized before rendering any view
SessionManager.initialize()

if is_cloud:
    st.warning(
        "⚠️ **Ambiente de Demonstração Interativa:** Os dados financeiros exibidos são fictícios e criados para fins de testes. Sinta-se livre para alterar, simular e importar dados; suas alterações serão isoladas de outros usuários e redefinidas ao atualizar a página."
    )

st.title(f"💼 Renda Perene v{get_app_version()}")

from core.strings import TAB_ASSETS, TAB_DASHBOARD, TAB_PLANNING
from views.assets_view import AssetsView
from views.dashboard_view import DashboardView
from views.planning_view import PlanningView

selected_tab = st.segmented_control(
    "Navegação Principal",
    options=[TAB_DASHBOARD, TAB_ASSETS, TAB_PLANNING],
    default=TAB_DASHBOARD,
    label_visibility="collapsed",
)

if not selected_tab:
    selected_tab = TAB_DASHBOARD

if selected_tab == TAB_DASHBOARD:
    DashboardView().render()
elif selected_tab == TAB_ASSETS:
    AssetsView().render()
elif selected_tab == TAB_PLANNING:
    PlanningView().render()
