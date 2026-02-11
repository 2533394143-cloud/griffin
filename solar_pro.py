import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

# --- 页面配置 ---
st.set_page_config(page_title="光伏储能工程分析系统 Pro", layout="wide", page_icon="⚡")

# --- CSS 样式优化 ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight: bold; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #2ecc71; }
    </style>
    """, unsafe_allow_html=True)


# --- 核心逻辑类 ---
class EngineeringModel:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon

    def estimate_capacity(self, area_sqm, install_type):
        """
        根据面积估算装机容量
        经验值:
        - 地面电站: 约 15-20 m2/kW (考虑间距) -> 约 50-65 W/m2
        - 屋顶平铺: 约 8-10 m2/kW -> 约 100-120 W/m2
        """
        if install_type == "地面电站 (有间距)":
            power_density = 60  # W/m2
        else:
            power_density = 110  # W/m2 (屋顶)

        capacity_kw = (area_sqm * power_density) / 1000
        return capacity_kw, power_density

    def fetch_historical_year(self):
        """获取过去365天的真实气象数据 (Open-Meteo Archive API)"""
        end_date = datetime.now().date() - timedelta(days=1)
        start_date = end_date - timedelta(days=365)

        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "hourly": "temperature_2m,shortwave_radiation",  # GHI
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
            st.error(f"气象数据获取失败: {e}")
            return pd.DataFrame()

    def simulate_generation(self, df, capacity_kw, pr=0.82):
        """计算8760小时发电量"""
        # 简单物理模型: P = Cap * (GHI/1000) * PR * (1 + temp_coeff*(T_cell-25))
        # 简化: T_cell ≈ T_air + 0.025*GHI
        df['cell_temp'] = df['temp'] + 0.025 * df['ghi']
        temp_loss = 1 + (-0.004) * (df['cell_temp'] - 25)

        df['gen_kw'] = capacity_kw * (df['ghi'] / 1000) * pr * temp_loss
        df['gen_kw'] = df['gen_kw'].clip(lower=0)
        return df


# --- 侧边栏：输入区 ---
with st.sidebar:
    st.title("🛠 工程参数设置")

    st.header("1. 地理位置")
    lat = st.number_input("纬度 (Latitude)", value=31.23, format="%.4f")
    lon = st.number_input("经度 (Longitude)", value=121.47, format="%.4f")

    st.header("2. 土地与容量")
    install_type = st.selectbox("安装场景", ["地面电站 (有间距)", "工商业屋顶 (平铺)"])
    area_sqm = st.number_input("可用有效面积 (m²)", value=5000, step=100)

    # 实时计算容量
    model = EngineeringModel(lat, lon)
    est_cap, density = model.estimate_capacity(area_sqm, install_type)

    st.info(f"📐 估算功率密度: {density} W/m²\n\n⚡ 建议装机容量: **{est_cap:.2f} kW** ({est_cap / 1000:.2f} MW)")

    # 允许用户微调容量
    final_capacity = st.number_input("确认最终设计容量 (kW)", value=float(f"{est_cap:.2f}"))
    pr = st.slider("系统综合效率 (PR)", 0.75, 0.90, 0.82)

# --- 主界面 ---
st.title("📊 光伏储能项目 · 精准分析报告")

# TAB 分页结构
tab1, tab2, tab3 = st.tabs(["📂 1. 数据导入与概览", "📈 2. 供需曲线对比", "🔋 3. 储能配置建议"])

# --- 全局变量占位 ---
if 'weather_df' not in st.session_state:
    st.session_state['weather_df'] = None

# ================= TAB 1: 数据导入 =================
with tab1:
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("步骤 A: 上传用电负荷")
        st.markdown("请上传 Excel (.xlsx) 或 CSV 文件。数据应包含一列每小时的用电功率(kW)。")
        uploaded_file = st.file_uploader("拖拽文件到此处", type=['xlsx', 'xls', 'csv'])

    with col2:
        st.subheader("步骤 B: 获取光照资源")
        if st.button("🌍 点击获取该地区历史气象年数据 (耗时约3秒)", type="primary"):
            with st.spinner("正在连接卫星数据库..."):
                df = model.fetch_historical_year()
                if not df.empty:
                    df = model.simulate_generation(df, final_capacity, pr)
                    st.session_state['weather_df'] = df
                    st.success("✅ 气象数据获取成功！已生成全年 8760 小时发电模型。")
                else:
                    st.error("无法获取数据，请检查网络。")

    st.divider()

    # 处理上传的负荷数据
    if uploaded_file is not None and st.session_state['weather_df'] is not None:
        try:
            # 读取文件
            if uploaded_file.name.endswith('.csv'):
                load_df = pd.read_csv(uploaded_file)
            else:
                load_df = pd.read_excel(uploaded_file)

            # 尝试自动寻找数值列
            numeric_cols = load_df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                target_col = numeric_cols[0]  # 默认取第一列数值
                load_data = load_df[target_col].values

                # 数据对齐 (裁切或填充到 8760 行)
                weather_df = st.session_state['weather_df'].copy()
                req_len = len(weather_df)

                if len(load_data) >= req_len:
                    weather_df['load_kw'] = load_data[:req_len]
                else:
                    # 如果数据不够一年，循环填充
                    tiled = np.tile(load_data, int(np.ceil(req_len / len(load_data))))
                    weather_df['load_kw'] = tiled[:req_len]

                st.session_state['final_df'] = weather_df

                # 展示前几行
                st.write("已合并数据预览:", weather_df[['time', 'gen_kw', 'load_kw']].head())
            else:
                st.error("文件中未找到数值列，请检查格式。")

        except Exception as e:
            st.error(f"文件解析错误: {e}")

# ================= TAB 2: 曲线对比 =================
with tab2:
    if 'final_df' in st.session_state:
        df = st.session_state['final_df']

        # 1. KPI 概览
        total_gen = df['gen_kw'].sum()
        total_load = df['load_kw'].sum()
        util_hours = total_gen / final_capacity  # 等效利用小时数

        k1, k2, k3 = st.columns(3)
        k1.metric("🌞 年总发电量", f"{total_gen / 10000:.2f} 万kWh")
        k2.metric("🏭 年总用电量", f"{total_load / 10000:.2f} 万kWh")
        k3.metric("⏱️ 等效利用小时数", f"{util_hours:.0f} 小时", help="反映当地光照资源水平")

        # 2. 交互式图表 (Plotly)
        st.subheader("🔍 发电 vs 用电 曲线透视")

        # 增加时间筛选器
        view_mode = st.radio("查看维度", ["典型日 (放大)", "全月视图", "全年概览"], horizontal=True)

        if view_mode == "典型日 (放大)":
            # 截取某一天
            day_df = df.iloc[1000:1048]  # 随便取的一天，实际可做日期选择器
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=day_df['time'], y=day_df['gen_kw'], fill='tozeroy', name='光伏发电',
                                     line=dict(color='#f1c40f')))
            fig.add_trace(
                go.Scatter(x=day_df['time'], y=day_df['load_kw'], name='用户负荷', line=dict(color='#2c3e50')))
            fig.update_layout(title="48小时典型日供需对比", yaxis_title="功率 (kW)")
            st.plotly_chart(fig, use_container_width=True)

        elif view_mode == "全月视图":
            month_df = df.set_index('time').resample('D').sum().reset_index()
            fig = go.Figure()
            fig.add_trace(go.Bar(x=month_df['time'], y=month_df['gen_kw'], name='日光伏电量'))
            fig.add_trace(
                go.Scatter(x=month_df['time'], y=month_df['load_kw'], name='日用电量', line=dict(color='red')))
            st.plotly_chart(fig, use_container_width=True)

        else:  # 全年
            fig = px.area(df, x='time', y=['gen_kw', 'load_kw'], title="全年8760小时概览 (由于数据量大，仅展示轮廓)")
            st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("请先在 Tab 1 完成数据导入。")

# ================= TAB 3: 储能建议 (核心算法) =================
with tab3:
    if 'final_df' in st.session_state:
        df = st.session_state['final_df']

        st.header("🔋 智能储能配置建议")

        # 计算逻辑：
        # 1. 净负荷 = 负荷 - 光伏
        # 2. 如果 净负荷 < 0: 光伏盈余，可充电
        # 3. 如果 净负荷 > 0: 供电缺口，需放电
        df['net_load'] = df['load_kw'] - df['gen_kw']

        # 按天统计每一天的 最大可充电量 和 最大需放电量
        daily_stats = df.set_index('time').resample('D').apply({
            'net_load': [
                lambda x: abs(x[x < 0].sum()),  # 当日盈余总量 (Surplus)
                lambda x: x[x > 0].sum()  # 当日缺口总量 (Deficit)
            ]
        })
        # 整理格式
        daily_analysis = pd.DataFrame(daily_stats['net_load'].tolist(), columns=['surplus', 'deficit'],
                                      index=daily_stats.index)

        # 核心算法：
        # 有效储能需求 = min(当日盈余, 当日缺口)
        # 意思是：存下来的电，晚上必须能用掉；或者晚上需要的电，白天必须存得够。
        daily_analysis['effective_storage'] = daily_analysis[['surplus', 'deficit']].min()

        # 排除 0 值（阴雨天或停产日）
        valid_days = daily_analysis[daily_analysis['effective_storage'] > 1]

        if not valid_days.empty:
            # 取 90% 分位数，避免因为极端的几天配置过大
            rec_capacity_kwh = valid_days['effective_storage'].quantile(0.90) / 0.9  # 除以0.9是考虑DOD

            # 推荐功率：一般按 0.5C (2小时系统) 或 1C 配置
            rec_power_kw = rec_capacity_kwh / 2

            # --- 结果展示 ---
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"""
                <div class="metric-card">
                    <h3>💡 推荐配置</h3>
                    <p style="font-size: 24px;"><b>{rec_power_kw:.0f} kW / {rec_capacity_kwh:.0f} kWh</b></p>
                    <p>系统类型: 2小时储能系统</p>
                </div>
                """, unsafe_allow_html=True)

            with c2:
                st.markdown("#### 📝 推荐理由")
                st.markdown(f"""
                - **消纳分析**: 根据您的用电曲线，系统计算了全年每一天的“光伏盈余”与“夜间缺口”。
                - **容量定值**: 选取了全年 **90%** 的场景都能满足的容量值，去除了极端天气影响。
                - **经济性**: 建议利用白天多余的 **{rec_capacity_kwh * .9:.0f} kWh** 电力存储，在晚间高峰释放，最大化自发自用率。
                """)

            # 可视化：储能充放电模拟图
            st.subheader("储能运行模拟 (全年每日需求分布)")
            st.bar_chart(daily_analysis['effective_storage'])
            st.caption("X轴: 日期, Y轴: 当日理论最佳储能吞吐量 (kWh)")

        else:
            st.warning("根据数据分析，光伏发电基本被实时消纳，或者负荷极大光伏极小，**不建议配置储能**，主要依靠市电补充。")

    else:
        st.info("等待数据分析...")streamlit run solar_pro.py
        streamlit
        pandas
        numpy
        requests
        plotly
        openpyxl