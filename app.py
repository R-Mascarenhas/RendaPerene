import os
import uuid

import streamlit as st

from core.application_paths import ApplicationPaths
from core.daos.assets_catalog_dao import AssetsCatalogDAO
from core.database import DatabaseManager, db
from core.utils import SessionManager, get_app_version
from core.utils.market_data import MarketData

# Detect if running in public shared cloud environments
is_cloud = (
    "STREAMLIT_SHARING_MODE" in os.environ
    or os.path.abspath(".").startswith("/mount")
    or "/mount/" in os.path.abspath(".")
)

runtime_paths = ApplicationPaths.discover()
app_paths = runtime_paths
if is_cloud:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    app_paths = app_paths.for_demo_session(st.session_state["session_id"])
    app_paths.prepare(app_paths.bundled_resource("database/portfolio_demo.db"))
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
            for source in selected_legacy:
                result = app_paths.migrate_legacy_database(source)
                if result.migrated:
                    st.sidebar.success(f"{source.name}: {result.message}")
                else:
                    st.sidebar.error(f"{source.name}: {result.message}")

inventory = app_paths.inspect_portfolios()
if inventory.invalid:
    invalid_names = ", ".join(path.name for path in inventory.invalid)
    st.sidebar.error(
        f"Bancos SQLite inválidos foram ignorados: {invalid_names}. "
        "Restaure uma cópia válida a partir da pasta de backups."
    )

db_files = [path.name for path in inventory.valid]
default_database = app_paths.portfolio_database("portfolio.db")
if not default_database.exists():
    db_files.append("portfolio.db")
if not db_files:
    st.error("Nenhuma carteira SQLite válida está disponível.")
    st.stop()
db_files = sorted(set(db_files))

if not is_cloud:
    # 2. Sidebar Selector
    st.sidebar.markdown("### 🗃️ Gerenciar Carteiras")

    active_db = st.session_state.get("active_db", "portfolio.db")
    if active_db not in db_files:
        active_db = "portfolio.db"

    # User-friendly labels mapping for files
    labels = {
        f: (
            "Carteira Principal"
            if f == "portfolio.db"
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
            temp_db = DatabaseManager(personal_db=new_filepath)
            temp_db.init_personal_db()
            st.session_state["active_db"] = new_filename
            st.toast(f"✅ Carteira '{clean_name}' criada com sucesso!")
            st.rerun()

    # 3. Handle database switch
    if selected_db != active_db:
        st.session_state["active_db"] = selected_db
        # Purge current session loaded state & values to trigger fresh load
        for key in [
            "db_loaded",
            "birth_date",
            "retirement_age",
            "desired_income_mw",
            "annual_interest_rate",
            "mw_value",
            "initial_equity",
            "desired_income_type",
            "desired_income_fixed",
            "ceiling_model_selection",
            "bazin_target_yield",
            "bazin_target_spread",
            "planning_start_date",
            "planning_start_date_enabled",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

    current_active_db = st.session_state.get("active_db", "portfolio.db")
else:
    current_active_db = "portfolio.db"

if is_cloud:

    def resolve_demo_database():
        """Resolve the database from the Streamlit context of the current connection."""
        session_paths = runtime_paths.for_demo_session(st.session_state["session_id"])
        return session_paths.portfolio_database("portfolio.db")

    db.personal_db = resolve_demo_database
else:
    db.personal_db = app_paths.portfolio_database(current_active_db)
MarketData.configure_catalog(app_paths.catalog_file)

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
    catalog_repo=AssetsCatalogDAO(app_paths.catalog_file),
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
