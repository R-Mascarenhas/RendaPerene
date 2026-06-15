import streamlit as st
from core.database import db
from core.utils import SessionManager

# Initialize both local databases at root level
db.init_assets_db()
db.init_personal_db()

# Base Page Configuration
st.set_page_config(page_title="Minha Carteira", page_icon="💼", layout="wide")

# Initialize global session state (must occur before rendering any View)
SessionManager.initialize()

st.title("💼 Carteira de Investimentos")

# Import Views from Domains
from dashboard.view import DashboardView
from lancamentos.view import LancamentosView
from planning.view import PlanningView

# Create 3 main tabs
tab_dashboard, tab_lancamentos, tab_planning = st.tabs([
    "📊 Dashboard (Resumo)", 
    "📝 Lançamentos & B3", 
    "🎯 Planejamento"
])

# Clean MVC Routing
with tab_dashboard:
    DashboardView().render()

with tab_lancamentos:
    LancamentosView().render()

with tab_planning:
    PlanningView().render()
