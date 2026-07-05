import streamlit as st
import importlib
from core.database import db
from core.utils import SessionManager

# Initialize both local databases at root level
db.init_personal_db()

# Base Page Configuration
st.set_page_config(page_title="Renda Perene", page_icon="💼", layout="wide")

# Initialize global session state (must occur before rendering any View)
SessionManager.initialize()

st.title("💼 Renda Perene")

# Import Views from Domains (SOLID compliant imports)
from views.dashboard_view import DashboardView
from views.assets_view import AssetsView
from views.planning_view import PlanningView
from core.strings import TAB_DASHBOARD, TAB_ASSETS, TAB_PLANNING

# Create 3 main tabs using a premium native segmented control for isolated, lazy-loaded rendering (blazing fast and beautiful!)
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

# Clean MVC Routing with strict isolation
if selected_tab == TAB_DASHBOARD:
    DashboardView().render()
elif selected_tab == TAB_ASSETS:
    AssetsView().render()
elif selected_tab == TAB_PLANNING:
    PlanningView().render()
