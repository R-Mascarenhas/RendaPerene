import streamlit as st
import importlib
from core.database import db
from core.utils import SessionManager

# Initialize both local databases at root level
db.init_personal_db()

# Base Page Configuration
st.set_page_config(page_title="Minha Carteira", page_icon="💼", layout="wide")

# Initialize global session state (must occur before rendering any View)
SessionManager.initialize()

st.title("💼 Carteira de Investimentos")

# Import Views from Domains (SOLID compliant imports)
from views.dashboard_view import DashboardView
from views.assets_view import AssetsView
from views.planning_view import PlanningView

# Create 3 main tabs (Optimized user labels)
tab_dashboard, tab_assets, tab_planning = st.tabs([
    "📊 Dashboard",
    "📝 Ativos",
    "🎯 Planejamento"
])

# Clean MVC Routing
with tab_dashboard:
    DashboardView().render()

with tab_assets:
    AssetsView().render()

with tab_planning:
    PlanningView().render()
