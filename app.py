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

# Import Views from Domains
from dashboard.dashboard_view import DashboardView
from lancamentos.transactions_view import LancamentosView
from planning.planning_view import PlanningView

# Create 3 main tabs
tab_dashboard, tab_planning, tab_lancamentos = st.tabs([
    "📊 Dashboard",
    "🎯 Planejamento",
    "📝 Ativos"
])

# Clean MVC Routing
with tab_dashboard:
    DashboardView().render()

with tab_planning:
    PlanningView().render()

with tab_lancamentos:
    LancamentosView().render()
