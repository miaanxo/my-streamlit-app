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

출력은 반드시 JSON 한 덩어리로만 한다.
{
  "assistant_message": "사용자에게 보여줄 말",
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

입력으로는 이미 정리된 사용자 정보가 주어진다.

목표:
- 사용자에게 맞는 진로 방향 초안을 설계한다.
- 여러 가능성이 있다면 비교 제안한다.

규칙:
- 아직 최종 결정처럼 말하지 마라.
- 로드맵 배치는 하지 마라.

출력은 반드시 JSON 한 덩어리로만 한다.
{
  "assistant_message": "설계 결과 설명",
  "career_options": [
    {
      "title": "진로 옵션",
      "fit_reason": "적합 이유",
      "risk": "리스크",
      "outlook": "전망"
    }
  ],
  "recommended_direction": "가장 유력한 방향",
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
# Utils
# ======================

def save_state():
    DATA_PATH.write_text(json.dumps(dict(st.session_state), ensure_ascii=False))


def load_state():
    if DATA_PATH.exists():
        data = json.loads(DATA_PATH.read_text())
        for k, v in data.items():
            st.session_state[k] = v


def extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError("JSON 파싱 실패")
        return json.loads(m.group(0))


def llm_call(client, system_prompt, messages):
    resp = client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": system_prompt},
            *messages,
        ],
    )
    return extract_json(resp.output_text)


# ======================
# Init
# ======================

def init_state():
    st.session_state.setdefault("stage", "DISCOVERY")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("discovery", {})
    st.session_state.setdefault("career_options", [])
    st.session_state.setdefault("career_plan", {})
    st.session_state.setdefault("activities", [])
    st.session_state.setdefault("roadmap", [])


# ======================
# UI
# ======================

def badge(priority):
    meta = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["권장"])
    return f"<span style='background:{meta['color']};color:white;padding:3px 10px;border-radius:999px;font-size:12px'>{meta['label']}</span>"


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
            if DATA_PATH.exists(): DATA_PATH.unlink()
            st.rerun()

    tab_chat, tab_act, tab_road = st.tabs(["채팅", "필요활동", "로드맵"])

    # ------------------
    # Chat Tab
    # ------------------
    with tab_chat:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        user_input = st.chat_input("자유롭게 이야기해 주세요")
        if user_input and api_key:
            client = OpenAI(api_key=api_key)
            st.session_state.messages.append({"role": "user", "content": user_input})

            if st.session_state.stage == "DISCOVERY":
                prompt = DISCOVERY_PROMPT
            elif st.session_state.stage == "DESIGN":
                prompt = DESIGN_PROMPT
            else:
                prompt = FINAL_PROMPT

            data = llm_call(client, prompt, st.session_state.messages)
            msg = data.get("assistant_message", "")
            st.session_state.messages.append({"role": "assistant", "content": msg})

            # 단계별 상태 처리
            if st.session_state.stage == "DISCOVERY":
                st.session_state.discovery = data.get("discovery_summary", {})
                if data.get("next_action") == "READY_FOR_DESIGN":
                    st.session_state.stage = "DESIGN"

            elif st.session_state.stage == "DESIGN":
                st.session_state.career_options = data.get("career_options", [])
                st.session_state.activities = data.get("draft_activities", [])
                if data.get("next_action") == "READY_FOR_FINAL":
                    st.session_state.stage = "FINAL"

            elif st.session_state.stage == "FINAL":
                st.session_state.career_plan = data.get("career_plan", {})
                st.session_state.activities = data.get("activities", [])
                st.session_state.roadmap = data.get("roadmap", [])

            save_state()
            st.rerun()

    # ------------------
    # Activities Tab
    # ------------------
    with tab_act:
        if not st.session_state.activities:
            st.info("아직 확정된 활동이 없습니다")
        for a in st.session_state.activities:
            st.markdown(f"### {a.get('title','')} {badge(a.get('priority','권장'))}", unsafe_allow_html=True)
            st.write(a.get("description", ""))

    # ------------------
    # Roadmap Tab
    # ------------------
    with tab_road:
        if not st.session_state.roadmap:
            st.info("아직 로드맵이 없습니다")
        for r in st.session_state.roadmap:
            st.markdown(f"## {r.get('year')}년")
            st.write("상반기:", r.get("h1", []))
            st.write("하반기:", r.get("h2", []))


if __name__ == "__main__":
    main()
