import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import io

# --- 1. 页面配置与 UI 美化 ---
st.set_page_config(page_title="光伏储能工程分析系统 Pro", layout="wide", page_icon="⚡")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .metric-card { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #2ecc71; margin-bottom: 15px;}
    </style>
    """, unsafe_allow_html=True)


# --- 新增：地理位置解析函数 (模糊搜索) ---
def get_coordinates(address):
    """通过开源地图接口将文字地址转为经纬度"""
    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'SolarEngineeringApp/1.0'}
    params = {'q': address, 'format': 'json', 'limit': 1}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        data = response.json()
        if len(data) > 0:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    return None, None


# --- 2. 核心工程逻辑 ---
class EngineeringModel:
    def __init__(self, lat, lon):
        self.lat = lat
        self.lon = lon

    def estimate_capacity(self, area_sqm, install_type):
        if install_type == "地面电站 (有间距)":
            power_density = 60
        else:
            power_density = 110
        return (area_sqm * power_density) / 1000, power_density

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
            return pd.DataFrame({
                'time': pd.to_datetime(data['hourly']['time']),
                'temp': data['hourly']['temperature_2m'],
                'ghi': data['hourly']['shortwave_radiation']
            })
        except:
            return pd.DataFrame()

    def simulate_generation(self, df, capacity_kw, pr=0.82):
        df['cell_temp'] = df['temp'] + 0.025 * df['ghi']
        temp_loss = 1 + (-0.004) * (df['cell_temp'] - 25)
        df['gen_kw'] = capacity_kw * (df['ghi'] / 1000) * pr * temp_loss
        df['gen_kw'] = df['gen_kw'].clip(lower=0)
        return df


# --- 初始化经纬度的 Session State ---
if 'lat_val' not in st.session_state:
    st.session_state.lat_val = 31.2300
if 'lon_val' not in st.session_state:
    st.session_state.lon_val = 121.4700
if 'lat_dir' not in st.session_state:
    st.session_state.lat_dir = "北纬 (N)"
if 'lon_dir' not in st.session_state:
    st.session_state.lon_dir = "东经 (E)"

# --- 3. 侧边栏：参数设置 ---
with st.sidebar:
    st.title("项目参数配置")

    with st.container(border=True):
        st.header("📍 地理位置")

        # --- 模糊搜索功能 ---
        search_address = st.text_input("快速定位", placeholder="输入城市或详细地址，如: 大同市")
        if st.button("🔍 智能解析地址", use_container_width=True):
            if search_address:
                with st.spinner("正在卫星定位..."):
                    found_lat, found_lon = get_coordinates(search_address)
                    if found_lat is not None:
                        # 自动判断南北纬、东西经
                        st.session_state.lat_dir = "北纬 (N)" if found_lat >= 0 else "南纬 (S)"
                        st.session_state.lat_val = abs(found_lat)
                        st.session_state.lon_dir = "东经 (E)" if found_lon >= 0 else "西经 (W)"
                        st.session_state.lon_val = abs(found_lon)
                        st.success("定位成功！")
                    else:
                        st.error("未能解析该地址，请尝试手动输入。")
            else:
                st.warning("请输入地址")

        st.markdown("---")

        # --- 精确经纬度输入 (带方向) ---
        c1, c2 = st.columns([1, 1.5])
        with c1:
            lat_dir = st.selectbox("纬度方向", ["北纬 (N)", "南纬 (S)"], key='lat_dir')
        with c2:
            lat_val = st.number_input("纬度", format="%.4f", min_value=0.0, max_value=90.0, key='lat_val')

        c3, c4 = st.columns([1, 1.5])
        with c3:
            lon_dir = st.selectbox("经度方向", ["东经 (E)", "西经 (W)"], key='lon_dir')
        with c4:
            lon_val = st.number_input("经度", format="%.4f", min_value=0.0, max_value=180.0, key='lon_val')

        # 计算实际用于气象 API 的带符号坐标 (北纬正, 南纬负; 东经正, 西经负)
        actual_lat = lat_val if "北纬" in lat_dir else -lat_val
        actual_lon = lon_val if "东经" in lon_dir else -lon_val

    with st.container(border=True):
        st.header("📐 土地与容量")
        install_type = st.selectbox("安装场景", ["地面电站 (有间距)", "工商业屋顶 (平铺)"])
        area_sqm = st.number_input("可用有效面积 (m²)", value=5000, step=100)

        model = EngineeringModel(actual_lat, actual_lon)
        est_cap, density = model.estimate_capacity(area_sqm, install_type)
        st.info(f"💡 建议装机容量: **{est_cap:.2f} kW**")
        final_capacity = st.number_input("确认设计容量 (kW)", value=float(f"{est_cap:.2f}"))

    with st.expander("⚙️ 高级工程参数", expanded=False):
        pr = st.slider("系统综合效率 (PR)", 0.75, 0.90, 0.82)

# --- 4. 主界面 ---
st.title("📊 光伏储能项目智能分析平台")

tab1, tab2, tab3 = st.tabs(["📂 1. 数据导入", "📈 2. 曲线对比", "🔋 3. 储能测算"])

if 'weather_df' not in st.session_state:
    st.session_state['weather_df'] = None

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.subheader("步骤 A: 导入用户负荷")
            st.markdown("为了保证数据准确，请务必使用标准模板。")
            df_template = pd.DataFrame({
                "时间参考 (不需要修改)": [f"第 {i + 1} 小时" for i in range(24)],
                "用电功率 (kW)": [100.0] * 24
            })
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_template.to_excel(writer, index=False, sheet_name='用电数据')
            st.download_button("📥 1. 点击下载标准数据模板", buffer.getvalue(), "光伏负荷测算模板.xlsx",
                               "application/vnd.ms-excel", type="primary")
            uploaded_file = st.file_uploader("📤 2. 填写后在此上传模板", type=['xlsx', 'xls'])

    with col2:
        with st.container(border=True):
            st.subheader("步骤 B: 获取气象资源")
            st.markdown(f"当前定位: **{lat_dir}{lat_val:.4f}, {lon_dir}{lon_val:.4f}**")
            if st.button("🌍 提取历史气象数据并建模", use_container_width=True):
                with st.spinner("正在连接气象卫星数据库..."):
                    df = model.fetch_historical_year()
                    if not df.empty:
                        df = model.simulate_generation(df, final_capacity, pr)
                        st.session_state['weather_df'] = df
                        st.success("✅ 模型生成完毕！请查看曲线对比。")
                    else:
                        st.error("获取失败，请重试或更换地点。")

    if uploaded_file is not None and st.session_state['weather_df'] is not None:
        try:
            load_df = pd.read_excel(uploaded_file)
            if "用电功率 (kW)" in load_df.columns:
                load_data = load_df["用电功率 (kW)"].values
                st.success("✅ 成功识别模板数据！")
            else:
                load_data = load_df.iloc[:, -1].values
                st.warning("⚠️ 未检测到标准格式，已自动提取最后一列数值。")

            weather_df = st.session_state['weather_df'].copy()
            req_len = len(weather_df)
            if len(load_data) >= req_len:
                weather_df['load_kw'] = load_data[:req_len]
            else:
                weather_df['load_kw'] = np.tile(load_data, int(np.ceil(req_len / len(load_data))))[:req_len]
            st.session_state['final_df'] = weather_df
        except:
            st.error("读取失败，请检查文件。")

with tab2:
    if 'final_df' in st.session_state:
        df = st.session_state['final_df']
        with st.container(border=True):
            k1, k2, k3 = st.columns(3)
            k1.metric("🌞 年总发电量", f"{df['gen_kw'].sum() / 10000:.2f} 万kWh")
            k2.metric("🏭 年总用电量", f"{df['load_kw'].sum() / 10000:.2f} 万kWh")
            k3.metric("⏱️ 等效利用小时数", f"{df['gen_kw'].sum() / final_capacity:.0f} 小时")

        view_mode = st.radio("查看维度", ["典型日视角", "全月视角", "全年视角"], horizontal=True)
        if view_mode == "典型日视角":
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.iloc[1000:1048]['time'], y=df.iloc[1000:1048]['gen_kw'], fill='tozeroy',
                                     name='光伏发电', line=dict(color='#f1c40f')))
            fig.add_trace(go.Scatter(x=df.iloc[1000:1048]['time'], y=df.iloc[1000:1048]['load_kw'], name='用户负荷',
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
            st.plotly_chart(px.area(df, x='time', y=['gen_kw', 'load_kw'], title="全年轮廓"), use_container_width=True)
    else:
        st.info("请先导入数据。")

with tab3:
    if 'final_df' in st.session_state:
        df = st.session_state['final_df']
        df['net_load'] = df['load_kw'] - df['gen_kw']
        daily = pd.DataFrame(df.set_index('time').resample('D').apply(
            {'net_load': [lambda x: abs(x[x < 0].sum()), lambda x: x[x > 0].sum()]})['net_load'].tolist(),
                             columns=['surplus', 'deficit'], index=df.set_index('time').resample('D').sum().index)
        daily['effective'] = daily[['surplus', 'deficit']].min()
        valid_days = daily[daily['effective'] > 1]

        with st.container(border=True):
            if not valid_days.empty:
                rec_cap = valid_days['effective'].quantile(0.90) / 0.9
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown(
                        f"""<div class="metric-card"><h3 style="color:#2c3e50;">🔋 推荐配置</h3><h2 style="color:#27ae60;">{rec_cap / 2:.0f} kW</h2><h2 style="color:#2980b9;">{rec_cap:.0f} kWh</h2></div>""",
                        unsafe_allow_html=True)
                with c2:
                    st.markdown("#### 📝 工程师诊断说明")
                    st.markdown(
                        f"基于全年回测，系统截取了 90% 的高频储能需求场景。\n\n建议配置 **{rec_cap:.0f}度** 电池，白天吸收盈余，夜间放电，实现收益最大化。")
            else:
                st.warning("光伏电量几乎被实时消纳，不建议配置储能。")
    else:
        st.info("请先导入数据。")