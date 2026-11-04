
import os
import io
from datetime import date, time, datetime

import streamlit as st
from openai import OpenAI

# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(
    page_title="JARVIS | Personal AI Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container {
    max-width: 1050px;
    padding-top: 2rem;
}
.hero {
    text-align: center;
    padding: 30px 10px 20px;
}
.hero-icon {
    font-size: 65px;
    margin-bottom: 12px;
}
.hero-title {
    font-size: 29px;
    font-weight: 750;
}
.hero-subtitle {
    color: #9299a5;
    margin-top: 8px;
}
.feature-box {
    border: 1px solid rgba(140,150,160,0.25);
    border-radius: 15px;
    padding: 20px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 상태 관리
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "schedules" not in st.session_state:
    st.session_state.schedules = []

if "last_search" not in st.session_state:
    st.session_state.last_search = ""

if "last_stock" not in st.session_state:
    st.session_state.last_stock = ""


# ==========================================
# 3. OpenAI 클라이언트
# ==========================================
def get_client():
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return None

    return OpenAI(api_key=api_key)


SYSTEM_ROLE = """
당신은 JARVIS라는 개인 AI 음성 비서입니다.

역할:
1. 사용자의 질문에 친절하게 답변합니다.
2. 한국어로 자연스럽게 대답합니다.
3. 음성으로 듣기 편하도록 간결하게 설명합니다.
4. 확실하지 않은 내용은 추측하지 않습니다.
5. 실시간 검색이나 캘린더에 접근할 수 없다면
   실제로 조회하거나 등록했다고 주장하지 않습니다.
"""


# ==========================================
# 4. AI 기능
# ==========================================
def speech_to_text(client, audio_bytes):
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "recording.wav"

    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )

    return transcript.text


def ask_ai(client, question, reference_text=""):
    system_content = SYSTEM_ROLE

    if reference_text:
        system_content += (
            "\n\n참고 문서 내용:\n"
            + reference_text[:20000]
        )

    # 최근 대화 내용을 함께 전달
    history = []

    for msg in st.session_state.messages[-10:]:
        history.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": system_content},
            *history,
            {"role": "user", "content": question}
        ]
    )

    return response.output_text


def text_to_speech(client, answer, voice):
    speech_response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=answer
    )

    return speech_response.read()


def process_question(question, reference_text=""):
    if not question.strip():
        st.warning("질문을 입력하거나 녹음해주세요.")
        return

    client = get_client()

    if client is None:
        st.error("OPENAI_API_KEY가 설정되지 않았습니다.")
        return

    try:
        with st.spinner("AI가 답변을 생성하고 있습니다..."):
            answer = ask_ai(client, question, reference_text)

            audio_data = None

            if st.session_state.voice_enabled:
                audio_data = text_to_speech(
                    client,
                    answer,
                    st.session_state.voice
                )

        st.session_state.messages.append({
            "role": "user",
            "content": question
        })

        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "audio": audio_data
        })

    except Exception as e:
        st.error(f"AI 처리 중 오류: {e}")


# ==========================================
# 5. 사이드바
# ==========================================
with st.sidebar:
    st.title("🤖 JARVIS AI")
    st.caption("Personal AI Voice Assistant")
    st.divider()

    menu = st.radio(
        "메뉴",
        [
            "🎙️ 음성 비서",
            "📅 일정 관리",
            "🔎 AI 검색",
            "📈 주식 분석",
            "⚙️ 설정"
        ]
    )

    st.divider()

    st.session_state.voice_enabled = st.toggle(
        "AI 음성 답변",
        value=st.session_state.get("voice_enabled", True)
    )

    st.session_state.show_text = st.toggle(
        "답변 텍스트 표시",
        value=st.session_state.get("show_text", False)
    )

    st.session_state.voice = st.selectbox(
        "AI 목소리",
        ["alloy", "nova", "echo", "shimmer", "onyx", "fable"],
        index=["alloy", "nova", "echo", "shimmer", "onyx", "fable"].index(
            st.session_state.get("voice", "nova")
        )
    )

    st.divider()

    if get_client():
        st.success("OpenAI API 키 설정됨")
    else:
        st.warning("OpenAI API 키 미설정")

    st.caption("JARVIS v1.0 | Streamlit")


# ==========================================
# 6. 음성 비서
# ==========================================
if menu == "🎙️ 음성 비서":

    st.markdown("""
    <div class="hero">
        <div class="hero-icon">🤖</div>
        <div class="hero-title">
            안녕하세요, JARVIS입니다.
        </div>
        <div class="hero-subtitle">
            무엇을 도와드릴까요?<br>
            마이크로 질문하거나 직접 입력하세요.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    left, right = st.columns([2, 1])

    with left:
        st.subheader("🎤 음성 질문")

        audio_value = st.audio_input(
            "마이크를 눌러 말씀해주세요."
        )

        if st.button(
            "🎙️ 음성 질문 실행",
            type="primary",
            use_container_width=True
        ):
            if audio_value is None:
                st.warning("먼저 음성을 녹음해주세요.")
            else:
                client = get_client()

                if client is None:
                    st.error("OpenAI API 키가 필요합니다.")
                else:
                    try:
                        with st.spinner("음성을 인식하고 있습니다..."):
                            question = speech_to_text(
                                client,
                                audio_value.getvalue()
                            )

                        process_question(question)

                    except Exception as e:
                        st.error(f"음성 인식 오류: {e}")

    with right:
        st.subheader("📎 참고 자료")

        uploaded_file = st.file_uploader(
            "TXT 파일 업로드",
            type=["txt"]
        )

        reference_text = ""

        if uploaded_file is not None:
            reference_text = uploaded_file.getvalue().decode(
                "utf-8-sig",
                errors="replace"
            )
            st.success("참고 문서 준비 완료")

    st.divider()

    st.subheader("💬 텍스트 질문")

    question = st.chat_input(
        "JARVIS에게 질문을 입력하세요..."
    )

    if question:
        process_question(question, reference_text)

    st.divider()

    st.subheader("🔊 대화 기록")

    if not st.session_state.messages:
        st.info("아직 대화 기록이 없습니다.")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):

            if msg["role"] == "user":
                st.write(msg["content"])

            else:
                # 음성 우선 출력
                if msg.get("audio"):
                    st.audio(
                        msg["audio"],
                        format="audio/mp3",
                        autoplay=False
                    )

                # 텍스트는 옵션으로 표시
                if (
                    st.session_state.show_text
                    or not msg.get("audio")
                ):
                    st.write(msg["content"])

    if st.session_state.messages:
        if st.button("🗑️ 대화 초기화"):
            st.session_state.messages = []
            st.rerun()


# ==========================================
# 7. 일정 관리
# ==========================================
elif menu == "📅 일정 관리":

    st.title("📅 일정 관리")
    st.caption(
        "음성 일정 관리 기능을 위한 화면"
    )

    st.info(
        "현재는 화면 내 임시 일정 저장만 가능합니다. "
        "Google Calendar에는 등록되지 않습니다."
    )

    left, right = st.columns([1, 1])

    with left:
        st.subheader("➕ 일정 추가")

        with st.form("schedule_form"):
            schedule_title = st.text_input(
                "일정 제목",
                placeholder="예: 프로젝트 회의"
            )

            schedule_date = st.date_input(
                "날짜",
                value=date.today()
            )

            schedule_time = st.time_input(
                "시간",
                value=time(10, 0)
            )

            description = st.text_area(
                "상세 내용"
            )

            submitted = st.form_submit_button(
                "일정 추가",
                use_container_width=True
            )

        if submitted:
            if not schedule_title.strip():
                st.warning("일정 제목을 입력해주세요.")
            else:
                st.session_state.schedules.append({
                    "title": schedule_title,
                    "date": schedule_date,
                    "time": schedule_time,
                    "description": description
                })

                st.success("임시 일정이 추가되었습니다.")

    with right:
        st.subheader("📋 나의 일정")

        selected_date = st.date_input(
            "조회할 날짜",
            value=date.today(),
            key="lookup_date"
        )

        day_schedules = [
            item
            for item in st.session_state.schedules
            if item["date"] == selected_date
        ]

        day_schedules.sort(key=lambda x: x["time"])

        if not day_schedules:
            st.info("선택한 날짜에 등록된 임시 일정이 없습니다.")

        for item in day_schedules:
            with st.container(border=True):
                st.markdown(f"**{item['title']}**")
                st.write(
                    item["time"].strftime("%H:%M")
                )
                if item["description"]:
                    st.caption(item["description"])

    st.divider()
    st.subheader("🎙️ 음성 일정 등록")
    st.caption(
        "향후 '내일 오후 3시에 회의 등록해줘'와 같은 "
        "자연어 일정 등록 기능을 연결할 영역입니다."
    )


# ==========================================
# 8. AI 검색
# ==========================================
elif menu == "🔎 AI 검색":

    st.title("🔎 AI 웹 검색")
    st.caption("최신 정보를 검색하는 AI 비서")

    st.markdown("""
    <div class="feature-box">
        <h3>🌐 무엇이 궁금하신가요?</h3>
        인터넷의 최신 정보를 검색하고
        음성으로 설명하는 기능을 연결할 예정입니다.
    </div>
    """, unsafe_allow_html=True)

    with st.form("search_form"):
        search_query = st.text_input(
            "검색할 내용",
            placeholder="예: 오늘 AI 관련 주요 뉴스"
        )

        search_submit = st.form_submit_button(
            "🔍 검색",
            use_container_width=True
        )

    if search_submit:
        if search_query.strip():
            st.session_state.last_search = search_query
        else:
            st.warning("검색어를 입력해주세요.")

    if st.session_state.last_search:
        st.subheader("검색 요청")
        st.write(st.session_state.last_search)

        st.info(
            "아직 웹 검색 API가 연결되지 않았습니다. "
            "현재는 검색 요청 화면만 구현되어 있습니다."
        )

    st.subheader("추천 검색 주제")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.info("📰 주요 뉴스")

    with col2:
        st.info("🌤️ 날씨 정보")

    with col3:
        st.info("💻 최신 IT 기술")


# ==========================================
# 9. 주식 분석
# ==========================================
elif menu == "📈 주식 분석":

    st.title("📈 AI 주식 분석")
    st.caption(
        "국내 및 해외 주식 종목 검색과 분석"
    )

    with st.form("stock_form"):
        stock_name = st.text_input(
            "종목명 또는 종목 코드",
            placeholder="삼성전자 / AAPL / NVIDIA"
        )

        submitted = st.form_submit_button(
            "📊 종목 조회",
            use_container_width=True
        )

    if submitted:
        if stock_name.strip():
            st.session_state.last_stock = stock_name
        else:
            st.warning("종목명을 입력해주세요.")

    if st.session_state.last_stock:
        st.subheader(
            f"📌 {st.session_state.last_stock}"
        )

        st.info(
            "종목 코드 자동 식별 및 실시간 시세 API는 "
            "아직 연결되지 않았습니다."
        )

    st.divider()

    st.subheader("시장 정보")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("현재 주가", "연동 전")

    with col2:
        st.metric("전일 대비", "연동 전")

    with col3:
        st.metric("거래량", "연동 전")

    st.subheader("📉 주가 차트")
    st.info("실제 주가 데이터를 연결하면 차트가 표시됩니다.")

    st.subheader("🤖 AI 종목 분석")
    st.caption(
        "향후 종목 코드 식별, 시세 조회, "
        "뉴스 분석 및 음성 브리핑을 연결할 영역입니다."
    )


# ==========================================
# 10. 설정
# ==========================================
elif menu == "⚙️ 설정":

    st.title("⚙️ AI 비서 설정")

    st.subheader("🎙️ 음성 설정")
    st.write(
        "음성 답변 활성화 여부와 AI 목소리는 "
        "왼쪽 사이드바에서 변경할 수 있습니다."
    )

    st.divider()

    st.subheader("🤖 AI 모델")

    st.text_input(
        "대화 모델",
        value="gpt-4o-mini",
        disabled=True
    )

    st.text_input(
        "음성 인식 모델",
        value="whisper-1",
        disabled=True
    )

    st.text_input(
        "음성 합성 모델",
        value="tts-1",
        disabled=True
    )

    st.divider()

    st.subheader("🔐 연결 상태")

    if get_client():
        st.success("OpenAI API 키 설정됨")
    else:
        st.error("OpenAI API 키가 없습니다.")

    st.warning(
        "Google Calendar, 실시간 웹 검색 및 "
        "주식 시세 서비스는 미연결 상태입니다."
    )
