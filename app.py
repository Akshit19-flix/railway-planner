"""
Indian Railways Train Availability Planner — Flixbus-themed UI with Plotly charts.
"""

import io
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st

from aggregator import AggregatedResults, WEEKDAY_NAMES
from scraper import scrape_schedule, scrape_availability_range, CLASS_ORDER
from stations import find_station_code, is_station_code

# ── Flixbus palette ───────────────────────────────────────────────────────────
FX_GREEN  = "#73D700"
FX_DARK   = "#1A1A2E"
FX_GREY   = "#353535"
FX_MID    = "#6B6B6B"
FX_LIGHT  = "#F5F7FA"
FX_WHITE  = "#FFFFFF"
FX_AMBER  = "#F5A623"
FX_RED    = "#D0021B"
FX_GREEN2 = "#2E7D32"
FX_CARD   = "#FFFFFF"

st.set_page_config(
    page_title="Railways Availability Planner",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(f"""
<style>
/* ── Base — light background, dark text everywhere in main area ── */
html, body {{ font-family: "Segoe UI", Arial, sans-serif; }}
.stApp {{ background-color: {FX_LIGHT}; }}
/* Ensure all regular text in main area is dark */
.stApp p, .stApp span, .stApp div, .stApp label,
.stMarkdown, .stMarkdown p {{ color: {FX_DARK}; }}
/* Fix Streamlit's own metric/caption text */
[data-testid="stMetricValue"] {{ color: {FX_DARK} !important; }}
[data-testid="stMetricLabel"] {{ color: {FX_MID}  !important; }}
[data-testid="stCaptionContainer"] p {{ color: {FX_MID} !important; }}

/* ── Top header ── */
.fx-header {{
    background: linear-gradient(135deg, {FX_DARK} 0%, #16213e 100%);
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.fx-header .logo {{
    background: {FX_GREEN};
    color: {FX_DARK} !important;
    font-weight: 900;
    font-size: 1.05rem;
    padding: 7px 15px;
    border-radius: 7px;
    letter-spacing: 1.5px;
    flex-shrink: 0;
}}
.fx-header .title {{ font-size: 1.3rem; font-weight: 700; color: {FX_WHITE} !important; }}
.fx-header .sub   {{ font-size: 0.8rem; color: #8899aa !important; margin-top: 3px; }}

/* ── KPI cards ── */
.kpi-row {{ display: flex; gap: 16px; margin-bottom: 8px; }}
.kpi-card {{
    flex: 1; background: {FX_WHITE};
    border-radius: 12px; padding: 20px 24px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    border-top: 4px solid {FX_GREEN}; text-align: center;
}}
.kpi-card .kval {{ font-size: 2.2rem; font-weight: 800; color: {FX_DARK} !important; line-height: 1; }}
.kpi-card .klbl {{ font-size: 0.78rem; color: {FX_MID} !important; margin-top: 6px;
                   letter-spacing: 0.5px; text-transform: uppercase; }}

/* ── Section headings ── */
.fx-section {{
    font-size: 1rem; font-weight: 700; color: {FX_DARK} !important;
    display: flex; align-items: center; gap: 8px;
    margin: 24px 0 12px 0; padding-bottom: 6px;
    border-bottom: 3px solid {FX_GREEN};
}}

/* ── Suggestion cards — explicit colours so dark sidebar CSS can't bleed in ── */
.sug-card {{
    border-radius: 10px; padding: 14px 18px; margin-bottom: 12px;
    display: flex; align-items: flex-start; gap: 14px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08);
}}
.sug-card .sug-icon {{ font-size: 1.6rem; flex-shrink: 0; line-height: 1; margin-top: 2px; }}
.sug-card .sug-title {{ font-weight: 700; font-size: 0.95rem; margin-bottom: 3px; color: {FX_DARK} !important; }}
.sug-card .sug-body  {{ font-size: 0.85rem; line-height: 1.6; color: #333 !important; }}
.sug-high {{ background: #FFF0F0 !important; border-left: 5px solid {FX_RED}; }}
.sug-med  {{ background: #FFFAEB !important; border-left: 5px solid {FX_AMBER}; }}
.sug-low  {{ background: #F1F8E9 !important; border-left: 5px solid {FX_GREEN}; }}
.sug-info {{ background: #EEF4FF !important; border-left: 5px solid #4A6CF7; }}

/* ── Sidebar — dark theme, scoped tightly ── */
section[data-testid="stSidebar"] {{
    background: {FX_DARK} !important;
}}
/* Only direct text labels and paragraphs inside sidebar get white */
section[data-testid="stSidebar"] > div > div > div > div p,
section[data-testid="stSidebar"] > div > div > div > div span,
section[data-testid="stSidebar"] > div > div > div > div label,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] .stMarkdown p {{
    color: {FX_WHITE} !important;
}}
/* Sidebar inputs */
section[data-testid="stSidebar"] input[type="text"] {{
    background: #242440 !important;
    color: {FX_WHITE} !important;
    border: 1px solid #556 !important;
    border-radius: 6px !important;
}}
/* Sidebar date picker text */
section[data-testid="stSidebar"] [data-testid="stDateInput"] input {{
    color: {FX_WHITE} !important;
    background: #242440 !important;
}}
/* Sidebar checkbox label */
section[data-testid="stSidebar"] [data-testid="stCheckbox"] label span {{
    color: {FX_WHITE} !important;
}}
/* Sidebar caption */
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
    color: #aabbc0 !important;
}}

/* ── Search button ── */
section[data-testid="stSidebar"] button[kind="primary"] {{
    background: {FX_GREEN} !important;
    color: {FX_DARK} !important;
    font-weight: 800 !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 1rem !important;
}}
section[data-testid="stSidebar"] button[kind="primary"]:hover {{
    background: #5CB800 !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    background: {FX_DARK};
    border-radius: 10px 10px 0 0;
    padding: 6px 8px 0;
    gap: 4px;
}}
.stTabs [data-baseweb="tab"] {{
    color: #aabbcc !important;
    font-weight: 600; font-size: 0.88rem;
    border-radius: 7px 7px 0 0; padding: 8px 18px;
}}
.stTabs [aria-selected="true"] {{
    background: {FX_GREEN} !important;
    color: {FX_DARK} !important;
    font-weight: 700 !important;
}}

/* ── Progress bar ── */
.stProgress > div > div > div {{ background-color: {FX_GREEN} !important; }}

/* ── Info / success / error banners — keep their own colours ── */
[data-testid="stAlert"] p {{ color: inherit !important; }}
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="fx-header">
  <div class="logo">FLIX</div>
  <div>
    <div class="title">Railways Availability Planner</div>
    <div class="sub">Train occupancy analysis · Bus deployment planning · Powered by erail.in / IRCTC</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Search")
    origin_input      = st.text_input("From Station", placeholder="e.g. New Delhi / NDLS")
    destination_input = st.text_input("To Station",   placeholder="e.g. Mumbai Central / BCT")
    start_date = st.date_input(
        "From Date", value=date.today() + timedelta(days=1),
        min_value=date.today(), max_value=date.today() + timedelta(days=120),
    )
    end_date = st.date_input(
        "To Date", value=date.today() + timedelta(days=30),
        min_value=date.today() + timedelta(days=1),
        max_value=date.today() + timedelta(days=120),
    )
    fetch_avail = st.checkbox(
        "Fetch live seat availability", value=True,
        help="Gets real seat counts per date (~30–60 s with HTTP, ~2 min with browser fallback).",
    )
    run_button = st.button("Search Trains", use_container_width=True, type="primary")
    st.markdown("---")
    st.markdown("**Reading seat values**")
    st.caption(
        "🟢 `92` — 92 seats available\n\n"
        "🟡 `R7` — RAC (likely confirmed)\n\n"
        "🟡 `P12` — Pooled quota\n\n"
        "🔴 `WL#` — Waitlisted\n\n"
        "🔴 `NA` — Full / no quota\n\n"
        "`—` — Class not on this train"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def resolve_station(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    if is_station_code(raw):
        return raw.upper(), raw.upper()
    return find_station_code(raw)


def _avail_score(val) -> Optional[float]:
    if val in ("—", "", None):
        return None
    s = str(val)
    if s == "NA" or s.startswith("WL"):
        return 1.0
    if s.startswith("R"):
        try:   return min(1.0, 0.80 + int(s[1:]) * 0.01)
        except ValueError: return 0.85
    if s.startswith("P"):
        try:   return max(0.0, 1.0 - int(s[1:]) / 60)
        except ValueError: return 0.65
    try:    return max(0.0, 1.0 - int(s) / 150)
    except ValueError: return None


def _cell_color(val) -> str:
    s = str(val) if val else ""
    if s in ("—", "", "None"):       return "color:#aaa"
    if s == "NA" or s.startswith("WL"):
        return f"background:#FFE0E0;color:{FX_RED};font-weight:700"
    if s.startswith("R") or s.startswith("P"):
        return "background:#FFF3CD;color:#856404"
    try:
        n = int(s)
        if n >= 50:  return f"background:#E8F5E9;color:{FX_GREEN2}"
        if n >= 10:  return "background:#FFF3CD;color:#856404"
        return f"background:#FFE0E0;color:{FX_RED}"
    except ValueError:
        return ""


def _demand_style(val):
    return {
        "High":   f"background:#FFE0E0;color:{FX_RED};font-weight:700",
        "Medium": "background:#FFF3CD;color:#856404;font-weight:700",
        "Low":    f"background:#E8F5E9;color:{FX_GREEN2};font-weight:700",
    }.get(val, "")


def _sug_card(icon: str, title: str, body: str, level: str) -> str:
    cls = {"high": "sug-high", "med": "sug-med", "low": "sug-low"}.get(level, "sug-info")
    return (
        f'<div class="sug-card {cls}">'
        f'  <div class="sug-icon">{icon}</div>'
        f'  <div>'
        f'    <div class="sug-title">{title}</div>'
        f'    <div class="sug-body">{body}</div>'
        f'  </div>'
        f'</div>'
    )


# ── Plotly chart builders ─────────────────────────────────────────────────────

_PLOTLY_LAYOUT = dict(
    paper_bgcolor=FX_WHITE, plot_bgcolor=FX_WHITE,
    font=dict(family="Segoe UI, Arial", color=FX_GREY, size=12),
    margin=dict(l=10, r=10, t=48, b=10),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
)
_GRID = dict(showgrid=True, gridcolor="#F0F0F0", zeroline=False)
_NO_GRID = dict(showgrid=False, zeroline=False)

DEMAND_COLORS = {"High": FX_RED, "Medium": FX_AMBER, "Low": FX_GREEN}


def _chart_weekday_combo(analysis: list[dict]) -> go.Figure:
    days   = [r["day"] for r in analysis]
    trains = [r["avg_trains"] for r in analysis]
    occ    = [r["avg_occupancy"] for r in analysis]
    colors = [DEMAND_COLORS.get(r["demand_level"], FX_GREEN) for r in analysis]
    has_occ = any(o is not None for o in occ)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=days, y=trains,
        name="Avg Trains / Day",
        marker_color=colors,
        marker_line_color=FX_WHITE,
        marker_line_width=1.5,
        text=[f"{v:.0f}" for v in trains],
        textposition="outside",
        textfont=dict(size=11, color=FX_DARK, family="Segoe UI"),
        hovertemplate="%{x}<br><b>%{y:.1f} trains</b><extra></extra>",
    ), secondary_y=False)

    if has_occ:
        occ_vals = [o if o is not None else 0 for o in occ]
        fig.add_trace(go.Scatter(
            x=days, y=occ_vals,
            name="Avg Occupancy %",
            mode="lines+markers+text",
            line=dict(color=FX_DARK, width=2.5),
            marker=dict(size=9, color=FX_DARK, symbol="circle",
                        line=dict(width=2, color=FX_WHITE)),
            text=[f"{v}%" if occ[i] is not None else "" for i, v in enumerate(occ_vals)],
            textposition="top center",
            textfont=dict(size=10, color=FX_DARK, family="Segoe UI"),
            hovertemplate="%{x}<br><b>%{y}% occupancy</b><extra></extra>",
        ), secondary_y=True)

        fig.add_hline(y=70, line_dash="dot", line_color=FX_RED,   line_width=1,
                      annotation_text="High", annotation_font_size=9,
                      annotation_font_color=FX_RED, secondary_y=True)
        fig.add_hline(y=40, line_dash="dot", line_color=FX_AMBER, line_width=1,
                      annotation_text="Med",  annotation_font_size=9,
                      annotation_font_color=FX_AMBER, secondary_y=True)

    fig.update_layout(
        title=dict(text="Weekday Demand — Trains & Occupancy", font=dict(size=14, color=FX_DARK)),
        bargap=0.3,
        yaxis=dict(title="Avg Trains / Day", **_GRID),
        yaxis2=dict(title="Avg Occupancy %", range=[0, 130], **_GRID),
        **_PLOTLY_LAYOUT,
    )
    return fig


def _chart_weekly(weekly: list[dict]) -> go.Figure:
    labels  = [r["date_range"] for r in weekly]
    trains  = [r["total_trains"] for r in weekly]
    occ     = [r["avg_occupancy"] for r in weekly]
    colors  = [DEMAND_COLORS.get(r["demand_level"], FX_GREEN) if r["demand_level"] != "—"
               else FX_GREEN for r in weekly]
    has_occ = any(o is not None for o in occ)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=labels, y=trains,
        name="Total Train-Day Slots",
        marker_color=colors,
        marker_line_color=FX_WHITE, marker_line_width=1.5,
        text=trains, textposition="outside",
        textfont=dict(size=11, color=FX_DARK),
        hovertemplate="%{x}<br><b>%{y} train-days</b><extra></extra>",
    ), secondary_y=False)

    if has_occ:
        occ_vals = [o if o is not None else 0 for o in occ]
        fig.add_trace(go.Scatter(
            x=labels, y=occ_vals,
            name="Avg Occupancy %",
            mode="lines+markers+text",
            line=dict(color=FX_DARK, width=2.5),
            marker=dict(size=9, color=FX_DARK, line=dict(width=2, color=FX_WHITE)),
            text=[f"{v}%" if occ[i] is not None else "" for i, v in enumerate(occ_vals)],
            textposition="top center",
            textfont=dict(size=10, color=FX_DARK),
            hovertemplate="%{x}<br><b>%{y}% occupancy</b><extra></extra>",
        ), secondary_y=True)

    fig.update_layout(
        title=dict(text="Week-by-Week Demand", font=dict(size=14, color=FX_DARK)),
        bargap=0.35,
        xaxis=dict(tickangle=-20, **_GRID),
        yaxis=dict(title="Total Train-Day Slots", **_GRID),
        yaxis2=dict(title="Avg Occupancy %", range=[0, 130], **_GRID),
        **_PLOTLY_LAYOUT,
    )
    return fig


def _chart_heatmap(results: AggregatedResults, cls: str, max_trains: int) -> go.Figure:
    data        = results.availability_heatmap(cls)
    matrix      = data["matrix"]
    date_labels = data["date_labels"]
    train_keys  = data["train_keys"][:max_trains]
    row_labels  = [f"{num} {name}" for num, name in train_keys]

    if not row_labels or not date_labels:
        fig = go.Figure()
        fig.add_annotation(text="No data available", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14))
        return fig

    Z       = []
    Z_text  = []
    for num, name in train_keys:
        label = f"{num} {name}"
        row_z, row_t = [], []
        for col in date_labels:
            val   = matrix.get(label, {}).get(col)
            score = _avail_score(val)
            row_z.append(score if score is not None else -0.05)
            row_t.append(val if val not in (None, "—") else "")
        Z.append(row_z)
        Z_text.append(row_t)

    colorscale = [
        [0.0,  FX_GREEN],
        [0.45, "#B5D900"],
        [0.65, FX_AMBER],
        [1.0,  FX_RED],
    ]

    fig = go.Figure(go.Heatmap(
        z=Z, x=date_labels, y=row_labels,
        text=Z_text, texttemplate="%{text}",
        textfont=dict(size=8, family="Segoe UI"),
        colorscale=colorscale,
        zmin=0, zmax=1,
        zmid=0.5,
        colorbar=dict(
            title=dict(text="Load", side="right"),
            tickvals=[0, 0.5, 1],
            ticktext=["Free", "Limited", "Full"],
            thickness=14,
            len=0.85,
        ),
        hovertemplate="<b>%{y}</b><br>%{x}<br>%{text}<extra></extra>",
    ))

    fig_h = max(350, len(row_labels) * 26)
    fig.update_layout(
        title=dict(text=f"{cls} class — Seat Availability (green=free, red=full)",
                   font=dict(size=14, color=FX_DARK)),
        xaxis=dict(tickangle=-45, tickfont=dict(size=9), **_NO_GRID),
        yaxis=dict(tickfont=dict(size=9), autorange="reversed", **_NO_GRID),
        height=fig_h,
        **_PLOTLY_LAYOUT,
    )
    return fig


def _chart_pressure_gauge(pressure: dict[str, Optional[float]]) -> go.Figure:
    """Radial gauge-style bar chart for weekday pressure."""
    days   = WEEKDAY_NAMES
    vals   = [int((pressure.get(d) or 0) * 100) for d in days]
    colors = [FX_RED if v >= 70 else FX_AMBER if v >= 40 else FX_GREEN for v in vals]

    fig = go.Figure()
    for i, (day, val, col) in enumerate(zip(days, vals, colors)):
        fig.add_trace(go.Bar(
            x=[day], y=[val],
            marker_color=col,
            marker_line_color=FX_WHITE, marker_line_width=1.5,
            text=[f"{val}%"], textposition="outside",
            textfont=dict(size=12, color=FX_DARK, family="Segoe UI"),
            showlegend=False,
            hovertemplate=f"<b>{day}</b><br>{val}% occupancy<extra></extra>",
        ))

    fig.add_hline(y=70, line_dash="dot", line_color=FX_RED,   line_width=1.2,
                  annotation_text="High demand", annotation_position="right",
                  annotation_font_color=FX_RED, annotation_font_size=9)
    fig.add_hline(y=40, line_dash="dot", line_color=FX_AMBER, line_width=1.2,
                  annotation_text="Medium demand", annotation_position="right",
                  annotation_font_color=FX_AMBER, annotation_font_size=9)

    fig.update_layout(
        title=dict(text="Average Train Occupancy by Day of Week",
                   font=dict(size=14, color=FX_DARK)),
        yaxis=dict(title="Avg Occupancy %", range=[0, 120], **_GRID),
        xaxis=dict(**_NO_GRID),
        bargap=0.3,
        **_PLOTLY_LAYOUT,
    )
    return fig


# ── Tab renderers ─────────────────────────────────────────────────────────────

def render_overview(results: AggregatedResults) -> None:
    unique   = len(results.unique_trains())
    total_td = sum(s.count for s in results.date_wise.values())
    days     = (results.end_date - results.start_date).days + 1
    bus      = results.bus_suggestions()

    # KPI row
    st.markdown(
        f'<div class="kpi-row">'
        f'  <div class="kpi-card"><div class="kval">{unique}</div><div class="klbl">Unique Trains</div></div>'
        f'  <div class="kpi-card"><div class="kval">{total_td}</div><div class="klbl">Train-Day Slots</div></div>'
        f'  <div class="kpi-card"><div class="kval">{days}</div><div class="klbl">Days Covered</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="fx-section">📅 Weekday Demand</div>', unsafe_allow_html=True)
    analysis = results.combined_weekday_analysis()
    st.plotly_chart(_chart_weekday_combo(analysis), use_container_width=True)

    st.markdown('<div class="fx-section">📆 Week-by-Week Demand</div>', unsafe_allow_html=True)
    weekly = results.weekly_demand_analysis()
    st.plotly_chart(_chart_weekly(weekly), use_container_width=True)

    # Summary table
    st.markdown('<div class="fx-section">📋 Summary Table</div>', unsafe_allow_html=True)
    rows = []
    for r in analysis:
        occ = f"{r['avg_occupancy']}%" if r["avg_occupancy"] is not None else "—"
        rows.append({
            "Day":            r["day"],
            "Avg Trains/Day": r["avg_trains"],
            "Avg Occupancy":  occ,
            "Demand Level":   r["demand_level"],
        })
    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.map(_demand_style, subset=["Demand Level"]),
        use_container_width=True, hide_index=True,
    )


def render_bus(results: AggregatedResults) -> None:
    bus      = results.bus_suggestions()
    analysis = results.combined_weekday_analysis()
    pressure = bus["weekday_pressure"]

    st.markdown('<div class="fx-section">🚌 Bus Deployment Recommendations</div>',
                unsafe_allow_html=True)

    if not bus["has_avail_data"]:
        st.markdown(_sug_card(
            "ℹ️", "No occupancy data yet",
            "Run the search with <b>Fetch live seat availability</b> enabled "
            "to generate personalised bus deployment suggestions.",
            "info",
        ), unsafe_allow_html=True)
    else:
        # Occupancy gauge
        st.plotly_chart(_chart_pressure_gauge(pressure), use_container_width=True)

        st.markdown('<div class="fx-section">💡 Recommendations</div>', unsafe_allow_html=True)

        for sug in bus["suggestions"]:
            if "High demand" in sug:
                title = sug.split(":**")[0].replace("**", "").strip()
                body  = sug.split(":**", 1)[-1].strip() if ":**" in sug else sug
                st.markdown(_sug_card("🔴", title, body, "high"), unsafe_allow_html=True)
            elif "Peak dates" in sug:
                title = sug.split(":**")[0].replace("**", "").strip()
                body  = sug.split(":**", 1)[-1].strip() if ":**" in sug else sug
                st.markdown(_sug_card("📌", title, body, "high"), unsafe_allow_html=True)
            elif "Moderate demand" in sug:
                title = sug.split(":**")[0].replace("**", "").strip()
                body  = sug.split(":**", 1)[-1].strip() if ":**" in sug else sug
                st.markdown(_sug_card("🟡", title, body, "med"), unsafe_allow_html=True)
            elif "Low demand" in sug:
                title = sug.split(":**")[0].replace("**", "").strip()
                body  = sug.split(":**", 1)[-1].strip() if ":**" in sug else sug
                st.markdown(_sug_card("🟢", title, body, "low"), unsafe_allow_html=True)
            else:
                st.markdown(_sug_card("ℹ️", "Note", sug, "info"), unsafe_allow_html=True)

        # Action plan table
        st.markdown('<div class="fx-section">📋 Weekday Action Plan</div>', unsafe_allow_html=True)
        table_rows = []
        for r in analysis:
            day = r["day"]
            p   = pressure.get(day) or 0
            occ_str = f"{int(p*100)}%" if pressure.get(day) is not None else "—"
            if p >= 0.70:
                action, buses = "Deploy extra buses", "+2 buses per slot"
            elif p >= 0.40:
                action, buses = "Monitor closely",   "+1 bus on peak departures"
            else:
                action, buses = "Standard schedule", "No change needed"
            table_rows.append({
                "Day":             day,
                "Avg Trains":      r["avg_trains"],
                "Train Load":      occ_str,
                "Demand":          r["demand_level"],
                "Recommended Action": action,
                "Bus Adjustment":  buses,
            })
        df = pd.DataFrame(table_rows)
        st.dataframe(
            df.style.map(_demand_style, subset=["Demand"]),
            use_container_width=True, hide_index=True,
        )

        # Peak dates
        if bus["high_demand_dates"]:
            st.markdown('<div class="fx-section">📌 Peak Demand Dates</div>',
                        unsafe_allow_html=True)
            peak_rows = [{
                "Date":   d.strftime("%d %b %Y (%a)"),
                "Trains": cnt,
                "Load":   f"{int(p*100)}%",
                "Status": "High" if p >= 0.70 else "Medium",
            } for d, p, cnt in bus["high_demand_dates"]]
            pdf = pd.DataFrame(peak_rows)
            st.dataframe(
                pdf.style.map(_demand_style, subset=["Status"]),
                use_container_width=True, hide_index=True,
            )


def render_trains(results: AggregatedResults) -> None:
    st.markdown('<div class="fx-section">🚃 All Trains on this Route</div>',
                unsafe_allow_html=True)
    trains = results.unique_trains()
    if not trains:
        st.warning("No trains found.")
        return
    df = pd.DataFrame(trains)
    avail_cols = [c for c in CLASS_ORDER if c in df.columns]
    st.dataframe(
        df.style.map(lambda v: _cell_color(str(v)), subset=avail_cols),
        use_container_width=True, hide_index=True,
    )


def render_heatmap(results: AggregatedResults) -> None:
    st.markdown('<div class="fx-section">🎨 Seat Availability Heatmap</div>',
                unsafe_allow_html=True)

    has_avail = any(
        t.availability and any(v not in ("—", "") for v in t.availability.values())
        for s in results.date_wise.values()
        for t in s.trains
    )
    if not has_avail:
        st.info("Enable **Fetch live seat availability** to see this heatmap.")
        return

    col1, col2 = st.columns([1, 5])
    with col1:
        cls        = st.selectbox("Class", CLASS_ORDER, key="hm_cls")
        max_trains = st.slider("Max trains", 5, 40, 20, key="hm_rows")
    with col2:
        st.plotly_chart(_chart_heatmap(results, cls, max_trains),
                        use_container_width=True)
    st.caption("Grey = train doesn't run that day  |  Hover cells for exact values")


def render_datewise(results: AggregatedResults) -> None:
    st.markdown('<div class="fx-section">📅 Day-by-Day Breakdown</div>',
                unsafe_allow_html=True)
    rows = [{
        "Date":     d.strftime("%d %b %Y"),
        "Day":      s.weekday,
        "Week #":   s.week_number,
        "# Trains": s.count,
        "Trains":   ", ".join(t.train_number for t in s.trains) or "—",
    } for d in sorted(results.date_wise) for s in [results.date_wise[d]]]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_export(results: AggregatedResults) -> None:
    st.markdown('<div class="fx-section">💾 Download Full Report</div>',
                unsafe_allow_html=True)
    buf      = io.BytesIO()
    analysis = results.combined_weekday_analysis()
    bus      = results.bus_suggestions()
    pressure = bus["weekday_pressure"]

    dw_rows = [{
        "Date":  d.strftime("%d-%b-%Y"), "Day": s.weekday, "Week #": s.week_number,
        "Train Count": s.count,
        "Trains": "; ".join(f"{t.train_number} {t.train_name}" for t in s.trains) or "—",
    } for d in sorted(results.date_wise) for s in [results.date_wise[d]]]

    bus_rows = []
    for r in analysis:
        p = pressure.get(r["day"]) or 0
        bus_rows.append({
            "Day": r["day"], "Avg Trains/Day": r["avg_trains"],
            "Avg Occupancy": f"{int(p*100)}%" if pressure.get(r["day"]) is not None else "—",
            "Demand Level":  r["demand_level"],
            "Recommended Action": (
                "Deploy extra buses" if p >= 0.70
                else "Monitor closely" if p >= 0.40
                else "Standard schedule"
            ),
        })

    df_weekly = pd.DataFrame(results.weekly_summary())
    df_weekly.rename(columns={"week": "Week #", "date_range": "Date Range",
                               "total": "Total"}, inplace=True)

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(dw_rows).to_excel(writer, sheet_name="Date-wise", index=False)
        df_weekly.to_excel(writer, sheet_name="Weekly Summary", index=False)
        pd.DataFrame(results.weekly_demand_analysis()).to_excel(
            writer, sheet_name="Weekly Demand Analysis", index=False)
        pd.DataFrame(results.unique_trains()).to_excel(
            writer, sheet_name="All Trains", index=False)
        pd.DataFrame(bus_rows).to_excel(writer, sheet_name="Bus Deployment Plan", index=False)
        for cls in CLASS_ORDER:
            summary = results.weekday_availability_summary(cls)
            if any(v["count"] > 0 for v in summary.values()):
                pd.DataFrame([{
                    "Day": d, "Avg Seats": summary[d]["avg"],
                    "Min": summary[d]["min"], "Max": summary[d]["max"],
                    "Data Points": summary[d]["count"],
                } for d in WEEKDAY_NAMES]).to_excel(
                    writer, sheet_name=f"Seats-{cls}", index=False)
        for ws in writer.sheets.values():
            for col_cells in ws.columns:
                w = max((len(str(c.value or "")) for c in col_cells), default=8)
                ws.column_dimensions[col_cells[0].column_letter].width = min(w + 4, 50)

    buf.seek(0)
    fname = (f"railways_{results.from_code}_{results.to_code}"
             f"_{results.start_date.strftime('%Y%m%d')}"
             f"_{results.end_date.strftime('%Y%m%d')}.xlsx")
    st.download_button(
        "Download Excel Report", data=buf, file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.caption(
        "Sheets: Date-wise · Weekly Summary · Weekly Demand Analysis · "
        "All Trains · Bus Deployment Plan · Per-class seat data"
    )


# ── Main ──────────────────────────────────────────────────────────────────────
if run_button:
    if not origin_input or not destination_input:
        st.error("Please enter both origin and destination stations.")
        st.stop()
    if end_date <= start_date:
        st.error("'To Date' must be after 'From Date'.")
        st.stop()

    try:
        from_code, from_name = resolve_station(origin_input)
        to_code,   to_name   = resolve_station(destination_input)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    days = (end_date - start_date).days + 1
    st.markdown(
        f'<div class="sug-info sug-card" style="margin-bottom:16px;">'
        f'  <div class="sug-icon">🛤️</div>'
        f'  <div><div class="sug-title">{from_name} ({from_code}) → {to_name} ({to_code})</div>'
        f'  <div class="sug-body">{start_date.strftime("%d %b %Y")} – '
        f'{end_date.strftime("%d %b %Y")} &nbsp;·&nbsp; {days} days</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Fetching train schedule from erail.in…"):
        trains = scrape_schedule(from_code, to_code)

    results = AggregatedResults(
        from_code=from_code, to_code=to_code,
        from_name=from_name, to_name=to_name,
        start_date=start_date, end_date=end_date,
    )
    results.build(trains)

    if fetch_avail:
        prog = st.progress(0, text="Fetching live seat availability…")

        def on_progress(done: int, total: int, date_str: str):
            prog.progress(done / total,
                          text=f"Fetching availability — {date_str}  ({done}/{total})")

        avail = scrape_availability_range(
            from_code, to_code, start_date, end_date,
            progress_cb=on_progress, batch_size=3,
        )
        results.merge_availability(avail)
        prog.empty()

    unique = len(results.unique_trains())
    total  = sum(s.count for s in results.date_wise.values())
    st.success(f"Found **{unique} unique trains** · **{total} train-day slots** over {days} days")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊  Overview",
        "🚌  Bus Planning",
        "🚃  Train List",
        "🎨  Heatmap",
        "📅  Day-by-Day",
        "💾  Export",
    ])
    with tab1: render_overview(results)
    with tab2: render_bus(results)
    with tab3: render_trains(results)
    with tab4: render_heatmap(results)
    with tab5: render_datewise(results)
    with tab6: render_export(results)

else:
    st.markdown(f"""
<div style="max-width:680px;margin:32px auto;">
<div style="background:{FX_WHITE};border-radius:14px;padding:36px 40px;
            box-shadow:0 4px 20px rgba(0,0,0,0.08);">

<h3 style="color:{FX_DARK};margin-top:0;font-size:1.2rem;">How to use</h3>
<ol style="color:{FX_GREY};line-height:2.2;margin:0 0 20px 0;">
  <li>Enter <b>From</b> and <b>To</b> station names — or codes like <code>NDLS</code>, <code>BCT</code>, <code>SBC</code></li>
  <li>Pick a <b>date range</b> (up to 120 days ahead)</li>
  <li>Check <b>Fetch live seat availability</b> for occupancy data and bus plans</li>
  <li>Click <b>Search Trains</b></li>
</ol>

<table style="width:100%;border-collapse:collapse;font-size:0.88rem;">
  <tr style="background:{FX_DARK};color:{FX_WHITE};">
    <th style="padding:10px 14px;border-radius:8px 0 0 0;text-align:left;">Tab</th>
    <th style="padding:10px 14px;border-radius:0 8px 0 0;text-align:left;">What you get</th>
  </tr>
  <tr style="background:#f9f9f9;">
    <td style="padding:9px 14px;">📊 Overview</td>
    <td style="padding:9px 14px;">KPIs + interactive weekday &amp; weekly demand charts</td>
  </tr>
  <tr>
    <td style="padding:9px 14px;">🚌 Bus Planning</td>
    <td style="padding:9px 14px;">Occupancy gauge + colour-coded bus deployment plan</td>
  </tr>
  <tr style="background:#f9f9f9;">
    <td style="padding:9px 14px;">🚃 Train List</td>
    <td style="padding:9px 14px;">All trains with live colour-coded seat availability</td>
  </tr>
  <tr>
    <td style="padding:9px 14px;">🎨 Heatmap</td>
    <td style="padding:9px 14px;">Train × Date interactive grid — green to red</td>
  </tr>
  <tr style="background:#f9f9f9;">
    <td style="padding:9px 14px;">📅 Day-by-Day</td>
    <td style="padding:9px 14px;">Full daily breakdown</td>
  </tr>
  <tr>
    <td style="padding:9px 14px;border-radius:0 0 0 8px;">💾 Export</td>
    <td style="padding:9px 14px;border-radius:0 0 8px 0;">Excel with all sheets including bus plan</td>
  </tr>
</table>

<p style="color:{FX_MID};font-size:0.8rem;margin-top:18px;margin-bottom:0;">
  <b>Sharing:</b> copy folder → run <code>setup.bat</code> once → <code>start.bat</code> to launch.
  Run <code>create_shortcut.bat</code> for a Desktop icon. For a public URL, deploy to
  <a href="https://streamlit.io/cloud" target="_blank" style="color:{FX_GREEN2};">Streamlit Community Cloud</a>.
</p>
</div>
</div>
""", unsafe_allow_html=True)
