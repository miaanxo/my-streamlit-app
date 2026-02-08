# app.py
# 실행: streamlit run app.py
# 설치: pip install streamlit openai

import json
import re
import uuid
from pathlib import Path

import streamlit as st
from openai import OpenAI

APP_TITLE = "진설이 - 나만의 진로컨설턴트"
DATA_PATH = Path(".jinsul_state.json")

# Discovery가 너무 길어지지 않도록: 유저 발화 N회 이후 자동 설계 단계로 전환
MAX_DISCOVERY_TURNS = 4

# ======================
# Prompt Templates
# ======================

DISCOVERY_PROMPT = """
너는 전문 진로 컨설턴트다.
현재 단계는 [대화 단계]다.

목표:
- 사용자의 관심사, 강점, 가치관, 선호 환경, 제약 조건을 파악한다.
- 질문을 통해 정보를 수집한다.

규칙:
- 진로 계획, 활동 목록, 로드맵을 만들지 마라.
- 해결책을 제시하지 말고 질문하거나 요약만 한다.
- 한 번에 질문은 최대 3개까지만 한다.
- 사용자가 3~4번 정도 응답하면, 불확실점이 남아도 가설 기반으로 설계 단계로 넘어갈 준비를 한다.

출력은 반드시 JSON 한 덩어리로만 한다.
{
  "assistant_message": "사용자에게 보여줄 말(질문/요약)",
  "discovery_summary": {
    "interests": [],
    "strengths": [],
    "values": [],
    "constraints": [],
    "uncertain_points": []
  },
  "next_action": "ASK_MORE | READY_FOR_DESIGN"
}
"""

DESIGN_PROMPT = """
너는 전문 진로 컨설턴트다.
현재 단계는 [설계 단계]다.

목표:
- 사용자에게 맞는 진로 방향 초안을 설계한다.
- 대화 중간이라도 초안을 제시하고, 사용자의 선택/수정을 유도한다.

규칙:
- 아직 최종 결정처럼 말하지 마라.
- 로드맵 배치는 하지 마라.
- 활동은 '초안'이며, 사용자가 수정 가능하다는 톤으로 제시한다.

출력은 반드시 JSON 한 덩어리로만 한다.
{
  "assistant_message": "설계 결과 설명(초안 제시 + 확인 질문)",
  "career_options": [
    {
      "title": "진로 옵션",
      "fit_reason": "적합 이유",
      "risk": "리스크",
      "outlook": "전망"
    }
  ],
  "recommended_direction": "가장 유력한 방향(초안)",
  "draft_activities": [
    {
      "id": "string",
      "title": "활동",
      "description": "내용",
      "priority": "핵심|권장|선택"
    }
  ],
  "next_action": "REFINE | READY_FOR_FINAL"
}
"""

FINAL_PROMPT = """
너는 전문 진로 컨설턴트다.
현재 단계는 [확정 단계]다.

목표:
- 실행 가능한 진로 계획을 완성한다.

규칙:
- 활동은 중복 없이 최소 10개 이상.
- 로드맵은 연도별 상/하반기로 나눈다.
- roadmap.h1/h2에는 activities의 id를 넣는다.

출력은 반드시 JSON 한 덩어리로만 한다.
{
  "assistant_message": "최종 요약 메시지",
  "career_plan": {
    "direction": "진로 방향",
    "strategy": [],
    "short_term_goals": [],
    "mid_term_goals": []
  },
  "activities": [
    {
      "id": "string",
      "title": "활동",
      "description": "내용",
      "priority": "핵심|권장|선택",
      "links": []
    }
  ],
  "roadmap": [
    {
      "year": 2026,
      "h1": [],
      "h2": []
    }
  ]
}
"""

PRIORITY_BADGE = {
    "핵심": {"label": "핵심", "color": "#ef4444"},
    "권장": {"label": "추천", "color": "#f59e0b"},
    "선택": {"label": "플러스", "color": "#22c55e"},
}

# ======================
# Persistence
# ======================


def save_state():
    snapshot = {
        "stage": st.session_state.get("stage"),
        "messages": st.session_state.get("messages"),
        "discovery": st.session_state.get("discovery"),
        "discovery_turns": st.session_state.get("discovery_turns"),
        "career_options": st.session_state.get("career_options"),
        "recommended_direction": st.session_state.get("recommended_direction"),
        "career_plan": st.session_state.get("career_plan"),
        "activities": st.session_state.get("activities"),
        "roadmap": st.session_state.get("roadmap"),
        "activity_status": st.session_state.get("activity_status"),
        "selected_year": st.session_state.get("selected_year"),
    }
    DATA_PATH.write_text(json.dumps(snapshot, ensure_ascii=False))


def load_state():
    if DATA_PATH.exists():
        data = json.loads(DATA_PATH.read_text())
        for k, v in data.items():
            st.session_state[k] = v


# ======================
# LLM Utils
# ======================


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
            return ""

.join(parts)


# ======================
# Main
# ======================


def main():
    st.set_page_config(APP_TITLE, "🧭", layout="wide")
    load_state()
    init_state()

    st.title(APP_TITLE)

    with st.sidebar:
        api_key = st.text_input("OpenAI API Key", type="password")
        st.markdown(f"**현재 단계:** {st.session_state.stage}")
        if st.button("전체 초기화"):
            st.session_state.clear()
            if DATA_PATH.exists():
                DATA_PATH.unlink()
            st.rerun()

    tab_chat, tab_act, tab_road = st.tabs(["채팅", "필요활동", "로드맵"])

    # ------------------
    # Chat Tab
    # ------------------
    with tab_chat:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"], unsafe_allow_html=True)

        user_input = st.chat_input("자유롭게 이야기해 주세요")

        if user_input and not api_key:
            st.warning("사이드바에 OpenAI API Key를 먼저 입력해줘!")

        if user_input and api_key:
            client = OpenAI(api_key=api_key)

            st.session_state.messages.append({"role": "user", "content": user_input})

            if st.session_state.stage == "DISCOVERY":
                st.session_state.discovery_turns += 1

            if st.session_state.stage == "DISCOVERY":
                prompt = DISCOVERY_PROMPT
            elif st.session_state.stage == "DESIGN":
                prompt = DESIGN_PROMPT
            else:
                prompt = FINAL_PROMPT

            with st.chat_message("assistant"):
                with st.spinner("생각중이에요..."):
                    data = llm_call(client, prompt, st.session_state.messages)

                    msg = (data.get("assistant_message") or "").strip()

                    if st.session_state.stage == "DESIGN":
                        career_options = data.get("career_options", [])
                        recommended_direction = data.get("recommended_direction", "")
                        draft_activities = normalize_activities(data.get("draft_activities", []))
                        appendix = _build_design_chat_appendix(career_options, recommended_direction, draft_activities)
                        if appendix:
                            msg += appendix

                    if st.session_state.stage == "FINAL":
                        msg += "\n\n---\n[완료] 필요활동과 로드맵을 업데이트했어요. 위 탭에서 확인할 수 있어요."

                    st.markdown(msg, unsafe_allow_html=True)

            st.session_state.messages.append({"role": "assistant", "content": msg})

            # 단계별 상태 반영
            if st.session_state.stage == "DISCOVERY":
                st.session_state.discovery = data.get("discovery_summary", st.session_state.discovery)
                if data.get("next_action") == "READY_FOR_DESIGN" or st.session_state.discovery_turns >= MAX_DISCOVERY_TURNS:
                    st.session_state.stage = "DESIGN"

            elif st.session_state.stage == "DESIGN":
                st.session_state.career_options = data.get("career_options", st.session_state.career_options)
                st.session_state.recommended_direction = data.get("recommended_direction", st.session_state.recommended_direction)
                st.session_state.activities = normalize_activities(data.get("draft_activities", st.session_state.activities))

                confirm_re = r"(확정|최종|결정|이대로|진행|좋아요|좋아|오케이|OK|go)"
                user_confirmed = bool(re.search(confirm_re, user_input, flags=re.IGNORECASE))
                model_ready = data.get("next_action") == "READY_FOR_FINAL"
                enough_draft = bool(st.session_state.recommended_direction) and len(st.session_state.activities) >= 6

                if model_ready or user_confirmed or enough_draft:
                    st.session_state.stage = "FINAL"
                    # FINAL을 즉시 생성(안전한 단일 문자열만 사용)
                    try:
                        final_data = llm_call(client, FINAL_PROMPT, st.session_state.messages)
                        final_msg = (final_data.get("assistant_message") or "").strip()
                        final_msg += "\n\n---\n[완료] 필요활동과 로드맵을 업데이트했어요. 위 탭에서 확인할 수 있어요."

                        st.session_state.messages.append({"role": "assistant", "content": final_msg})
                        st.session_state.career_plan = final_data.get("career_plan", st.session_state.career_plan)
                        st.session_state.activities = normalize_activities(final_data.get("activities", st.session_state.activities))
                        st.session_state.roadmap = normalize_roadmap(final_data.get("roadmap", st.session_state.roadmap))
                    except Exception:
                        pass

            elif st.session_state.stage == "FINAL":
                st.session_state.career_plan = data.get("career_plan", st.session_state.career_plan)
                st.session_state.activities = normalize_activities(data.get("activities", st.session_state.activities))
                st.session_state.roadmap = normalize_roadmap(data.get("roadmap", st.session_state.roadmap))

            save_state()
            st.rerun()

    with tab_act:
        render_activities_table()

    with tab_road:
        render_roadmap()


if __name__ == "__main__":
    main()
