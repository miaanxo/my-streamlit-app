# app.py
# 실행: streamlit run app.py
# 설치: pip install streamlit openai

import json
import re
import uuid
from datetime import datetime

import streamlit as st
from openai import OpenAI

APP_TITLE = "진설이 - 나만의 진로컨설턴트"

SYSTEM_PROMPT = """
너는 한국어로 대화하는 '진로 컨설턴트 AI'다.
목표:
1) 사용자와의 대화를 통해 관심사/강점/가치/선호환경/제약조건을 파악한다.
2) 그에 맞는 '진로 계획(커리어 방향 + 전략 + 단기/중기 목표)'을 제시한다.
3) 진로 계획을 바탕으로 사용자에게 필요한 '활동/역량'을 중요도(핵심/권장/선택)로 정리한다.
4) 활동들을 연도별 상반기/하반기에 배치한 로드맵을 만든다.

중요:
- 너의 응답은 반드시 JSON "한 덩어리"만 출력한다. 설명 텍스트/마크다운/코드블록 금지.
- JSON 스키마(반드시 준수):
{
  "assistant_message": "채팅에 보여줄 자연어 답변(한국어)",
  "profile": {
    "interests": ["..."],
    "strengths": ["..."],
    "values": ["..."],
    "preferred_work": ["..."],
    "constraints": ["..."],
    "target_roles": ["..."],
    "target_industries": ["..."],
    "notes": "요약 메모"
  },
  "career_plan": {
    "direction": "진로 방향 한 문장",
    "strategy": ["전략 bullet", "..."],
    "short_term_goals": ["3~6개월 목표", "..."],
    "mid_term_goals": ["1~2년 목표", "..."],
    "assumptions": ["가정/불확실성", "..."]
  },
  "activities": [
    {
      "id": "string(고유)",
      "title": "활동/역량 제목",
      "description": "구체적 내용(무엇을/왜/어떻게)",
      "priority": "핵심|권장|선택",
      "links": ["https://...","..."]
    }
  ],
  "roadmap": [
    {
      "year": 2026,
      "h1": ["activities.id", "..."],   // 상반기(1~6월)
      "h2": ["activities.id", "..."]    // 하반기(7~12월)
    }
  ]
}

대화 규칙:
- 먼저 질문을 통해 정보를 수집하되, 사용자가 요청하면 언제든 계획/활동/로드맵을 생성한다.
- 활동은 최소 8개 이상(가능하면 12~20개), 중복 없이.
- 링크는 확실할 때만 넣고, 없으면 빈 배열 [].
- 로드맵은 최소 2개 연도(예: 올해~내년) 이상 제시. 사용자가 시간범위를 말하면 그에 맞춰 조정.
"""

PRIORITY_BADGE = {
    "핵심": {"label": "핵심", "color": "#ef4444"},   # red
    "권장": {"label": "추천", "color": "#f59e0b"},   # amber
    "선택": {"label": "플러스", "color": "#22c55e"}, # green
}


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("JSON을 찾지 못했습니다.")
    return json.loads(m.group(0))


def llm_step(client: OpenAI, messages: list[dict]) -> dict:
    resp = client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages
        ],
        text={"verbosity": "low"},
    )
    data = _extract_json(resp.output_text)
    return data


def init_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "profile" not in st.session_state:
        st.session_state.profile = {}
    if "career_plan" not in st.session_state:
        st.session_state.career_plan = {}
    if "activities" not in st.session_state:
        st.session_state.activities = []
    if "roadmap" not in st.session_state:
        st.session_state.roadmap = []
    if "activity_status" not in st.session_state:
        st.session_state.activity_status = {}
    if "roadmap_open" not in st.session_state:
        st.session_state.roadmap_open = {}


def badge_html(priority: str) -> str:
    meta = PRIORITY_BADGE.get(priority, {"label": priority, "color": "#94a3b8"})
    return f"""
    <span style="
        display:inline-block;
        padding:4px 10px;
        border-radius:999px;
        background:{meta['color']};
        color:white;
        font-size:12px;
        font-weight:700;
        line-height:1;
    ">{meta['label']}</span>
    """


def render_activities_table(activities: list[dict]):
    st.subheader("필요활동 / 역량")
    if not activities:
        st.info("아직 생성된 활동이 없어요. 채팅에서 진로 방향을 더 이야기해보세요.")
        return

    header_cols = st.columns([0.6, 2.2, 4.5, 2.6, 3.2])
    header_cols[0].markdown("**완료**")
    header_cols[1].markdown("**제목**")
    header_cols[2].markdown("**내용**")
    header_cols[3].markdown("**관련 링크**")
    header_cols[4].markdown("**메모**")

    st.markdown("<hr>", unsafe_allow_html=True)

    for a in activities:
        aid = a.get("id") or str(uuid.uuid4())
        a["id"] = aid
        st.session_state.activity_status.setdefault(aid, {"done": False, "memo": ""})
        status = st.session_state.activity_status[aid]

        row = st.columns([0.6, 2.2, 4.5, 2.6, 3.2], vertical_alignment="top")
        status["done"] = row[0].checkbox("", value=status["done"], key=f"done_{aid}")
        row[1].markdown(f"**{a.get('title','')}**<br>{badge_html(a.get('priority','권장'))}", unsafe_allow_html=True)
        row[2].write(a.get("description", ""))

        links = a.get("links") or []
        if links:
            for i, link in enumerate(links[:3], start=1):
                row[3].link_button(f"열기 {i}", link)
        else:
            row[3].caption("—")

        status["memo"] = row[4].text_area("", value=status["memo"], key=f"memo_{aid}", height=80)
        st.markdown("<hr>", unsafe_allow_html=True)


def render_roadmap(roadmap: list[dict], activities: list[dict]):
    st.subheader("연도별 로드맵")
    if not roadmap or not activities:
        st.info("로드맵을 보려면 먼저 계획 생성이 필요해요.")
        return

    act_map = {a["id"]: a for a in activities if a.get("id")}

    for r in sorted(roadmap, key=lambda x: x.get("year", 0)):
        year = r.get("year")
        if not isinstance(year, int):
            continue
        st.markdown(f"### {year}년")

        for half, label in [("h1", "상반기"), ("h2", "하반기")]:
            key = f"{year}-{half}"
            st.session_state.roadmap_open.setdefault(key, False)
            if st.button(f"{label} 보기/접기", key=f"btn_{key}"):
                st.session_state.roadmap_open[key] = not st.session_state.roadmap_open[key]
            if st.session_state.roadmap_open[key]:
                for aid in r.get(half, []):
                    a = act_map.get(aid)
                    if a:
                        st.markdown(f"- {badge_html(a.get('priority','권장'))} <b>{a.get('title')}</b>", unsafe_allow_html=True)
        st.markdown("---")


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide")
    init_state()
    st.title(APP_TITLE)

    with st.sidebar:
        st.header("설정")
        api_key = st.text_input("OpenAI API Key", type="password")
        st.caption("키는 브라우저 세션에만 저장됩니다.")
        if st.button("대화/데이터 초기화"):
            st.session_state.clear()
            init_state()
            st.rerun()

    tab_chat, tab_act, tab_road = st.tabs(["채팅", "필요활동", "로드맵"])

    with tab_chat:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        user_input = st.chat_input("예) 나는 교육/데이터에 관심이 있어")
        if user_input:
            if not api_key:
                st.warning("API Key를 입력해주세요")
            else:
                client = OpenAI(api_key=api_key)
                st.session_state.messages.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)
                with st.chat_message("assistant"):
                    with st.spinner("진설이가 정리 중..."):
                        data = llm_step(client, st.session_state.messages)
                        msg = data.get("assistant_message", "")
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.session_state.profile = data.get("profile", {})
                        st.session_state.career_plan = data.get("career_plan", {})
                        st.session_state.activities = data.get("activities", [])
                        st.session_state.roadmap = data.get("roadmap", [])

    with tab_act:
        render_activities_table(st.session_state.activities)

    with tab_road:
        render_roadmap(st.session_state.roadmap, st.session_state.activities)


if __name__ == "__main__":
    main()
