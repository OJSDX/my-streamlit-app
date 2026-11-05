
import base64
import html
import json
import math
import os
import time
from io import BytesIO

import requests
import streamlit as st
from openai import OpenAI
from PIL import Image

# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="Thumbs Up | AI Voice Assistant",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# API 키: Streamlit Cloud > Settings > Secrets 에 OPENAI_API_KEY = "sk-..." 로 저장
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"], timeout=30.0, max_retries=1)

# 역할 부여
sys_role = """
당신은 '김 대리'의 개인 비서 '에이블'입니다.
김 대리가 음성으로 물어본 지역의 날씨와 미세먼지 정보를 바탕으로
오늘 하루를 준비할 수 있도록 친절하고 간결하게 안내합니다.

답변은 다음 순서로 작성하세요.
1. 해당 지역의 날씨 요약 (기온, 체감온도)
   - 데이터에 [강수 확률]이 있을 때만 비·눈·우산을 언급하세요.
   - [강수 확률]이 없으면 강수 확률, 비, 눈, 우산에 대해 아무 말도 하지 마세요.
2. 미세먼지 상태
   - 수치(숫자)는 절대 말하지 말고 '좋음', '보통', '나쁨', '매우 나쁨' 등급만 말하세요.
3. 추천 의상
   - 반드시 [기온별 옷차림 가이드]에 있는 옷 중에서 추천하세요.
   - 현재 체감온도 기준 옷차림을 중심으로 안내하고,
     일교차가 크면 아침/저녁에 걸칠 겉옷도 함께 안내하세요.
   - 가이드에 팁이 있으면 꼭 함께 전달하세요.
4. 챙겨야 할 준비물 (미세먼지 나쁨 이상 → 마스크,
   자외선이 강하거나 맑고 더운 날 → 선글라스·선크림, 일교차가 큰 날 → 겉옷,
   [강수 확률]이 데이터에 있을 때만 비/눈 → 우산 등)

주어진 데이터에 없는 수치는 지어내지 마세요.
일교차가 큰 경우 일교차의 온도 수치는 말하지 말고 '일교차가 크다'고만 말하세요.
답변은 전체 6문장 이내로 간결하게 작성하세요.
음성으로 읽을 내용이므로 이모지, 특수기호, 마크다운 표기는 쓰지 말고 자연스러운 문장으로 작성하세요.
"""

# ---------------------------------------------------------
# 날씨 코드 → 한글 설명 (WMO 코드)
# ---------------------------------------------------------
WEATHER_CODE = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림",
    45: "안개", 48: "짙은 안개",
    51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈",
    80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
    95: "뇌우", 96: "우박을 동반한 뇌우", 99: "강한 우박을 동반한 뇌우",
}


# ---------------------------------------------------------
# 미세먼지 등급 (한국 환경부 기준)
# ---------------------------------------------------------
def grade_pm10(v):
    if v <= 30:
        return "좋음"
    if v <= 80:
        return "보통"
    if v <= 150:
        return "나쁨"
    return "매우 나쁨"


def grade_pm25(v):
    if v <= 15:
        return "좋음"
    if v <= 35:
        return "보통"
    if v <= 75:
        return "나쁨"
    return "매우 나쁨"


# ---------------------------------------------------------
# 기온별 옷차림 가이드 (첨부 이미지 기준)
# (최저 기온 기준, 옷 목록, 추가 팁) - 높은 온도 구간부터 순서대로
# ---------------------------------------------------------
CLOTHING_GUIDE = [
    (28, "민소매, 반팔, 반바지, 치마", ""),
    (23, "반팔, 얇은 셔츠, 반바지, 면바지", ""),
    (20, "얇은 가디건, 긴팔티, 면바지, 청바지", ""),
    (17, "얇은 니트, 가디건, 맨투맨, 얇은 자켓, 면바지, 청바지", ""),
    (12, "자켓, 가디건, 야상, 맨투맨, 니트, 스타킹, 청바지, 면바지", ""),
    (9, "자켓, 트렌치코트, 야상, 니트, 스타킹, 청바지, 면바지", "아우터 안에 가디건을 꼭 입으세요"),
    (5, "코트, 히트텍, 니트, 청바지, 레깅스", "레이어드(겹쳐 입기)가 필수예요"),
    (-100, "패딩, 두꺼운 코트, 목도리, 기모 제품", "최대한 많이 껴입으세요"),
]


def get_clothing(temp):
    """기온(℃)에 맞는 옷차림과 팁을 반환"""
    for min_temp, clothes, tip in CLOTHING_GUIDE:
        if temp >= min_temp:
            return clothes, tip
    return CLOTHING_GUIDE[-1][1], CLOTHING_GUIDE[-1][2]


def with_tip(clothes, tip):
    """옷 목록 뒤에 팁이 있으면 괄호로 붙여서 반환"""
    if tip:
        return clothes + " (" + tip + ")"
    return clothes


# ---------------------------------------------------------
# 도 단위·별칭 → 대표 도시 (한글명, 영문명, 소속 시·도)
# ---------------------------------------------------------
REGION_ALIAS = {
    "제주도": ("제주시", "Jeju City", "제주특별자치도"),
    "제주": ("제주시", "Jeju City", "제주특별자치도"),
    "제주특별자치도": ("제주시", "Jeju City", "제주특별자치도"),
    "경기도": ("수원시", "Suwon", "경기도"),
    "경기": ("수원시", "Suwon", "경기도"),
    "강원도": ("춘천시", "Chuncheon", "강원특별자치도"),
    "강원특별자치도": ("춘천시", "Chuncheon", "강원특별자치도"),
    "충청북도": ("청주시", "Cheongju", "충청북도"),
    "충북": ("청주시", "Cheongju", "충청북도"),
    "충청남도": ("홍성군", "Hongseong", "충청남도"),
    "충남": ("홍성군", "Hongseong", "충청남도"),
    "전라북도": ("전주시", "Jeonju", "전북특별자치도"),
    "전북": ("전주시", "Jeonju", "전북특별자치도"),
    "전북특별자치도": ("전주시", "Jeonju", "전북특별자치도"),
    "전라남도": ("무안군", "Muan", "전라남도"),
    "전남": ("무안군", "Muan", "전라남도"),
    "경상북도": ("안동시", "Andong", "경상북도"),
    "경북": ("안동시", "Andong", "경상북도"),
    "경상남도": ("창원시", "Changwon", "경상남도"),
    "경남": ("창원시", "Changwon", "경상남도"),
    "세종": ("세종시", "Sejong", "세종특별자치시"),
    "세종시": ("세종시", "Sejong", "세종특별자치시"),
}


def apply_alias(location):
    """도 단위 이름이면 대표 도시로 바꿔서 반환"""
    key = location.get("korean", "").replace(" ", "")
    if key in REGION_ALIAS:
        korean, english, province = REGION_ALIAS[key]
        return {"korean": korean, "english": english,
                "province": province, "parent": ""}
    return location


# ---------------------------------------------------------
# 1) 음성 → 텍스트 (STT)
# ---------------------------------------------------------
def speech_to_text(audio_file):
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=("question.wav", audio_file.getvalue()),
        language="ko",
    )
    return transcript.text


# ---------------------------------------------------------
# 2) 질문에서 지역명 추출 (LLM)
# ---------------------------------------------------------
def extract_location(question):
    empty = {"korean": "", "english": "", "province": "", "parent": ""}

    res = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content":
                "사용자 질문에서 날씨를 묻는 대한민국 지역을 추출해 JSON으로만 답하세요. "
                "키는 korean(질문에 나온 지역명, 한글), english(그 지역의 영문 표기), "
                "province(소속 시·도의 정식 명칭. 예: 서울특별시, 경기도, 전라남도), "
                "parent(소속 시·군·구. 시·도 자체를 물었으면 빈 문자열)입니다. "
                '예: {"korean": "강남구", "english": "Gangnam-gu", '
                '"province": "서울특별시", "parent": ""} '
                "질문에 지역이 없거나 어느 지역인지 알 수 없으면 추측하지 말고 "
                '{"korean": "", "english": "", "province": "", "parent": ""} 로 답하세요.'},
            {"role": "user", "content": question},
        ],
    )
    text = res.output_text.strip().replace("```json", "").replace("```", "")
    try:
        result = json.loads(text)
        if not result.get("korean"):
            return empty
        return result
    except Exception:
        return empty


# ---------------------------------------------------------
# 3) 지역명 → 위도/경도 (지오코딩)
# ---------------------------------------------------------
def geocode(location):
    location = apply_alias(location)

    url = "https://geocoding-api.open-meteo.com/v1/search"
    province = location.get("province", "")

    # 한글 → 영문 → 상위 지역 순서로 검색 시도
    candidates = [location.get("korean"), location.get("english"), location.get("parent")]

    for name in candidates:
        if not name:
            continue
        params = {"name": name, "count": 10, "language": "ko", "countryCode": "KR"}
        data = requests.get(url, params=params, timeout=10).json()
        results = data.get("results")
        if not results:
            continue

        # 시·도가 일치하는 후보를 우선 선택 (동명 지역 문제 방지)
        picked = results[0]
        for r in results:
            if province and r.get("admin1") == province:
                picked = r
                break

        place = picked["name"]
        admin1 = picked.get("admin1", "")
        if admin1 and admin1 not in place:
            place = admin1 + " " + place
        return {"name": place, "lat": picked["latitude"], "lon": picked["longitude"]}

    return None


# ---------------------------------------------------------
# 4) 날씨 + 미세먼지 조회
# ---------------------------------------------------------
def get_weather(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max",
        "timezone": "auto",
        "forecast_days": 1,
    }
    return requests.get(url, params=params, timeout=10).json()


def get_air_quality(lat, lon):
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm10,pm2_5",
        "timezone": "auto",
    }
    return requests.get(url, params=params, timeout=10).json()


def build_weather_summary(place, weather, air):
    cur, daily = weather["current"], weather["daily"]
    pm10, pm25 = air["current"]["pm10"], air["current"]["pm2_5"]

    feels = cur["apparent_temperature"]
    t_min = daily["temperature_2m_min"][0]
    t_max = daily["temperature_2m_max"][0]
    diff = round(t_max - t_min, 1)

    # 기온대별 옷차림 (체감 / 아침·저녁 / 낮)
    now_clothes, now_tip = get_clothing(feels)
    morning_clothes, morning_tip = get_clothing(t_min)
    day_clothes, day_tip = get_clothing(t_max)

    now_text = with_tip(now_clothes, now_tip)
    morning_text = with_tip(morning_clothes, morning_tip)
    day_text = with_tip(day_clothes, day_tip)

    if diff >= 10:
        diff_text = "일교차가 큽니다. 벗고 입기 편한 겉옷을 챙기세요."
    else:
        diff_text = "일교차가 크지 않습니다."

    weather_name = WEATHER_CODE.get(cur["weather_code"], "알 수 없음")

    # 강수 확률이 30% 미만이면 아예 데이터에 넣지 않음
    rain_prob = daily["precipitation_probability_max"][0] or 0
    if rain_prob >= 30:
        rain_text = "[강수 확률] " + str(rain_prob) + "%\n"
    else:
        rain_text = ""

    # 현재 비/눈이 오고 있을 때만 강수량 포함
    if cur["precipitation"] > 0:
        precip_text = "[현재 강수량] " + str(cur["precipitation"]) + "mm\n"
    else:
        precip_text = ""

    summary = f"""
[지역] {place}
[현재 날씨] {weather_name}
[현재 기온] {cur['temperature_2m']}도 (체감 {feels}도)
[오늘 최저/최고 기온] {t_min}도 / {t_max}도
{rain_text}{precip_text}[풍속] {cur['wind_speed_10m']}km/h
[자외선 지수 최대] {daily['uv_index_max'][0]}
[미세먼지] {grade_pm10(pm10)}
[초미세먼지] {grade_pm25(pm25)}

[기온별 옷차림 가이드]
- 현재 체감온도({feels}도) 기준: {now_text}
- 아침/저녁 최저기온({t_min}도) 기준: {morning_text}
- 낮 최고기온({t_max}도) 기준: {day_text}
- 일교차 안내: {diff_text}
"""
    return summary


# ---------------------------------------------------------
# 첨부 이미지 준비 (크기를 줄여서 빠르게 전달)
# ---------------------------------------------------------
def prepare_image(uploaded_file):
    """업로드한 jpg/png를 최대 1024px, JPEG로 줄여서 반환. 실패하면 None"""
    try:
        img = Image.open(BytesIO(uploaded_file.getvalue()))
        img = img.convert("RGB")
        img.thumbnail((1024, 1024))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return {"bytes": buf.getvalue(), "mime": "image/jpeg"}
    except Exception:
        return None


# ---------------------------------------------------------
# 5) 답변 생성 (LLM)
# ---------------------------------------------------------
def make_answer(question, weather_summary, memo="", image=None):
    prompt = f"""
[김 대리의 질문]
{question}

[조회된 날씨 데이터]
{weather_summary}
"""
    # 첨부한 TXT 메모가 있으면 참고 자료로 함께 전달
    if memo:
        prompt += "\n[첨부 메모]\n" + memo + "\n"
        prompt += "(첨부 메모는 참고용입니다. 오늘 날씨와 관련된 일정이 있을 때만 준비물에 반영하세요.)\n"

    # 첨부한 이미지가 있으면 함께 전달
    if image is not None:
        prompt += "\n[첨부 이미지]가 함께 전달되었습니다. 질문이나 오늘 날씨와 관련 있을 때만 참고하세요.\n"

    content = [{"type": "input_text", "text": prompt}]
    if image is not None:
        b64 = base64.b64encode(image["bytes"]).decode("utf-8")
        content.append({
            "type": "input_image",
            "image_url": "data:" + image["mime"] + ";base64," + b64,
        })

    res = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": sys_role},
            {"role": "user", "content": content},
        ],
    )
    return res.output_text


# ---------------------------------------------------------
# 6) 텍스트 → 음성 (TTS)
# ---------------------------------------------------------
def text_to_speech(text, voice="nova"):
    speech = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
        instructions="친절하고 또렷한 비서의 톤으로 읽어주세요",
    )
    return speech.content  # mp3 bytes


# =========================================================
# 화면 디자인 (CSS)
# =========================================================
ASSISTANT_IMG = "assistant.png"  # 비서 캐릭터 이미지 (app.py와 같은 폴더에 저장)

ANSWER_MODES = ["음성 + 텍스트", "텍스트만", "음성만"]
VOICES = {
    "nova": "Nova (기본)",
    "alloy": "Alloy",
    "shimmer": "Shimmer",
    "coral": "Coral",
    "sage": "Sage",
    "onyx": "Onyx",
}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap');
html, body, .stApp, .stApp *:not([data-testid="stIconMaterial"]) { font-family: 'Noto Sans KR', sans-serif; }
.stApp { background: linear-gradient(160deg, #fdfcff 0%, #f6f2ff 55%, #fff4fb 100%); }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.4rem; padding-bottom: 3rem; max-width: 1280px; }
.tu-title { font-size: 3.1rem; font-weight: 800; color: #1f2033; line-height: 1.22; margin: 0; letter-spacing: -0.02em; }
.tu-title .tu-accent { background: linear-gradient(90deg, #8b6cf0, #e58be0); -webkit-background-clip: text; background-clip: text; color: transparent; }
.tu-sub { color: #7a7890; font-size: 1.05rem; margin: 14px 0 26px 0; }
.tu-card { background: #ffffff; border: 1px solid #ece8f7; border-radius: 28px; box-shadow: 0 12px 40px rgba(139, 108, 240, 0.10); padding: 34px 38px; min-height: 300px; }
.tu-placeholder { color: #bdb9d2; font-size: 1.9rem; font-weight: 500; padding-top: 6px; }
.tu-label { color: #8a86a3; font-size: 0.85rem; font-weight: 500; margin-bottom: 8px; }
.tu-question { color: #1f2033; font-size: 1.55rem; font-weight: 700; line-height: 1.5; }
.tu-wait { color: #bdb9d2; font-size: 1.05rem; font-weight: 500; animation: tu-blink 1.6s ease-in-out infinite; }
@keyframes tu-blink { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
.tu-divider { height: 1px; background: #efebfa; margin: 22px 0 18px 0; }
.tu-answer { color: #34344a; font-size: 1.12rem; line-height: 1.85; }
.st-key-recwrap { position: relative; margin: 22px 0 6px 0; }
.tu-wave { display: flex; align-items: center; height: 96px; gap: 18px; }
.tu-side { flex: 1; display: flex; align-items: center; justify-content: space-between; height: 96px; }
.tu-bar { width: 3px; height: 3px; border-radius: 99px; opacity: var(--o); }
.tu-side.left .tu-bar { background: linear-gradient(180deg, #b9d3ff, #8fa8ff); }
.tu-side.right .tu-bar { background: linear-gradient(180deg, #f6b4e6, #ee8fd6); }
.tu-mic { position: relative; width: 76px; height: 76px; flex: none; border-radius: 50%; background: #ffffff; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 0 10px rgba(139, 108, 240, 0.08), 0 10px 30px rgba(139, 108, 240, 0.25); transition: transform 0.2s, background 0.3s; }
.tu-micsvg { display: flex; }
.tu-mic .tu-stop { display: none; }
.tu-rec-txt { display: none; }
.stApp:has([data-testid="stAudioInputActionButton"][aria-label="Record"]:hover) .tu-mic { transform: scale(1.06); }
.stApp:has([aria-label="Stop recording"]) .tu-bar, .stApp:has(.tu-busy) .tu-bar { animation: tu-bar 1s ease-in-out infinite; animation-delay: calc(var(--i) * -0.09s); }
.stApp:has([aria-label="Stop recording"]) .tu-mic { background: linear-gradient(135deg, #8b6cf0, #e58be0); animation: tu-pulse 1.4s ease-in-out infinite; }
.stApp:has([aria-label="Stop recording"]) .tu-micsvg { display: none; }
.stApp:has([aria-label="Stop recording"]) .tu-mic .tu-stop { display: flex; }
.stApp:has([aria-label="Stop recording"]) .tu-txt { display: none; }
.stApp:has([aria-label="Stop recording"]) .tu-rec-txt { display: inline; }
@keyframes tu-bar { 0%, 100% { height: 3px; } 50% { height: var(--h); } }
@keyframes tu-pulse { 0%, 100% { box-shadow: 0 0 0 8px rgba(229, 139, 224, 0.18), 0 10px 30px rgba(139, 108, 240, 0.30); } 50% { box-shadow: 0 0 0 18px rgba(229, 139, 224, 0.10), 0 10px 36px rgba(139, 108, 240, 0.40); } }
[class*="st-key-rec_"] { position: absolute; top: 10px; left: 50%; transform: translateX(-50%); width: 76px; height: 76px; z-index: 6; margin: 0; }
[class*="st-key-rec_"] [data-testid="stAudioInput"] { position: relative; width: 76px; height: 76px; min-height: 0; padding: 0; margin: 0; border: none; background: transparent; opacity: 0; overflow: hidden; border-radius: 50%; }
[class*="st-key-rec_"] [data-testid="stAudioInputActionButton"] { position: absolute; top: 0; left: 0; width: 76px; height: 76px; border-radius: 50%; cursor: pointer; }
[class*="st-key-rec_"] [data-testid="stAudioInputActionButton"]:not([aria-label="Record"]):not([aria-label="Stop recording"]) { display: none; }
[class*="st-key-rec_"] [data-testid="stAudioInput"] * { pointer-events: none; }
[class*="st-key-rec_"] [data-testid="stAudioInputActionButton"] { pointer-events: auto; }
[class*="st-key-rec_"] [data-testid="stAudioInputWaveSurfer"], [class*="st-key-rec_"] [data-testid="stAudioInputWaveformTimeCode"] { display: none; }
.tu-status { word-break: keep-all; margin-top: 30px; padding: 14px 18px; border-radius: 16px; text-align: center; font-size: 0.98rem; font-weight: 500; }
.tu-idle { background: #f1ecff; color: #5b45c4; }
.tu-busy { background: #ece4ff; color: #6b52d9; }
.tu-done { background: #fdeef8; color: #b0408f; }
.tu-error { background: #ffe9ef; color: #c0364f; }
[data-testid="stFileUploader"] section { background: #f6f4fb; border: 1px dashed #d9d0f5; border-radius: 18px; }
[data-testid="stFileUploader"] label p { color: #5b5877; font-size: 0.9rem; font-weight: 500; }
[data-testid="stFileUploader"] button { border-radius: 12px; border: 1px solid #d9d0f5; color: #6b52d9; background: #ffffff; }
.stButton > button { border-radius: 999px; border: 1px solid #e3dcf7; background: #ffffff; color: #6b52d9; font-weight: 600; padding: 0.55rem 1.1rem; box-shadow: 0 4px 14px rgba(139, 108, 240, 0.08); }
.stButton > button:hover { border-color: #b9a6f5; background: #f5f1ff; color: #5b45c4; }

.st-key-toggle_sidebar button { min-height: 42px; width: 100%; border-radius: 999px; border: 1px solid #e3dcf7; background: #ffffff; color: #6b52d9; font-weight: 600; padding: 0.55rem 0.6rem; box-shadow: 0 4px 14px rgba(139, 108, 240, 0.08); }
.st-key-toggle_sidebar button:hover { border-color: #b9a6f5; background: #f5f1ff; color: #5b45c4; }

.st-key-settings_panel { background: #ffffff; border: 1px solid #ece8f7; border-radius: 28px; box-shadow: 0 12px 40px rgba(139, 108, 240, 0.10); padding: 22px 24px; }
.tu-panel-title { color: #1f2033; font-size: 1.25rem; font-weight: 800; padding-bottom: 12px; border-bottom: 1px solid #efebfa; margin-bottom: 16px; }
.tu-panel-sec { color: #1f2033; font-size: 0.98rem; font-weight: 700; margin: 18px 0 6px 0; }
.tu-ver { color: #b5b1c9; font-size: 0.72rem; margin-top: 28px; }
[data-testid="stAudio"] audio { width: 100%; border-radius: 999px; background: #f5f1ff; }
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #ece8f7; }
.tu-brand { color: #1f2033; font-size: 1.25rem; font-weight: 800; margin-top: 6px; }
.tu-brand span { color: #8b6cf0; font-size: 0.8rem; font-weight: 500; margin-left: 8px; }
.tu-menu-title { color: #8a86a3; font-size: 0.8rem; font-weight: 600; margin: 24px 0 10px 0; }
.tu-menu-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-radius: 14px; margin-bottom: 6px; color: #34344a; font-size: 0.95rem; font-weight: 500; }
.tu-menu-item.active { background: #f1ecff; color: #5b45c4; font-weight: 700; }
.tu-menu-item.disabled { color: #a9a6bd; }
.tu-badge { font-size: 0.7rem; background: #f6f4fb; color: #8a86a3; border-radius: 99px; padding: 2px 9px; font-weight: 500; }
.st-key-hero { position: fixed; right: 0; bottom: 0; width: min(46vw, 82vh); z-index: 0; pointer-events: none; margin: 0; padding: 0; }
.st-key-hero img { display: block; width: 100%; height: auto; }
@media (max-width: 900px) { .st-key-hero { display: none; } }
"""

# ---------------------------------------------------------
# 사이드 메뉴 열림/닫힘 (설정 버튼 옆 메뉴 버튼으로 여닫기)
# ---------------------------------------------------------
st.session_state.setdefault("show_sidebar", False)  # True로 바꾸면 처음부터 열려 있음

# 기본 '<<', '>>' 아이콘은 숨기고, 설정 버튼 옆의 메뉴 버튼만 사용
CSS += '[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapsedControl"] { display: none; }\n'
CSS += ".tu-brand { margin: 6px 0 18px 0; }\n"
CSS += ".tu-badge { white-space: nowrap; flex: none; margin-left: 8px; }\n"
CSS += ".tu-title { font-size: clamp(1.8rem, 3.8vw, 3.1rem); }\n"

if st.session_state["show_sidebar"]:
    # 사이드 메뉴가 본문을 밀지 않고, 본문 위에 겹쳐서 열리게 함
    CSS += '[data-testid="stSidebar"] { position: fixed !important; top: 0 !important; left: 0 !important; height: 100vh !important; box-shadow: 12px 0 48px rgba(139, 108, 240, 0.22); }\n'
else:
    CSS += '[data-testid="stSidebar"] { display: none; }\n'

st.markdown("<style>" + CSS + "</style>", unsafe_allow_html=True)


TITLE_HTML = (
    '<div class="tu-title">Thumbs Up,<br>'
    'Your <span class="tu-accent">professional</span> AI Voice Assistant</div>'
    '<div class="tu-sub">당신만의 AI Voice Assistant ThumbsUp입니다.</div>'
)

MIC_SVG = (
    '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#8b6cf0" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="9" y="2" width="6" height="12" rx="3" fill="#8b6cf0"></rect>'
    '<path d="M5 11a7 7 0 0 0 14 0"></path>'
    '<line x1="12" y1="18" x2="12" y2="22"></line></svg>'
)

STOP_SVG = (
    '<svg width="28" height="28" viewBox="0 0 24 24">'
    '<rect x="5" y="5" width="14" height="14" rx="3" fill="#ffffff"></rect></svg>'
)


def build_bars(side, n=30):
    """파형 막대 생성. 원에 가까울수록 높고, 안쪽에서 바깥쪽으로 물결이 퍼짐"""
    bars = ""
    for p in range(n):
        # 왼쪽은 바깥→안쪽, 오른쪽은 안쪽→바깥 순서로 배치
        near = p / (n - 1) if side == "left" else 1 - p / (n - 1)
        dist = n - 1 - p if side == "left" else p
        shift = 0 if side == "left" else 1.3
        wobble = 0.55 + 0.45 * abs(math.sin(dist * 1.7 + shift))
        height = int(6 + 44 * (near ** 1.4) * wobble)
        opacity = round(0.25 + 0.75 * near, 2)
        bars += (
            '<span class="tu-bar" style="--h:' + str(height) + 'px;--o:' + str(opacity)
            + ';--i:' + str(dist) + '"></span>'
        )
    return '<div class="tu-side ' + side + '">' + bars + '</div>'


WAVE_HTML = (
    '<div class="tu-wave">' + build_bars("left")
    + '<div class="tu-mic"><span class="tu-micsvg">' + MIC_SVG + '</span>'
    + '<span class="tu-stop">' + STOP_SVG + '</span></div>'
    + build_bars("right") + '</div>'
)


def build_card_html(question=None, answer=None, mode="음성 + 텍스트", listening=False):
    """결과 카드 HTML. 질문/답변이 아직 없으면 대기 문구를 보여줌"""
    if question is None and not listening:
        return '<div class="tu-card"><div class="tu-placeholder">행복한 하루 되세요!</div></div>'

    card = '<div class="tu-card"><div class="tu-label">🎤 내 말 · 음성 인식 결과</div>'
    if question is None:
        card += '<div class="tu-wait">질문을 듣고 있어요...</div>'
    else:
        card += '<div class="tu-question">' + html.escape(question) + '</div>'
        if mode != "음성만":
            card += '<div class="tu-divider"></div><div class="tu-label">Thumbs Up의 답변</div>'
            if answer is None:
                card += '<div class="tu-wait">답변을 준비하고 있어요...</div>'
            else:
                card += '<div class="tu-answer">' + html.escape(answer).replace("\n", "<br>") + '</div>'
    card += '</div>'
    return card


def show_status(placeholder, kind, text):
    """하단 안내 배너 갱신 (kind: idle / busy / done / error)"""
    inner = '<span class="tu-txt">' + html.escape(text) + '</span>'
    if kind in ("idle", "done"):
        # 녹음 중일 때만 보이는 문구 (CSS가 자동으로 전환)
        inner += '<span class="tu-rec-txt">🔴 녹음 중이에요. 다시 누르면 끝나요</span>'
    placeholder.markdown(
        '<div class="tu-status tu-' + kind + '">' + inner + '</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------
st.session_state.setdefault("show_settings", False)
st.session_state.setdefault("pref_mode", ANSWER_MODES[0])
st.session_state.setdefault("pref_voice", "nova")
st.session_state.setdefault("audio_n", 0)
st.session_state.setdefault("memo_n", 0)

# ---------------------------------------------------------
# 사이드 메뉴 (추후 기능은 MENU_ITEMS에 한 줄씩 추가)
# (아이콘, 메뉴 이름, 사용 가능 여부)
# ---------------------------------------------------------
MENU_ITEMS = [
    ("🌤️", "날씨 비서", True),
    ("📝", "회의록 분석 (요약·업무 정리)", False),
    ("⚠️", "업무 리스크 점검", False),
    ("✉️", "이메일 작성 및 발송", False),
]

menu_html = '<div class="tu-brand">나의 질문</div>'
for icon, name, enabled in MENU_ITEMS:
    if enabled:
        menu_html += '<div class="tu-menu-item active"><div>' + icon + ' ' + name + '</div></div>'
    else:
        menu_html += (
            '<div class="tu-menu-item disabled"><div>' + icon + ' ' + name + '</div>'
            '<div class="tu-badge">준비 중</div></div>'
        )

with st.sidebar:
    st.markdown(menu_html, unsafe_allow_html=True)

# ---------------------------------------------------------
# 상단: 타이틀 + 설정 버튼
# ---------------------------------------------------------
head_left, head_menu, head_right = st.columns([7, 0.6, 1.5], gap="small")
with head_left:
    st.markdown(TITLE_HTML, unsafe_allow_html=True)
with head_menu:
    menu_icon = ":material/menu_open:" if st.session_state["show_sidebar"] else ":material/menu:"
    if st.button("", key="toggle_sidebar", icon=menu_icon, help="사이드 메뉴 열기/닫기", width="stretch"):
        st.session_state["show_sidebar"] = not st.session_state["show_sidebar"]
        st.rerun()
with head_right:
    toggle_label = "닫기 ✕" if st.session_state["show_settings"] else "⚙️ 설정"
    if st.button(toggle_label, key="toggle_settings", width="stretch"):
        st.session_state["show_settings"] = not st.session_state["show_settings"]
        st.rerun()

# ---------------------------------------------------------
# 본문: 왼쪽(결과 카드 + 녹음/업로드) / 오른쪽(비서 이미지 또는 설정)
# ---------------------------------------------------------
left, right = st.columns([3, 2], gap="large")

with left:
    card_ph = st.empty()  # 결과 카드 자리 (처리 후 아래에서 채움)

    # 큰 마이크 버튼 = 실제 녹음 버튼
    # (기본 녹음창은 투명하게 큰 버튼 위에 겹쳐 두어, 큰 버튼을 누르면 녹음이 시작됨)
    with st.container(key="recwrap"):
        st.markdown(WAVE_HTML, unsafe_allow_html=True)
        audio = st.audio_input(
            "질문 녹음",
            key="rec_" + str(st.session_state["audio_n"]),
            label_visibility="collapsed",
        )

    status_col, up_col = st.columns([1.15, 1], gap="medium")
    with status_col:
        status_ph = st.empty()
        error_ph = st.empty()
    with up_col:
        memo_file = st.file_uploader(
            "파일 업로드",
            type=["txt", "jpg", "jpeg", "png"],
            key="memo_" + str(st.session_state["memo_n"]),
        )

with right:
    if st.session_state["show_settings"]:
        with st.container(border=False, key="settings_panel"):
            st.markdown('<div class="tu-panel-title">⚙️ 설정 및 도구</div>', unsafe_allow_html=True)

            st.markdown('<div class="tu-panel-sec">답변 방식</div>', unsafe_allow_html=True)
            mode = st.radio(
                "답변 방식",
                ANSWER_MODES,
                index=ANSWER_MODES.index(st.session_state["pref_mode"]),
                label_visibility="collapsed",
            )
            st.session_state["pref_mode"] = mode

            st.markdown('<div class="tu-panel-sec">음성 설정 (TTS)</div>', unsafe_allow_html=True)
            voice_keys = list(VOICES.keys())
            voice = st.selectbox(
                "음성",
                voice_keys,
                index=voice_keys.index(st.session_state["pref_voice"]),
                format_func=lambda k: VOICES[k],
                label_visibility="collapsed",
            )
            st.session_state["pref_voice"] = voice

            st.markdown('<div class="tu-panel-sec">기타 설정</div>', unsafe_allow_html=True)
            if st.button("새 대화 시작", key="new_chat", width="stretch"):
                st.session_state["audio_n"] += 1
                st.session_state["memo_n"] += 1
                st.session_state.pop("result", None)
                st.session_state.pop("error", None)
                st.rerun()
            st.caption("설정은 현재 브라우저 세션에서 유지됩니다.")
    else:
        # 화면 오른쪽 아래에 붙여서 크게 표시 (CSS: .st-key-hero)
        with st.container(key="hero"):
            if os.path.exists(ASSISTANT_IMG):
                st.image(ASSISTANT_IMG, width="stretch")
            else:
                st.markdown(
                    '<div style="font-size:7rem; text-align:center;">🎙️</div>',
                    unsafe_allow_html=True,
                )

# ---------------------------------------------------------
# 안내 배너 초기 상태
# ---------------------------------------------------------
if st.session_state.get("error"):
    show_status(status_ph, "error", "⚠️ 처리 중 문제가 생겼어요. 다시 녹음해 주세요.")
    error_ph.error(st.session_state["error"])
elif "result" in st.session_state:
    elapsed_text = st.session_state["result"].get("elapsed", "")
    show_status(status_ph, "done", "✅ 완료 (" + elapsed_text + "초) · 다시 질문하려면 마이크 버튼을 눌러주세요")
else:
    show_status(status_ph, "idle", "마이크 버튼을 눌러 질문해주세요")

# ---------------------------------------------------------
# 질문 처리
# ---------------------------------------------------------
mode = st.session_state["pref_mode"]

if audio is not None:
    st.session_state.pop("result", None)
    st.session_state.pop("error", None)
    error_ph.empty()
    error_message = None
    question = None

    # 처리 시작 즉시 카드 유지 (질문 인식 전에는 '듣고 있어요' 표시)
    card_ph.markdown(build_card_html(listening=True), unsafe_allow_html=True)

    try:
        start = time.time()

        show_status(status_ph, "busy", "⏳ 잠시만 기다려 주세요...")
        question = speech_to_text(audio)

        # 질문이 인식되면 바로 카드에 텍스트로 표시
        card_ph.markdown(build_card_html(question=question, mode=mode), unsafe_allow_html=True)

        show_status(status_ph, "busy", "🌍 지역과 날씨를 확인하고 있어요...")
        location = extract_location(question)

        if not location["korean"]:
            # 질문에서 지역을 알아듣지 못한 경우
            answer = "지역을 알아듣지 못했어요. 어느 지역의 날씨가 궁금한지 다시 말씀해 주세요."
        else:
            geo = geocode(location)
            if geo is None:
                # 지역명은 알아들었지만 검색에서 찾지 못한 경우
                answer = location["korean"] + " 지역은 찾지 못했어요. 지역 이름을 다시 말씀해 주세요."
            else:
                weather = get_weather(geo["lat"], geo["lon"])
                air = get_air_quality(geo["lat"], geo["lon"])
                summary = build_weather_summary(geo["name"], weather, air)

                # 첨부 파일: txt는 메모로, jpg/png는 이미지로 전달
                memo_text = ""
                image = None
                if memo_file is not None:
                    if memo_file.name.lower().endswith(".txt"):
                        memo_text = memo_file.getvalue().decode("utf-8", errors="ignore")[:3000]
                    else:
                        image = prepare_image(memo_file)

                show_status(status_ph, "busy", "📝 답변을 작성하고 있어요...")
                answer = make_answer(question, summary, memo_text, image)

        mp3 = None
        if st.session_state["pref_mode"] != "텍스트만":
            show_status(status_ph, "busy", "🔊 음성을 만들고 있어요...")
            mp3 = text_to_speech(answer, st.session_state["pref_voice"])

        st.session_state["result"] = {
            "question": question,
            "answer": answer,
            "mp3": mp3,
            "played": False,
            "elapsed": str(round(time.time() - start, 1)),
        }

    except Exception as e:
        error_message = str(e)

    if error_message:
        st.session_state["error"] = error_message
        if question:
            # 질문은 인식됐지만 이후 단계에서 실패한 경우, 질문은 카드에 남김
            st.session_state["result"] = {
                "question": question,
                "answer": "답변을 만들지 못했어요. 다시 한 번 말씀해 주세요.",
                "mp3": None,
                "played": True,
                "elapsed": "0",
            }

    # 녹음창을 새것으로 바꿔서, 큰 버튼이 다시 '녹음 대기' 상태가 되게 함
    st.session_state["audio_n"] += 1
    st.rerun()

# ---------------------------------------------------------
# 결과 카드 출력 (텍스트 + 음성 동시)
# ---------------------------------------------------------
result = st.session_state.get("result")

with card_ph.container():
    if result is None:
        st.markdown(build_card_html(), unsafe_allow_html=True)
    else:
        st.markdown(
            build_card_html(question=result["question"], answer=result["answer"], mode=mode),
            unsafe_allow_html=True,
        )

        if mode != "텍스트만" and result["mp3"]:
            # 새 답변일 때만 자동 재생 (설정을 열고 닫을 때 다시 재생되지 않도록)
            st.audio(result["mp3"], format="audio/mp3", autoplay=not result["played"])
            result["played"] = True

# ---------------------------------------------------------
# 버전 표시 (새 코드가 배포됐는지 확인용)
# ---------------------------------------------------------
st.markdown(
    '<div class="tu-ver">버전 v6 · Streamlit ' + st.__version__ + '</div>',
    unsafe_allow_html=True,
)
