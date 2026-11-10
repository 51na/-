import streamlit as st
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import time

# ---------------------------------------------------------
# 1. 페이지 설정 및 초기화
# ---------------------------------------------------------
st.set_page_config(
    page_title="개인 걸음속도 맞춤형 보행 및 지름길 공유 앱",
    page_icon="🚶",
    layout="wide"
)

st.title("🚶 개인 걸음속도 맞춤형 보행 및 지름길 공유 앱")
st.markdown("사용자의 걸음 속도를 반영한 최적의 보행 경로를 안내하고, 나만의 지름길을 공유하는 공간입니다.")

if "custom_shortcuts" not in st.session_state:
    st.session_state["custom_shortcuts"] = []

# ---------------------------------------------------------
# 2. 사이드바 사용자 설정
# ---------------------------------------------------------
st.sidebar.header("⚙️ 사용자 및 경로 설정")

# 걸음 속도 슬라이더 (km/h -> m/s 변환)
speed_kmh = st.sidebar.slider("개인 걸음 속도 (km/h)", min_value=2.0, max_value=6.0, value=4.5, step=0.1)
speed_ms = speed_kmh * 1000 / 3600

# 분석 기준 중심점 및 반경 설정 (에러 방지를 위해 좌표 중심 반경 방식 사용)
st.sidebar.subheader("📍 분석 범위 설정")
center_query = st.sidebar.text_input("중심 기준 장소", value="Gangnam Station, Seoul")
dist_meters = st.sidebar.slider("탐색 반경 (미터)", min_value=500, max_value=3000, value=1500, step=100)

# 출발지 및 목적지 입력
st.sidebar.subheader("📍 출발지 및 목적지 설정")
orig_query = st.sidebar.text_input("출발지", value="Gangnam Station, Seoul")
dest_query = st.sidebar.text_input("목적지", value="Yeoksam Station, Seoul")

# 지름길 등록 폼
st.sidebar.subheader("➕ 나만의 지름길 등록")
with st.sidebar.form("shortcut_form"):
    shortcut_name = st.text_input("지름길 이름 (예: 뒷골목 지름길)")
    orig_desc = st.text_input("출발지 위치")
    dest_desc = st.text_input("도착지 위치")
    shortcut_time = st.number_input("단축 예상 소요 시간 (분)", min_value=1, value=2)
    submitted = st.form_submit_button("지름길 등록하기")
    
    if submitted:
        if shortcut_name and orig_desc and dest_desc:
            st.session_state["custom_shortcuts"].append({
                "name": shortcut_name,
                "orig": orig_desc,
                "dest": dest_desc,
                "time": shortcut_time
            })
            st.sidebar.success(f"'{shortcut_name}' 지름길 등록 완료!")
        else:
            st.sidebar.error("모든 항목을 입력해주세요.")

# ---------------------------------------------------------
# 3. 네트워크 데이터 로딩 (좌표 중심 + 자동 재시도 적용)
# ---------------------------------------------------------
@st.cache_data(show_spinner=True)
def load_pedestrian_network(center_text, dist):
    """중심 장소를 좌표로 변환한 뒤, 반경 내 보행자 도로망을 다운로드합니다 (502 에러 방지용 재시도 포함)."""
    max_retries = 3
    delay = 3
    
    for attempt in range(max_retries):
        try:
            ox.settings.timeout = 60
            # 주소를 위도/경도 좌표(Point)로 안전하게 변환
            point = ox.geocode(center_text)
            # 폴곤 에러가 나지 않는 graph_from_point 방식 사용
            return ox.graph_from_point(point, dist=dist, network_type="walk")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
            else:
                raise e

try:
    with st.spinner(f"'{center_query}' 기준 반경 {dist_meters}m 보행 도로망을 불러오는 중..."):
        G = load_pedestrian_network(center_query, dist_meters)
except Exception as e:
    st.error(f"도로망 로딩 중 오류 발생: {e}")
    st.stop()

# 등록된 커스텀 지름길 목록 표시
if st.session_state["custom_shortcuts"]:
    st.sidebar.write("---")
    st.sidebar.markdown("**📌 등록된 커스텀 지름길**")
    for idx, sc in enumerate(st.session_state["custom_shortcuts"]):
        st.sidebar.text(f"{idx+1}. {sc['name']} ({sc['time']}분 단축)")

# ---------------------------------------------------------
# 4. 주소를 노드로 변환하는 함수
# ---------------------------------------------------------
def get_node_from_query(query, graph):
    try:
        point = ox.geocode(query)
        node = ox.distance.nearest_nodes(graph, X=point[1], Y=point[0])
        return node, point
    except Exception:
        return None, None

# ---------------------------------------------------------
# 5. 메인 화면 및 지도 시각화
# ---------------------------------------------------------
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🗺️ 보행 및 환승 경로 지도")
    
    try:
        center_point = ox.geocode(center_query)
    except:
        center_point = (37.4979, 127.0276)
        
    m = folium.Map(location=center_point, zoom_start=15)
    
    if st.button("🚀 최적 경로 탐색 및 환승 보정 계산"):
        orig_node, orig_coord = get_node_from_query(orig_query, G)
        dest_node, dest_coord = get_node_from_query(dest_query, G)
        
        if orig_node is None or dest_node is None:
            st.error("출발지 또는 목적지를 찾을 수 없습니다. 설정한 탐색 반경 내의 정확한 장소명을 입력해주세요.")
        else:
            # 에지에 개인 걸음 속도 가중치 부여
            for u, v, data in G.edges(data=True):
                length = data.get('length', 1.0)
                data['travel_time'] = length / speed_ms
                
            try:
                # 최단 경로 탐색
                path_nodes = nx.shortest_path(G, orig_node, dest_node, weight='travel_time')
                path_length = nx.path_weight(G, path_nodes, weight='length')
                path_time_sec = nx.path_weight(G, path_nodes, weight='travel_time')
                path_time_min = path_time_sec / 60.0
                
                # 지도에 선 그리기
                node_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in path_nodes]
                folium.PolyLine(node_coords, color="blue", weight=6, opacity=0.8, tooltip="최적 보행 경로").add_to(m)
                
                folium.Marker(orig_coord, popup=f"출발지: {orig_query}", icon=folium.Icon(color="green", icon="play")).add_to(m)
                folium.Marker(dest_coord, popup=f"목적지: {dest_query}", icon=folium.Icon(color="red", icon="stop")).add_to(m)
                
                # 우측 결과 패널 출력
                with col2:
                    st.success("경로 탐색 완료!")
                    st.metric("총 보행 거리", f"{path_length:.1f} m")
                    st.metric("예상 보행 시간", f"{path_time_min:.1f} 분", delta=f"속도 {speed_kmh} km/h")
                    
                    st.markdown("---")
                    st.subheader("🚇 지하철 환승 시간 보정")
                    standard_transfer = 5.0
                    adjusted_transfer = standard_transfer * (4.0 / speed_kmh)
                    st.info(f"환승 소요 시간: **{adjusted_transfer:.1f}분** (기준 속도 대비 보정)")
                    
            except nx.NetworkXNoPath:
                st.error("지정한 두 지점 사이에 연결된 보행자 도로가 없습니다. 탐색 반경이나 위치를 확인해주세요.")
            except Exception as e:
                st.error(f"경로 계산 중 오류 발생: {e}")
    else:
        folium.Marker(center_point, popup="탐색 기준 중심", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)

    st_data = st_folium(m, width=700, height=500)

with col2:
    st.markdown("### 💡 이용 가이드")
    st.markdown("""
    - **분석 범위**: 특정 중심 장소와 반경(미터)을 설정하여 안정적으로 도로망을 불러옵니다.
    - **속도 조절**: 사이드바에서 본인의 속도를 바꾸면 시간이 실시간 재계산됩니다.
    - **지름길 등록**: 나만의 지름길을 입력해 목록에서 관리할 수 있습니다.
    """)
