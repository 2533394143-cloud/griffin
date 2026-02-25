import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import io  # 新增：用于处理Excel文件下载

# --- 1. 页面配置与 UI 美化 ---
st.set_page_config(page_title="光伏储能工程分析系统 Pro", layout="wide", page_icon="⚡")

# 注入 CSS 代码，美化界面并隐藏官方水印
st.markdown("""
    <style>
    /* 隐藏右上角菜单和底部水印，提升专业感 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* 美化指标卡片 */
    .metric-card { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #2ecc71; margin-bottom: 15px;}
    </style>
    """, unsafe_allow_html=True)


# --- 2. 核心工程逻辑 ---
class EngineeringModel:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon

    def estimate_capacity(self, area_sqm, install_type):
        if install_type == "地面电站 (有间距)":
            power_density = 60  # W/m2
        else:
            power_density = 110  # W/m2
        capacity_kw = (area_sqm * power_density) / 1000
        return capacity_kw, power_density

    def fetch_historical_year(self):
        end_date = datetime.now().date() - timedelta(days=1)
        start_date = end_date - timedelta(days=365)
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "hourly": "temperature_2m,shortwave_radiation",
            "timezone": "auto"
        }
        try:
            r = requests.get(url, params=params)
            data = r.json()
            if 'hourly' not in data: return pd.DataFrame()
            df = pd.DataFrame({
                'time': pd.to_datetime(data['hourly']['time']),
                'temp': data['hourly']['temperature_2m'],
                'ghi': data['hourly']['shortwave_radiation']
            })
            return df
        except Exception as e:
            return pd.DataFrame()

    def simulate_generation(self, df, capacity_kw, pr=0.82):
        df['cell_temp'] = df['temp'] + 0.025 * df['ghi']
        temp_loss = 1 + (-0.004) * (df['cell_temp'] - 25)
        df['gen_kw'] = capacity_kw * (df['ghi'] / 1000) * pr * temp_loss
        df['gen_kw'] = df['gen_kw'].clip(lower=0)
        return df


# --- 3. 侧边栏：参数设置 ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/000000/solar-panel.png", width=60)  # 加个小图标
    st.title("项目参数配置")

    with st.container(border=True):
        st.header("📍 地理位置")
        lat = st.number_input("纬度 (Latitude)", value=31.23, format="%.4f")
        lon = st.number_input("经度 (Longitude)", value=121.47, format="%.4f")

    with st.container(border=True):
        st.header("📐 土地与容量")
        install_type = st.selectbox("安装场景", ["地面电站 (有间距)", "工商业屋顶 (平铺)"])
        area_sqm = st.number_input("可用有效面积 (m²)", value=5000, step=100)

        model = EngineeringModel(lat, lon)
        est_cap, density = model.estimate_capacity(area_sqm, install_type)
        st.success(f"建议装机容量: {est_cap:.2f} kW")
        final_capacity = st.number_input("确认设计容量 (kW)", value=float(f"{est_cap:.2f}"))

    # 将不常用的专业参数折叠起来
    with st.expander("⚙️ 高级工程参数", expanded=False):
        pr = st.slider("系统综合效率 (PR)", 0.75, 0.90, 0.82)

# --- 4. 主界面 ---
st.title("📊 光伏储能项目分析平台")

tab1, tab2, tab3 = st.tabs(["📂 1. 数据导入", "📈 2. 曲线对比", "🔋 3. 储能测算"])

if 'weather_df' not in st.session_state:
    st.session_state['weather_df'] = None

# ================= TAB 1: 数据导入 (引入模板下载功能) =================
with tab1:
    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("步骤 A: 导入用户负荷")
            st.markdown("为了保证数据准确，请务必使用标准模板。")

            # --- 生成 Excel 模板供用户下载 ---
            df_template = pd.DataFrame({
                "时间参考 (不需要修改)": [f"第 {i + 1} 小时" for i in range(24)],
                "用电功率 (kW)": [100.0] * 24  # 默认填100，让用户知道填这里
            })
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_template.to_excel(writer, index=False, sheet_name='用电数据')

            st.download_button(
                label="📥 1. 点击下载标准数据模板",
                data=buffer.getvalue(),
                file_name="光伏负荷测算模板.xlsx",
                mime="application/vnd.ms-excel",
                type="primary"
            )

            # --- 上传窗口 ---
            uploaded_file = st.file_uploader("📤 2. 填写后在此上传模板", type=['xlsx', 'xls'])

    with col2:
        with st.container(border=True):
            st.subheader("步骤 B: 获取气象资源")
            st.markdown("一键获取该地区过去一年的真实光照数据。")
            if st.button("🌍 开始获取气象资源", use_container_width=True):
                with st.spinner("正在连接气象卫星数据库..."):
                    df = model.fetch_historical_year()
                    if not df.empty:
                        df = model.simulate_generation(df, final_capacity, pr)
                        st.session_state['weather_df'] = df
                        st.success("✅ 气象数据与光伏发电模型生成完毕！")
                    else:
                        st.error("获取失败，请重试。")

    # --- 处理上传的数据 ---
    if uploaded_file is not None and st.session_state['weather_df'] is not None:
        try:
            load_df = pd.read_excel(uploaded_file)

            # 防呆设计：强制寻找我们模板里的列名
            if "用电功率 (kW)" in load_df.columns:
                load_data = load_df["用电功率 (kW)"].values
                st.success("✅ 成功识别标准模板数据！")
            else:
                load_data = load_df.iloc[:, -1].values  # 找不到就硬取最后一列
                st.warning("⚠️ 未检测到标准格式，已尝试自动提取。")

            weather_df = st.session_state['weather_df'].copy()
            req_len = len(weather_df)

            # 循环填充数据
            if len(load_data) >= req_len:
                weather_df['load_kw'] = load_data[:req_len]
            else:
                tiled = np.tile(load_data, int(np.ceil(req_len / len(load_data))))
                weather_df['load_kw'] = tiled[:req_len]

            st.session_state['final_df'] = weather_df
        except Exception as e:
            st.error("文件读取失败，请确保您使用的是刚刚下载的 Excel 模板。")

# ================= TAB 2: 曲线对比 (美化展示) =================
with tab2:
    if 'final_df' in st.session_state:
        df = st.session_state['final_df']
        total_gen = df['gen_kw'].sum()
        total_load = df['load_kw'].sum()

        with st.container(border=True):
            k1, k2, k3 = st.columns(3)
            k1.metric("🌞 年总发电量", f"{total_gen / 10000:.2f} 万kWh")
            k2.metric("🏭 年总用电量", f"{total_load / 10000:.2f} 万kWh")
            k3.metric("⏱️ 等效利用小时数", f"{total_gen / final_capacity:.0f} 小时")

        view_mode = st.radio("查看维度", ["典型日视角", "全月视角", "全年视角"], horizontal=True)
        if view_mode == "典型日视角":
            day_df = df.iloc[1000:1048]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=day_df['time'], y=day_df['gen_kw'], fill='tozeroy', name='光伏发电 (kW)',
                                     line=dict(color='#f1c40f')))
            fig.add_trace(go.Scatter(x=day_df['time'], y=day_df['load_kw'], name='用户负荷 (kW)',
                                     line=dict(color='#2c3e50', width=2)))
            st.plotly_chart(fig, use_container_width=True)
        elif view_mode == "全月视角":
            month_df = df.set_index('time').resample('D').sum().reset_index()
            fig = go.Figure()
            fig.add_trace(go.Bar(x=month_df['time'], y=month_df['gen_kw'], name='日光伏电量', marker_color='#f1c40f'))
            fig.add_trace(go.Scatter(x=month_df['time'], y=month_df['load_kw'], name='日用电量',
                                     line=dict(color='#e74c3c', width=2)))
            st.plotly_chart(fig, use_container_width=True)
        else:
            fig = px.area(df, x='time', y=['gen_kw', 'load_kw'], title="全年供需轮廓")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("请先在 Tab 1 完成数据导入。")

# ================= TAB 3: 储能测算 =================
with tab3:
    if 'final_df' in st.session_state:
        df = st.session_state['final_df']
        df['net_load'] = df['load_kw'] - df['gen_kw']
        daily_stats = df.set_index('time').resample('D').apply({
            'net_load': [lambda x: abs(x[x < 0].sum()), lambda x: x[x > 0].sum()]
        })
        daily_analysis = pd.DataFrame(daily_stats['net_load'].tolist(), columns=['surplus', 'deficit'],
                                      index=daily_stats.index)
        daily_analysis['effective_storage'] = daily_analysis[['surplus', 'deficit']].min()

        valid_days = daily_analysis[daily_analysis['effective_storage'] > 1]

        with st.container(border=True):
            if not valid_days.empty:
                rec_capacity_kwh = valid_days['effective_storage'].quantile(0.90) / 0.9
                rec_power_kw = rec_capacity_kwh / 2

                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown(f"""
                    <div class="metric-card">
                        <h3 style="color: #2c3e50;">🔋 推荐储能规模</h3>
                        <h2 style="color: #27ae60;">{rec_power_kw:.0f} kW</h2>
                        <h2 style="color: #2980b9;">{rec_capacity_kwh:.0f} kWh</h2>
                    </div>
                    """, unsafe_allow_html=True)
                with c2:
                    st.markdown("#### 📝 工程师诊断说明")
                    st.markdown(
                        f"基于过去全年的气象回测与您的用电曲线匹配度分析，系统截取了 **90%** 的高频需求场景。\n\n建议利用白天光伏盈余电量进行充电，配置 **{rec_capacity_kwh:.0f}度** 电池，既能避免储能资源浪费，又能最大化降低夜间购电成本。")
            else:
                st.warning("根据当前数据，光伏发电几乎被实时消纳，暂无足够余电用于充电，不建议配置储能。")
    else:
        st.info("请先完成数据导入。")