# main.py
import io
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ─────────────────────────────────────────────
# 한글 폰트 (Streamlit CSS + Plotly)
# ─────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR&display=swap');
html, body, [class*="css"] {
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# CSV 읽기 (인코딩 2종 시도, file.getvalue로 바이트 확보)
# ─────────────────────────────────────────────
@st.cache_data
def read_csv(file):
    """utf-8-sig → cp949 순서로 시도"""
    data = file.getvalue()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc)
        except Exception:
            pass
    return pd.DataFrame()


# ─────────────────────────────────────────────
# 열 이름 표준화 (KeyError 방지)
# ─────────────────────────────────────────────
def std_cols(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        k = c.lower().replace(" ", "")
        if k in ("time", "categories", "시간", "날짜", "datetime", "date"):
            rename[c] = "time"
        elif k in ("temperature", "온도"):
            rename[c] = "temperature"
        elif k in ("humidity", "습도"):
            rename[c] = "humidity"
        elif k == "ph":
            rename[c] = "ph"
        elif k == "ec":
            rename[c] = "ec"
        elif "생중량" in k:
            rename[c] = "생중량"
        elif "잎" in k:
            rename[c] = "잎 수"
        elif "지상부" in k and "길이" in k:
            rename[c] = "지상부 길이"
        elif "지하부" in k and "길이" in k:
            rename[c] = "지하부 길이"
        elif "지상부" in k and ("질량" in k or "무게" in k):
            rename[c] = "지상부 질량"
        elif "지하부" in k and ("질량" in k or "무게" in k):
            rename[c] = "지하부 질량"
        elif "개체" in k:
            rename[c] = "개체번호"
    df = df.rename(columns=rename)
    for c in df.columns:
        if c in ("time", "개체번호"):
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            num = pd.to_numeric(
                df[c].astype(str).str.replace(",", "")
                .str.extract(r"(-?\d+\.?\d*)")[0],
                errors="coerce",
            )
            if num.notna().mean() >= 0.5:
                df[c] = num
    if "생중량" not in df.columns and {"지상부 질량", "지하부 질량"} <= set(df.columns):
        df["생중량"] = df["지상부 질량"] + df["지하부 질량"]
    if "time" in df.columns:
        t = df["time"].astype(str).str.strip()
        parsed = pd.to_datetime(t, errors="coerce", format="mixed")
        bad = parsed.isna() & t.str.match(r"^\d{8}_\d{1,2}$")
        if bad.any():
            parts = t[bad].str.split("_", expand=True)
            parsed[bad] = (
                pd.to_datetime(parts[0], format="%Y%m%d")
                + pd.to_timedelta(parts[1].astype(int), unit="h")
            )
        df["time"] = parsed
    return df


# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(page_title="극지식물 생육 차이 분석", layout="wide")
st.title("🌱 우리 학교 극지식물 개체별 생육 차이 분석")
st.caption("CSV 두 개를 업로드하면 환경 데이터 + 생육 결과를 함께 분석할 수 있어요.")


# ─────────────────────────────────────────────
# 사이드바: CSV 업로드 + 항목 선택
# ─────────────────────────────────────────────
st.sidebar.header("📁 CSV 업로드")
env_file = st.sidebar.file_uploader("환경 데이터 CSV", type="csv")
growth_file = st.sidebar.file_uploader("생육 결과 CSV", type="csv")

with st.sidebar.expander("📌 생육 측정 항목 선택"):
    growth_metrics = st.multiselect(
        "분석할 생육 지표",
        ["잎 수", "지상부 길이", "지하부 길이", "생중량", "지상부 질량", "지하부 질량"],
        default=["잎 수", "지상부 길이", "지하부 길이", "생중량"],
        help="해당 열이 있는 지표만 그래프에 사용됩니다.",
    )

# ── 학교명 추출 ──
def extract_school(fn):
    name = fn.replace(".csv", "").strip()
    parts = name.split("_")
    return parts[0] if len(parts) >= 2 else (name[:10] if name else "우리 학교")

school_name = "업로드 예정"
if env_file:
    school_name = extract_school(env_file.name)
if growth_file:
    s2 = extract_school(growth_file.name)
    school_name = s2 if school_name == "업로드 예정" else school_name
st.sidebar.caption(f"🏫 감지된 학교명: {school_name}")

# ── 데이터 로딩 (한 번만) ──
env_df = pd.DataFrame()
growth_df = pd.DataFrame()
if env_file:
    with st.spinner("환경 데이터를 읽는 중..."):
        env_df = std_cols(read_csv(env_file))
if growth_file:
    with st.spinner("생육 결과 데이터를 읽는 중..."):
        growth_df = std_cols(read_csv(growth_file))


# ─────────────────────────────────────────────
# 지표 설명 (고등학생용)
# ─────────────────────────────────────────────
METRIC_HELP = {
    "총 개체수": "분석에 사용된 극지식물 개체의 총 수예요.",
    "평균 온도": "측정 기간 동안 온도의 평균값. 온도가 생육에 영향을 줄 수 있어요.",
    "평균 습도": "측정 기간 동안 습도의 평균값. 습도가 높으면 식물이 물을 덜 잃어요.",
    "평균 생중량": "개체 전체의 무게 평균. 평균 = 모든 값을 더해 개수로 나눈 대표값.",
}


# ─────────────────────────────────────────────
# 공통 그래프: 환경 일별 시계열
# ─────────────────────────────────────────────
def env_ts(df_agg, col, title, color, ylabel):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_agg["Date"],
            y=df_agg[col],
            mode="lines+markers",
            name=title,
            line=dict(color=color, width=2),
            marker=dict(size=5),
            hovertemplate=f"{title}<br>%{{x|%m/%d %H:%M}}<br>값: %{{y:.2f}}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, x=0.02, y=0.95, xanchor="left"),
        xaxis_title="날짜",
        yaxis_title=ylabel,
        hovermode="x unified",
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
        margin=dict(t=50, b=40, l=40, r=20),
        height=250,
    )
    return fig


# ─────────────────────────────────────────────
# 공통 그래프: 생육 지표 평균 막대
# ─────────────────────────────────────────────
def metric_bar(metric, value, unit):
    d = pd.DataFrame({"지표": [metric], "평균값": [value]})
    fig = px.bar(
        d,
        x="평균값",
        y="지표",
        orientation="h",
        color="지표",
        color_discrete_sequence=["#2E86AB"],
        labels={"평균값": f"평균 ({unit})", "지표": ""},
    )
    fig.add_annotation(
        x=value, y=metric,
        text=f"{value:.2f}",
        showarrow=False, yshift=10,
        font=dict(size=12, color="black"),
    )
    fig.update_layout(
        xaxis_title=f"평균 ({unit})",
        height=210,
        margin=dict(t=30, b=30, l=60, r=20),
        showlegend=False,
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
    )
    return fig


# ─────────────────────────────────────────────
# 공통 그래프: 개체별 막대 그래프
# ─────────────────────────────────────────────
def individual_bar(df_in, col, title, unit):
    d = df_in[["개체번호", col]].dropna()
    if d.shape[0] < 2:
        st.info(f"⚠️ {title}을 그릴 데이터가 부족해요 (개체 {d.shape[0]}개).")
        return None
    d = d.sort_values("개체번호").reset_index(drop=True)
    mean_v = d[col].mean()
    q75 = d[col].quantile(0.75)
    q25 = d[col].quantile(0.25)
    colors = [
        "#27AE60" if v >= q75 else
        "#E74C3C" if v <= q25 else
        "#85C1E9"
        for v in d[col]
    ]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=d["개체번호"].astype(str),
            y=d[col],
            marker_color=colors,
            name="개체별 값",
        )
    )
    fig.add_hline(
        y=mean_v,
        line_dash="dash",
        line_color="orange",
        annotation_text=f"평균 {mean_v:.2f}",
        annotation_position="top right",
    )
    fig.update_layout(
        title=dict(text=title, x=0.02, y=0.95),
        xaxis_title="개체번호",
        yaxis_title=unit,
        height=290,
        margin=dict(t=50, b=40, l=50, r=20),
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
    )
    return fig


# ─────────────────────────────────────────────
# 공통 그래프: 산점도 + np.polyfit 추세선 + 상관계수
# ─────────────────────────────────────────────
def scatter_trend(x, y, xlabel, ylabel, title):
    data = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(data) < 3:
        st.info(f"⚠️ {title}을 그릴 데이터가 부족해요 ({len(data)}개).")
        return None, None
    r = np.corrcoef(data["x"], data["y"])[0, 1]
    slope, intercept = np.polyfit(data["x"], data["y"], 1)
    lx = np.array([data["x"].min(), data["x"].max()])
    ly = slope * lx + intercept
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["x"], y=data["y"],
            mode="markers",
            marker=dict(size=9, color="#2E86AB", opacity=0.75),
            name="데이터",
            hovertemplate=f"{xlabel}: %{{x:.2f}}<br>{ylabel}: %{{y:.2f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=lx, y=ly,
            mode="lines",
            line=dict(color="#E74C3C", width=2, dash="dash"),
            name=f"추세선 (r={r:.2f})",
        )
    )
    fig.update_layout(
        title=dict(text=title, x=0.02, y=0.95),
        xaxis_title=xlabel,
        yaxis_title=ylabel,
        height=310,
        margin=dict(t=50, b=40, l=50, r=20),
        hovermode="closest",
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
    )
    return fig, r


# ─────────────────────────────────────────────
# 공통 함수: CSV 다운로드 버튼
# ─────────────────────────────────────────────
def download_btn(df, label, filename):
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label=label, data=csv_bytes, file_name=filename, mime="text/csv")


# ═════════════════════════════════════════════
# Tab 1 — 실험 개요
# ═════════════════════════════════════════════
tab1, tab2, tab3 = st.tabs(["📖 실험 개요", "🌡️ 환경 데이터", "📊 생육 결과"])

with tab1:
    try:
        st.header("연구 배경 및 목적")
        st.markdown(
            """
**극지식물**은 온도·습도 등 환경이 열악한 곳에서도 살아남는 식물이에요.
이 실험에서는 같은 조건에서 키운 극지식물 개체들을 하나씩 측정해,
**개체마다 생육(잎 수, 길이, 무게)이 얼마나 차이 나는지**를 살펴봐요.

- **평균**: 모든 값을 더해 개수로 나눈 것 — 대표값을 알 수 있어요.
- **표준편차**: 값들이 평균 주위에 얼마나 흩어져 있는지 — 클수록 들쭉날쭉해요.
- **상관계수 (r)**: -1 ~ 1 사이의 수 — 1에 가까우면 함께 증가, -1에 가까우면 반대로 움직여요. 0에 가까우면 관계가 거의 없어요.
- **CV(변동계수)**: 표준편차를 평균으로 나눈 값 — 평균이 다른 집단끼리 흩어진 정도를 비교할 때 써요.
"""
        )

        st.header("📋 데이터 요약")

        if growth_df.empty and env_df.empty:
            st.info("👆 사이드바에서 환경 CSV와 생육 CSV를 업로드해 주세요.")
        else:
            rows = []
            if not growth_df.empty:
                n = growth_df.shape[0]
                cols_present = [c for c in ["잎 수", "지상부 길이", "지하부 길이", "생중량"]
                                if c in growth_df.columns]
                rows.append({"항목": "생육 데이터", "내용": f"총 {n}개체, 측정 항목: {', '.join(cols_present)}"})
            if not env_df.empty and "time" in env_df.columns:
                idx = env_df["time"].dropna()
                if len(idx) > 0:
                    start_s = idx.min().strftime("%Y-%m-%d")
                    end_s = idx.max().strftime("%Y-%m-%d")
                    rows.append({"항목": "환경 데이터", "내용": f"측정 기간: {start_s} ~ {end_s}"})
            st.table(pd.DataFrame(rows))

            cards = []
            if not growth_df.empty and "생중량" in growth_df.columns:
                cards.append(("총 개체수", growth_df.shape[0], "개", METRIC_HELP["총 개체수"]))
                gw = growth_df["생중량"].dropna()
                if len(gw) > 0:
                    cards.append(("평균 생중량", round(gw.mean(), 2), "g", METRIC_HELP["평균 생중량"]))
            if not env_df.empty and "temperature" in env_df.columns:
                tv = env_df["temperature"].dropna()
                if len(tv) > 0:
                    cards.append(("평균 온도", round(tv.mean(), 1), "°C", METRIC_HELP["평균 온도"]))
            if not env_df.empty and "humidity" in env_df.columns:
                hv = env_df["humidity"].dropna()
                if len(hv) > 0:
                    cards.append(("평균 습도", round(hv.mean(), 1), "%", METRIC_HELP["평균 습도"]))
            if cards:
                cols = st.columns(len(cards))
                for i, (label, val, unit, help_txt) in enumerate(cards):
                    with cols[i]:
                        st.metric(label=label, value=val, delta=None, delta_color="off")
                        st.caption(help_txt)
    except Exception as e:
        st.warning(f"⚠️ 이 부분은 데이터 형식 때문에 표시하지 못했어요: {e}")


# ═════════════════════════════════════════════
# Tab 2 — 환경 데이터
# ═════════════════════════════════════════════
with tab2:
    try:
        if env_df.empty:
            st.info("🌡️ 환경 CSV를 아직 업로드하지 않았어요. 사이드바에서 업로드해 주세요.")
        else:
            env_cols = [c for c in ["temperature", "humidity", "ph", "ec"] if c in env_df.columns]
            if env_cols:
                st.subheader("📐 환경 요약 (평균 · 최소 · 최대)")
                ev = env_df[env_cols].dropna()
                if len(ev) > 0:
                    summ = pd.DataFrame({
                        "평균": ev.mean().round(2),
                        "최소": ev.min().round(2),
                        "최대": ev.max().round(2),
                    }).T
                    st.dataframe(summ, width="stretch", height=200)
                else:
                    st.info("환경 데이터가 비어 있어요.")

            with st.expander("📋 환경 데이터 원본 테이블"):
                st.dataframe(env_df, width="stretch", height=300)
                download_btn(env_df, "📥 환경 CSV 다운로드", "환경데이터_download.csv")

            if "time" in env_df.columns and len(env_df) > 0:
                env_df2 = env_df.copy()
                env_df2["time"] = pd.to_datetime(env_df2["time"], errors="coerce")
                env_df2 = env_df2.dropna(subset=["time"])
                if len(env_df2) > 0:
                    env_df2["Date"] = env_df2["time"].dt.floor("D")
                    grp = env_df2.groupby("Date")[env_cols].mean().reset_index()
                    grp = grp.sort_values("Date")

                    ts_cols = [c for c in ["temperature", "humidity", "ph", "ec"] if c in grp.columns]
                    if ts_cols:
                        st.subheader("📈 날짜별 환경 변화 (일별 평균)")
                        n_ts = len(ts_cols)
                        fig_ts = make_subplots(rows=n_ts, cols=1, subplot_titles=ts_cols,
                                                vertical_spacing=0.12)
                        color_cycle = ["#E74C3C", "#2E86AB", "#27AE60", "#F39C12"]
                        for i, col in enumerate(ts_cols):
                            trace = go.Scatter(
                                x=grp["Date"], y=grp[col],
                                mode="lines+markers",
                                name=col,
                                line=dict(color=color_cycle[i % len(color_cycle)], width=2),
                                marker=dict(size=5),
                                hovertemplate=f"{col}<br>%{{x|%m/%d}}<br>값: %{{y:.2f}}<extra></extra>",
                            )
                            fig_ts.add_trace(trace, row=i + 1, col=1)
                            fig_ts.update_yaxes(title_text=col, row=i + 1, col=1)
                        fig_ts.update_xaxes(title_text="날짜", row=n_ts, col=1)
                        fig_ts.update_layout(
                            height=120 * n_ts + 40,
                            hovermode="x unified",
                            font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
                            margin=dict(t=30, b=30, l=40, r=20),
                        )
                        st.plotly_chart(fig_ts, width="stretch")
                    else:
                        st.info("그래프로 표시할 환경 열이 없어요.")
                else:
                    st.info("시간 데이터가 없어서 시계열을 그릴 수 없어요.")
            else:
                st.info("time 열이 없어서 날짜별 시계열을 표시할 수 없어요.")
    except Exception as e:
        st.warning(f"⚠️ 이 부분은 데이터 형식 때문에 표시하지 못했어요: {e}")


# ═════════════════════════════════════════════
# Tab 3 — 생육 결과
# ═════════════════════════════════════════════
with tab3:
    try:
        if growth_df.empty:
            st.info("📊 생육 CSV를 아직 업로드하지 않았어요. 사이드바에서 업로드해 주세요.")
        elif "생중량" not in growth_df.columns and "지상부 질량" not in growth_df.columns:
            st.info("생중량(또는 지상부 질량 + 지하부 질량) 열이 없어서 생육 분석을 할 수 없어요.")
        else:
            gdf = growth_df.dropna(subset=["생중량"]) if "생중량" in growth_df.columns else growth_df.copy()
            gw = gdf["생중량"].dropna() if "생중량" in gdf.columns else pd.Series(dtype=float)

            # ── 핵심 결과 ──
            st.subheader("🥇 핵심 결과")
            if len(gw) > 0:
                mean_gw = gw.mean()
                std_gw = gw.std()
                cv_gw = std_gw / mean_gw if mean_gw > 0 else 0
                best_idx = gw.idxmax()
                worst_idx = gw.idxmin()
                best_id = gdf.loc[best_idx, "개체번호"] if best_idx is not None and not pd.isna(best_idx) else "—"
                worst_id = gdf.loc[worst_idx, "개체번호"] if worst_idx is not None and not pd.isna(worst_idx) else "—"

                st.markdown(
                    f"""
**개체 수**: {gdf.shape[0]}개체 &nbsp;|&nbsp;
**평균 생중량**: {mean_gw:.2f} g &nbsp;|&nbsp;
**표준편차**: {std_gw:.2f} g &nbsp;|&nbsp;
**CV(변동계수)**: {cv_gw:.3f}
"""
                )
                st.caption(
                    "표준편차: 값들이 평균 주위에 얼마나 흩어져 있는지. "
                    "CV(변동계수): 표준편차를 평균으로 나눈 값 — 평균이 다른 집단끼리 비교할 때 사용해요."
                )

                cards3 = [
                    ("평균 생중량", f"{mean_gw:.2f} g", f"표준편차 {std_gw:.2f} g, CV {cv_gw:.3f}"),
                    ("최대 생중량", f"{gw.max():.2f} g", f"개체 {best_id} (개체번호 {best_idx})"),
                    ("최소 생중량", f"{gw.min():.2f} g", f"개체 {worst_id} (개체번호 {worst_idx})"),
                    ("총 개체수", f"{gdf.shape[0]} 개체", ""),
                ]
                cc = st.columns(len(cards3))
                for i, (lbl, val, sub) in enumerate(cards3):
                    with cc[i]:
                        st.metric(label=lbl, value=val)
                        if sub:
                            st.caption(sub)

                # ── 상위/하위 25% 비교 ──
                q75 = gw.quantile(0.75)
                q25 = gw.quantile(0.25)
                top = gdf[gdf["생중량"] >= q75] if "생중량" in gdf.columns else pd.DataFrame()
                bot = gdf[gdf["생중량"] <= q25] if "생중량" in gdf.columns else pd.DataFrame()
                st.divider()
                if len(top) > 0 and len(bot) > 0:
                    st.markdown("**생중량 상위 25% vs 하위 25% 비교**")
                    comp_rows = []
                    for m in ["잎 수", "지상부 길이", "지하부 길이"]:
                        if m in gdf.columns:
                            t_mean = top[m].dropna().mean() if len(top[m].dropna()) > 0 else float("nan")
                            b_mean = bot[m].dropna().mean() if len(bot[m].dropna()) > 0 else float("nan")
                            comp_rows.append({
                                "측정 항목": m,
                                "상위 25% 평균": f"{t_mean:.2f}" if not pd.isna(t_mean) else "—",
                                "하위 25% 평균": f"{b_mean:.2f}" if not pd.isna(b_mean) else "—",
                            })
                    if comp_rows:
                        st.table(pd.DataFrame(comp_rows))

            # ── 개체별 생육 비교 막대 ──
            st.divider()
            st.subheader("📊 개체별 생육 지표 평균")
            metrics_to_plot = [m for m in growth_metrics if m in gdf.columns and m != "생중량"]
            if metrics_to_plot:
                avg_rows = []
                for m in metrics_to_plot:
                    vals = gdf[m].dropna()
                    avg_rows.append({"지표": m, "평균": round(vals.mean(), 2) if len(vals) > 0 else 0})
                avg_df = pd.DataFrame(avg_rows)
                fig_avg = go.Figure()
                fig_avg.add_trace(
                    go.Bar(
                        x=avg_df["지표"],
                        y=avg_df["평균"],
                        marker_color="#2E86AB",
                        name="평균",
                    )
                )
                fig_avg.update_layout(
                    title="측정 지표별 평균값",
                    xaxis_title="측정 지표",
                    yaxis_title="평균값",
                    height=280,
                    margin=dict(t=50, b=40, l=50, r=20),
                    font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
                )
                st.plotly_chart(fig_avg, width="stretch")
            else:
                st.info("선택한 생육 측정 지표 열이 데이터에 없어요.")

            # ── 개별 개체 생중량 막대 ──
            st.subheader("📊 개체별 생중량 비교")
            if "생중량" in gdf.columns and gdf.shape[0] >= 2:
                fig_ind = individual_bar(gdf, "생중량", "개체별 생중량 (상위 25%: 초록 / 하위 25%: 빨강)", "g")
                if fig_ind:
                    st.plotly_chart(fig_ind, width="stretch")
            else:
                st.info("생중량 열이 없거나 개체가 2개 미만이에요.")

            # ── 생중량 분포 (박스플롯) ──
            if "생중량" in gdf.columns and gdf.shape[0] >= 4:
                st.subheader("📦 생중량 분포 (박스플롯)")
                fig_box = go.Figure()
                fig_box.add_trace(
                    go.Box(
                        y=gdf["생중량"].dropna(),
                        name="생중량",
                        fillcolor="#85C1E9",
                        line_color="#2E86AB",
                        jitter=0.3,
                        pointpos=0,
                        marker=dict(size=6),
                    )
                )
                fig_box.add_hline(
                    y=gw.mean(),
                    line_dash="dash",
                    line_color="orange",
                    annotation_text=f"평균 {gw.mean():.2f} g",
                    annotation_position="top right",
                )
                fig_box.update_layout(
                    title="생중량 분포 — 상자 수염 그래프",
                    yaxis_title="생중량 (g)",
                    height=300,
                    margin=dict(t=50, b=40, l=50, r=20),
                    font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
                )
                st.plotly_chart(fig_box, width="stretch")
                st.caption(
                    "박스플롯(상자 수염 그래프): 상자 안은 가운데 50% 값의 범위, "
                    "선(수염)은 극단값까지, 점들은 개별 개체 값이에요."
                )
            else:
                st.info("생중량 분포가 표시되지 않았어요 (데이터 부족).")

            # ── 상관관계 산점도 ──
            st.divider()
            st.subheader("🔗 상관관계 분석")
            if "생중량" in gdf.columns:
                pairs = [
                    ("잎 수", "생중량", "잎 수 (장)", "생중량 (g)", "잎 수 vs 생중량"),
                    ("지상부 길이", "생중량", "지상부 길이 (mm)", "생중량 (g)", "지상부 길이 vs 생중량"),
                ]
                for xcol, ycol, xlbl, ylbl, ttl in pairs:
                    if xcol in gdf.columns:
                        fig_s, r_val = scatter_trend(gdf[xcol], gdf[ycol], xlbl, ylbl, ttl)
                        if fig_s:
                            st.plotly_chart(fig_s, width="stretch")
                            st.caption(
                                f"상관계수 r = {r_val:.2f} — "
                                f"1에 가까우면 함께 증가, -1에 가까우면 반대로 움직여요. "
                                f"0에 가까우면 관계가 거의 없어요."
                            )
                    else:
                        st.info(f"⚠️ '{xcol}' 열이 데이터에 없어서 '{ttl}' 그래프를 그릴 수 없어요.")

            # ── 원본 + 다운로드 ──
            with st.expander("📋 생육 데이터 원본 테이블 + CSV 다운로드"):
                st.dataframe(growth_df, width="stretch", height=280)
                download_btn(growth_df, "📥 생육 결과 CSV 다운로드", "생육결과_download.csv")
    except Exception as e:
        st.warning(f"⚠️ 이 부분은 데이터 형식 때문에 표시하지 못했어요: {e}")
