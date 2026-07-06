import streamlit as st
import importlib
from core.database import db
from core.utils import SessionManager, get_app_version

db.init_personal_db()

st.set_page_config(page_title=f"Renda Perene v{get_app_version()}", page_icon="💼", layout="wide")

# Session state must be initialized before rendering any view
SessionManager.initialize()

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
