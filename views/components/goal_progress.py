import html

import streamlit as st


class GoalProgressBar:
    """Renders goal completion and its overachievement in a reusable bar."""

    @staticmethod
    def render(progress: float, tooltip: str | None = None) -> None:
        """Renders 0-100% in blue and up to another 100% of excess in green."""
        base_width = min(100.0, max(0.0, progress))
        excess_width = min(100.0, max(0.0, progress - 100.0))
        tooltip_attribute = (
            f' title="{html.escape(tooltip, quote=True)}"' if tooltip is not None else ""
        )
        st.markdown(
            f"""
            <div role="progressbar" aria-valuenow="{progress:.1f}" aria-valuemin="0"
                 aria-label="Progresso da meta: {progress:.1f}%"{tooltip_attribute}
                 style="position:relative; width:100%; height:0.7rem; overflow:hidden;
                        border-radius:0.35rem; background:rgba(128,128,128,0.25);">
                <div style="position:absolute; height:100%; width:{base_width:.2f}%;
                            background:#1f77b4;"></div>
                <div style="position:absolute; height:100%; width:{excess_width:.2f}%;
                            background:#2ca02c;"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
