import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 页面配置 ---
st.set_page_config(page_title="光伏储能工程仿真系统", layout="wide", page_icon="☀")

# --- 侧边栏：参数设置 ---
with st.sidebar:
    st.header("⚙️ 工程参数设置")

    st.subheader("1. 电站参数")
    capacity = st.number_input("光伏装机容量 (kW)", value=100.0, step=10.0)
    pr = st.slider("系统综合效率 (PR)", 0.7, 0.9, 0.82)

    st.subheader("2. 地理位置")
    lat = st.number_input("纬度 (Latitude)", value=31.23, format="%.4f")
    lon = st.number_input("经度 (Longitude)", value=121.47, format="%.4f")

    st.subheader("3. 储能模拟")
    battery_cap = st.number_input("储能容量 (kWh)", value=0.0, step=10.0, help="设为0则不模拟储能")

    st.subheader("4. 经济性")
    elec_price = st.number_input("平均电价 (元/kWh)", value=0.8)


# --- 核心函数：获取气象数据 ---
@st.cache_data
def get_weather_data(lat, lon):
    """获取未来7天的每小时气象预测"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,shortwave_radiation",
        "timezone": "auto",
        "forecast_days": 7
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        df = pd.DataFrame({
            'time': pd.to_datetime(data['hourly']['time']),
            'temp': data['hourly']['temperature_2m'],
            'ghi': data['hourly']['shortwave_radiation']
        })
        return df
    except Exception as e:
        st.error(f"气象数据获取失败: {e}")
        return pd.DataFrame()


# --- 核心函数：光伏物理仿真 ---
def simulate_pv(df, capacity, pr):
    # 温度修正系数 (假设晶硅组件)
    temp_coeff = -0.004
    # 电池片温度估算 T_cell = T_air + 0.025 * GHI
    cell_temp = df['temp'] + 0.025 * df['ghi']
    correction = 1 + temp_coeff * (cell_temp - 25)

    # 发电量公式 P = Cap * (G/1000) * PR * Correction
    pv_out = capacity * (df['ghi'] / 1000) * pr * correction
    pv_out = pv_out.clip(lower=0)  # 修正负值
    return pv_out


# --- 主界面逻辑 ---
st.title("☀ 光伏+储能 智能仿真模型 (PV Engineer Pro)")

# 1. 数据加载区
col1, col2 = st.columns([1, 2])

with col1:
    st.info("上传负荷数据 (CSV格式，单列数据，无表头或表头为'load')")
    uploaded_file = st.file_uploader("拖入负荷曲线文件", type=['csv'])

# 初始化数据
weather_df = get_weather_data(lat, lon)

if not weather_df.empty:
    # 计算发电
    weather_df['pv_gen'] = simulate_pv(weather_df, capacity, pr)

    # 处理负荷数据
    if uploaded_file is not None:
        try:
            load_raw = pd.read_csv(uploaded_file)
            # 尝试获取第一列数据
            load_vals = load_raw.iloc[:, 0].values
            # 数据对齐逻辑：如果数据少，就循环填充；如果数据多，就截取
            needed_len = len(weather_df)
            if len(load_vals) < needed_len:
                # 重复填充 (例如只传了24小时，自动重复填满7天)
                repeats = (needed_len // len(load_vals)) + 1
                extended_load = np.tile(load_vals, repeats)[:needed_len]
                weather_df['load'] = extended_load
                st.success(f"已加载负荷数据，并自动延展至7天周期 ({len(load_vals)}点 -> {needed_len}点)")
            else:
                weather_df['load'] = load_vals[:needed_len]
                st.success("已加载高精度负荷数据")
        except Exception as e:
            st.error(f"文件解析失败: {e}")
            weather_df['load'] = 0
    else:
        st.warning("未上传负荷，使用默认模拟工厂曲线 (早8-晚6运行)")
        # 模拟负荷
        hours = weather_df['time'].dt.hour
        weather_df['load'] = np.where((hours >= 8) & (hours <= 18), capacity * 0.6, capacity * 0.1)

    # 计算供需平衡
    weather_df['net_load'] = weather_df['load'] - weather_df['pv_gen']

    # --- 储能逻辑 (简化版) ---
    # 假设简单策略：光伏多了充，光伏少了放
    soc = [0.0] * len(weather_df)  # 荷电状态 kWh
    battery_action = [0.0] * len(weather_df)  # 充放功率 (+放 -充)
    current_soc = battery_cap * 0.5  # 初始50%电量

    if battery_cap > 0:
        for i in range(len(weather_df)):
            net = weather_df.loc[i, 'net_load']

            if net < 0:  # 光伏盈余 -> 充电
                can_charge = battery_cap - current_soc
                actual_charge = min(abs(net), can_charge, battery_cap * 0.5)  # 限制倍率0.5C
                current_soc += actual_charge
                battery_action[i] = -actual_charge  # 记录为负(充电)

            elif net > 0:  # 缺电 -> 放电
                can_discharge = current_soc
                actual_discharge = min(net, can_discharge, battery_cap * 0.5)
                current_soc -= actual_discharge
                battery_action[i] = actual_discharge  # 记录为正(放电)

            soc[i] = current_soc

    weather_df['battery_power'] = battery_action
    weather_df['soc'] = soc
    weather_df['grid_power'] = weather_df['net_load'] - weather_df['battery_power']  # 最终买网电量

    # --- 结果展示区 ---
    st.markdown("---")

    # KPI 指标卡
    total_gen = weather_df['pv_gen'].sum()
    total_load = weather_df['load'].sum()
    self_use = total_gen - abs(weather_df[weather_df['net_load'] < 0]['net_load'].sum())  # 粗略自用
    if battery_cap > 0:
        # 如果有储能，自用量要加上电池充进去的那部分
        self_use += abs(sum(x for x in battery_action if x < 0))

    self_use_rate = (self_use / total_gen * 100) if total_gen > 0 else 0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("未来7天总发电", f"{total_gen:.1f} kWh")
    kpi2.metric("未来7天总用电", f"{total_load:.1f} kWh")
    kpi3.metric("光伏自发自用率", f"{self_use_rate:.1f} %")
    kpi4.metric("预估节省电费", f"¥ {(self_use * elec_price):.1f}")

    # --- 图表分析 ---
    tab1, tab2 = st.tabs(["📈 详细功率曲线", "📊 日/周 对比分析"])

    with tab1:
        st.subheader("源-网-荷-储 功率实时平衡")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=weather_df['time'], y=weather_df['pv_gen'], name='光伏发电', fill='tozeroy',
                                 line=dict(color='#f1c40f')))
        fig.add_trace(go.Scatter(x=weather_df['time'], y=weather_df['load'], name='用户负荷',
                                 line=dict(color='#2c3e50', width=3)))
        if battery_cap > 0:
            fig.add_trace(go.Scatter(x=weather_df['time'], y=weather_df['battery_power'], name='电池充放(正放负充)',
                                     line=dict(color='#27ae60', dash='dot')))

        fig.update_layout(height=500, xaxis_title="时间", yaxis_title="功率 (kW)", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("日均数据聚合对比")
        # 按日期重采样
        daily_df = weather_df.set_index('time').resample('D').sum()

        # 柱状图
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(x=daily_df.index, y=daily_df['pv_gen'], name='日发电量'))
        fig_bar.add_trace(go.Bar(x=daily_df.index, y=daily_df['load'], name='日用电量'))
        fig_bar.update_layout(barmode='group', height=400)
        st.plotly_chart(fig_bar, use_container_width=True)

        # 建议生成
        st.info("💡 **智能建议：**")
        daily_surplus = (daily_df['pv_gen'] - daily_df['load']).clip(lower=0).mean()
        if daily_surplus > 10:
            st.write(f"- 监测到日均盈余电量约 **{daily_surplus:.1f} kWh**。")
            st.write(f"- 建议配置储能容量： **{daily_surplus * 0.9:.1f} kWh** 以实现光伏全额消纳。")
        else:
            st.write("- 光伏电量基本被负荷完全消纳，当前无需大规模配置储能。")

else:
    st.info("请等待数据加载...")


    