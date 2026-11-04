
import os
import io
import html
import hashlib

import streamlit as st
from openai import OpenAI
from streamlit_mic_recorder import mic_recorder
from identity_settings_addon import show_identity_settings_dialog


# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(
    page_title="ThumbsUp AI",
    page_icon="👍🏻",
    layout="wide"
)


# ==========================================
# 2. CSS 디자인
# ==========================================
st.markdown("""
<style>
.block-container {
    max-width: 1000px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

header[data-testid="stHeader"] {
    background: transparent;
}

.voice-title {
    text-align: center;
    font-size: 32px;
    font-weight: 750;
    margin-top: 35px;
}

.voice-subtitle {
    text-align: center;
    color: #888;
    margin-bottom: 24px;
}

.mic-caption {
    text-align: center;
    color: #858b97;
    margin: 10px 0 26px;
}

.answer-box {
    background: #f7f8fc;
    border: 1px solid #e9ecf3;
    border-radius: 18px;
    padding: 20px 24px;
    line-height: 1.75;
    color: #303744;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.answer-collapsed {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
}
</style>
""", unsafe_allow_html=True)


# ==========================================
# 3. 세션 상태 초기화
# ==========================================
defaults = {
    "answer": "",
    "transcript": "",
    "answer_audio": None,
    "answer_expanded": False,
    "history": [],
    "last_processed_audio": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ==========================================
# 4. OpenAI 클라이언트
# ==========================================
def get_client():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        try:
            api_key = st.secrets.get("OPENAI_API_KEY")
        except Exception:
            api_key = None

    if not api_key:
        return None

    return OpenAI(api_key=api_key)


# ==========================================
# 5. AI 시스템 역할
# ==========================================
SYSTEM_PROMPT = """
당신은 ThumpsUp AI라는 한국어 음성 비서입니다.

역할:
1. 사용자의 음성 명령을 이해합니다.
2. 질문에 친절하고 정확하게 답변합니다.
3. 음성으로 듣기 편하도록 간결하게 설명합니다.
4. 첨부된 텍스트 파일을 참고할 수 있습니다.
5. 확실하지 않은 정보는 추측하지 않습니다.

주의:
웹 검색, 실시간 주식 조회, Google Calendar 등록 및
조회 기능은 아직 연결되지 않았습니다.

실제로 실행하지 않은 작업을 완료했다고 말하지 마세요.
"""


# ==========================================
# 6. 음성 처리 함수
# ==========================================
def process_audio(audio_bytes, reference_text):

    client = get_client()

    if client is None:
        st.error("OPENAI_API_KEY가 설정되지 않았습니다.")
        return

    try:
        # ----------------------------------
        # STT: 음성 -> 텍스트
        # ----------------------------------
        with st.spinner("음성을 인식하고 있습니다..."):

            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "recording.wav"

            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

            question = result.text.strip()

        if not question:
            st.warning("음성이 인식되지 않았습니다.")
            return

        # ----------------------------------
        # AI 대화 메시지 구성
        # ----------------------------------
        conversation = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ]

        if reference_text:
            conversation.append({
                "role": "system",
                "content": (
                    "참고 파일 내용:\n"
                    + reference_text[:15000]
                )
            })

        # 이전 대화 유지
        conversation.extend(
            st.session_state.history[-8:]
        )

        conversation.append({
            "role": "user",
            "content": question
        })

        # ----------------------------------
        # LLM 답변 생성
        # ----------------------------------
        with st.spinner("ThumpsUp AI가 답변 중입니다..."):

            response = client.responses.create(
                model="gpt-4o-mini",
                input=conversation
            )

            answer = response.output_text.strip()

        # ----------------------------------
        # TTS: 텍스트 -> 음성
        # ----------------------------------
        answer_audio = None

        try:
            with st.spinner("음성 답변을 생성하고 있습니다..."):

                speech = client.audio.speech.create(
                    model="tts-1",
                    voice="nova",
                    input=answer[:4000]
                )

                answer_audio = speech.read()

        except Exception as e:
            st.warning(f"음성 합성 오류: {e}")

        # ----------------------------------
        # 결과 저장
        # ----------------------------------
        st.session_state.transcript = question
        st.session_state.answer = answer
        st.session_state.answer_audio = answer_audio
        st.session_state.answer_expanded = False

        st.session_state.history.extend([
            {
                "role": "user",
                "content": question
            },
            {
                "role": "assistant",
                "content": answer
            }
        ])

    except Exception as e:
        st.error(f"AI 처리 중 오류: {e}")


# ==========================================
# 7. 상단 헤더 + 설정 버튼
# ==========================================
brand_col, settings_col = st.columns(
    [12, 1],
    vertical_alignment="center"
)

with brand_col:
    st.markdown("### 👍🏻 ThumpsUp AI")

with settings_col:
    if st.button(
        "⚙️",
        key="settings_button",
        help="설정"
    ):
        show_identity_settings_dialog()


# ==========================================
# 8. 중앙 안내 문구
# ==========================================
st.markdown("""
<div class="voice-title">
    무엇을 도와드릴까요?
</div>

<div class="voice-subtitle">
    음성으로 말씀하시면 ThumpsUp AI가 답변합니다.
</div>
""", unsafe_allow_html=True)


# ==========================================
# 9. TXT 파일 업로드
# ==========================================
with st.expander("📎 참고 TXT 파일 첨부 (선택)"):

    uploaded_file = st.file_uploader(
        "텍스트 파일",
        type=["txt"],
        key="txt_file"
    )

    if uploaded_file is not None:
        st.success(
            f"{uploaded_file.name} 파일이 준비되었습니다."
        )

reference_text = ""

if uploaded_file is not None:
    reference_text = uploaded_file.getvalue().decode(
        "utf-8-sig",
        errors="replace"
    )


# ==========================================
# 10. 중앙 음성 녹음 버튼
# ==========================================
left, mic_col, right = st.columns([3, 2, 3])

with mic_col:

    audio = mic_recorder(
        start_prompt="🎙️ 녹음 시작",
        stop_prompt="⏹️ 녹음 종료",
        just_once=False,
        use_container_width=True,
        key="voice_recorder"
    )

st.markdown("""
<div class="mic-caption">
    마이크를 눌러 녹음을 시작하고,
    다시 눌러 종료하세요.
</div>
""", unsafe_allow_html=True)


# ==========================================
# 11. 음성 녹음 자동 처리
# ==========================================
if audio and audio.get("bytes"):

    audio_bytes = audio["bytes"]

    # 동일한 녹음을 반복 처리하지 않도록 방지
    audio_hash = hashlib.sha256(
        audio_bytes
    ).hexdigest()

    if audio_hash != st.session_state.last_processed_audio:

        st.session_state.last_processed_audio = audio_hash

        process_audio(
            audio_bytes,
            reference_text
        )


# ==========================================
# 12. AI 답변 표시
# ==========================================
st.subheader("👍🏻 AI 답변")

answer = st.session_state.answer

if answer:

    # HTML 특수문자 변환
    safe_answer = html.escape(answer)

    # 펼침 상태
    if st.session_state.answer_expanded:
        collapsed_class = ""
    else:
        collapsed_class = "answer-collapsed"

    # 답변 출력
    st.markdown(
        f"""
        <div class="answer-box">
            <div class="{collapsed_class}">
                {safe_answer}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 긴 답변에만 더보기 표시
    # 글자 수 기반의 근사 판정
    is_long = (
        len(answer) > 85
        or answer.count("\n") >= 2
    )

    if is_long:

        if st.session_state.answer_expanded:
            button_text = "접기 ▲"
        else:
            button_text = "더보기 ▼"

        if st.button(
            button_text,
            key="toggle_answer"
        ):

            st.session_state.answer_expanded = (
                not st.session_state.answer_expanded
            )

            st.rerun()

    # AI 음성 답변 재생
    if st.session_state.answer_audio:

        st.audio(
            st.session_state.answer_audio,
            format="audio/mp3"
        )

else:
    st.info(
        "음성으로 질문하면 AI 답변이 여기에 표시됩니다."
    )


# ==========================================
# 13. 인식된 음성 확인
# ==========================================
if st.session_state.transcript:

    with st.expander("인식된 음성 확인"):

        st.write(
            st.session_state.transcript
        )


# ==========================================
# 14. 최근 대화 기록
# ==========================================
with st.expander("최근 대화 기록"):

    if not st.session_state.history:

        st.caption("아직 대화 기록이 없습니다.")

    else:

        for message in st.session_state.history[-10:]:

            if message["role"] == "user":
                who = "나"
            else:
                who = "ThumpsUp AI"

            st.markdown(f"**{who}**")
            st.write(message["content"])

        if st.button("대화 초기화"):

            reset_values = {
                "answer": "",
                "transcript": "",
                "answer_audio": None,
                "answer_expanded": False,
                "history": [],
                "last_processed_audio": None
            }

            for key, value in reset_values.items():
                st.session_state[key] = value

            st.rerun()
