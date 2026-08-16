import streamlit as st
import importlib
import os
import glob
from core.database import db, DatabaseManager
from core.utils import SessionManager, get_app_version

# Detect if running in public shared cloud environments
is_cloud = (
    "STREAMLIT_SHARING_MODE" in os.environ or
    os.path.abspath(".").startswith("/mount") or
    "/mount/" in os.path.abspath(".")
)

# 1. Scan for available databases inside 'database/' folder (if not in public cloud)
db_files = []
if not is_cloud:
    if os.path.exists("database"):
        all_dbs = glob.glob("database/*.db")
        for d in all_dbs:
            name = os.path.basename(d)
            # Exclude temp, bkp, and specific reference demo files
            if name.endswith(".db") and "demo" not in name:
                db_files.append(name)

    # Ensure at least 'portfolio.db' is listed
    if "portfolio.db" not in db_files:
        db_files.append("portfolio.db")

    db_files = sorted(list(set(db_files)))

    # 2. Sidebar Selector
    st.sidebar.markdown("### 🗃️ Gerenciar Carteiras")

    active_db = st.session_state.get("active_db", "portfolio.db")
    if active_db not in db_files:
        active_db = "portfolio.db"

    # User-friendly labels mapping for files
    labels = {
        f: ("Carteira Principal" if f == "portfolio.db" else
            f"Carteira: {f[10:-3].title()}" if f.startswith("portfolio_") else f
           ) for f in db_files}

    selected_db = st.sidebar.selectbox(
        "Selecione a Carteira Ativa",
        options=db_files,
        format_func=lambda x: labels.get(x, x),
        index=db_files.index(active_db)
    )

    # Option to create a new database
    st.sidebar.markdown("---")
    st.sidebar.markdown("#### ➕ Nova Carteira")
    new_db_name = st.sidebar.text_input(
        "Nome da Nova Carteira",
        placeholder="Ex: compania, esposa",
        label_visibility="collapsed")
    if st.sidebar.button("Criar Nova Carteira", use_container_width=True):
        if new_db_name:
            clean_name = "".join([c for c in new_db_name if c.isalnum() or c in ("_", "-")]).strip()
            if clean_name:
                new_filename = f"portfolio_{clean_name.lower()}.db"
                new_filepath = f"database/{new_filename}"
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
        for key in ["db_loaded", "birth_date", "retirement_age", "desired_income_mw",
                    "annual_interest_rate", "mw_value", "initial_equity",
                    "desired_income_type", "desired_income_fixed",
                    "ceiling_model_selection", "bazin_target_yield",
                    "bazin_target_spread", "planning_start_date",
                    "planning_start_date_enabled"]:
            st.session_state.pop(key, None)
        st.rerun()

    current_active_db = st.session_state.get("active_db", "portfolio.db")
    db.personal_db = f"database/{current_active_db}"

db.init_personal_db()

st.set_page_config(page_title=f"Renda Perene v{get_app_version()}", page_icon="💼", layout="wide")

# Session state must be initialized before rendering any view
SessionManager.initialize()

if is_cloud:
    st.warning("⚠️ **Ambiente de Demonstração Interativa:** Os dados financeiros exibidos são fictícios e criados para fins de testes. Sinta-se livre para alterar, simular e importar dados; suas alterações serão isoladas de outros usuários e redefinidas ao atualizar a página.")

st.title(f"💼 Renda Perene v{get_app_version()}")

from views.dashboard_view import DashboardView
from views.assets_view import AssetsView
from views.planning_view import PlanningView
from core.strings import TAB_DASHBOARD, TAB_ASSETS, TAB_PLANNING

selected_tab = st.segmented_control(
    "Navegação Principal",
    options=[
        TAB_DASHBOARD,
        TAB_ASSETS,
        TAB_PLANNING
    ],
    default=TAB_DASHBOARD,
    label_visibility="collapsed"
)

if not selected_tab:
    selected_tab = TAB_DASHBOARD

if selected_tab == TAB_DASHBOARD:
    DashboardView().render()
elif selected_tab == TAB_ASSETS:
    AssetsView().render()
elif selected_tab == TAB_PLANNING:
    PlanningView().render()
