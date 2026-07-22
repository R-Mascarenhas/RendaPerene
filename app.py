import streamlit as st
import importlib
from core.database import db
from core.utils import SessionManager, get_app_version

db.init_personal_db()

st.set_page_config(page_title=f"Renda Perene v{get_app_version()}", page_icon="💼", layout="wide")

# Session state must be initialized before rendering any view
SessionManager.initialize()

import os
# Detect if running in public shared cloud environments
is_cloud = (
    "STREAMLIT_SHARING_MODE" in os.environ or
    os.path.abspath(".").startswith("/mount") or
    "/mount/" in os.path.abspath(".")
)
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
