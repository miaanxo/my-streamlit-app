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

규칙:
- 아직 최종 결정처럼 말하지 마라.
- 로드맵 배치는 하지 마라.

출력은 반드시 JSON 한 덩어리로만 한다.
{
  "assistant_message": "설계 결과 설명",
  "career_options": [],
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
    st.session_state.setdefault("career_plan", {})
    st.session_state.setdefault("activities", [])
    st.session_state.setdefault("roadmap", [])
    st.session_state.setdefault("activity_status", {})

# ======================
# UI Helpers
# ======================

def badge(priority):
    meta = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["권장"])
    return f"<span style='background:{meta['color']};color:white;padding:3px 10px;border-radius:999px;font-size:12px'>{meta['label']}</span>"


def render_activities_table():
    st.subheader("필요활동")
    acts = st.session_state.activities
    if not acts:
        st.info("아직 확정된 활동이 없습니다")
        return

    header = st.columns([0.6, 2, 4, 2, 3])
    header[0].markdown("**완료**")
    header[1].markdown("**제목**")
    header[2].markdown("**내용**")
    header[3].markdown("**링크**")
    header[4].markdown("**메모**")

    st.markdown("---")

    for a in acts:
        aid = a.get("id") or str(uuid.uuid4())
        a["id"] = aid
        st.session_state.activity_status.setdefault(aid, {"done": False, "memo": ""})
        row = st.columns([0.6, 2, 4, 2, 3])
        row[0].checkbox("", key=f"done_{aid}")
        row[1].markdown(f"**{a['title']}**<br>{badge(a['priority'])}", unsafe_allow_html=True)
        row[2].write(a.get("description", ""))
        if a.get("links"):
            for l in a["links"]:
                row[3].link_button("열기", l)
        else:
            row[3].write("-")
        st.session_state.activity_status[aid]["memo"] = row[4].text_area("", key=f"memo_{aid}")
        st.markdown("---")


def render_roadmap():
    st.subheader("로드맵")
    roadmap = st.session_state.roadmap
    if not roadmap:
        st.info("아직 로드맵이 없습니다")
        return

    act_map = {a['id']: a for a in st.session_state.activities}

    for r in roadmap:
        st.markdown(f"### {r['year']}년")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**상반기**")
            for aid in r.get("h1", []):
                if aid in act_map:
                    a = act_map[aid]
                    st.markdown(f"- {badge(a['priority'])} {a['title']}", unsafe_allow_html=True)
        with c2:
            st.markdown("**하반기**")
            for aid in r.get("h2", []):
                if aid in act_map:
                    a = act_map[aid]
                    st.markdown(f"- {badge(a['priority'])} {a['title']}", unsafe_allow_html=True)

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

            with st.chat_message("assistant"):
                with st.spinner("생각중이에요 🤔"):
                    if st.session_state.stage == "DISCOVERY":
                        prompt = DISCOVERY_PROMPT
                    elif st.session_state.stage == "DESIGN":
                        prompt = DESIGN_PROMPT
                    else:
                        prompt = FINAL_PROMPT

                    data = llm_call(client, prompt, st.session_state.messages)

            msg = data.get("assistant_message", "")
            st.session_state.messages.append({"role": "assistant", "content": msg})

            # 단계별 처리
            if st.session_state.stage == "DISCOVERY":
                if data.get("next_action") == "READY_FOR_DESIGN":
                    st.session_state.stage = "DESIGN"

            elif st.session_state.stage == "DESIGN":
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
        render_activities_table()

    # ------------------
    # Roadmap Tab
    # ------------------
    with tab_road:
        render_roadmap()


if __name__ == "__main__":
    main()
