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
    """
    모델이 실수로 JSON 바깥 텍스트를 섞었을 때 대비.
    가장 바깥의 JSON 객체를 찾아 파싱.
    """
    text = text.strip()
    # 1) 바로 파싱 시도
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) 가장 큰 {...} 블록 찾기
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("JSON을 찾지 못했습니다.")
    return json.loads(m.group(0))


def llm_step(client: OpenAI, messages: list[dict]) -> dict:
    """
    Responses API로 JSON 한 덩어리 출력 유도.
    """
    resp = client.responses.create(
        model="gpt-5.2",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages
        ],
        text={"verbosity": "low"},
    )
    # openai-python Responses는 output_text로 텍스트 합본 제공
    data = _extract_json(resp.output_text)
    return data


def init_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []  # [{"role":"user|assistant","content":"..."}]
    if "profile" not in st.session_state:
        st.session_state.profile = {}
    if "career_plan" not in st.session_state:
        st.session_state.career_plan = {}
    if "activities" not in st.session_state:
        st.session_state.activities = []  # list[dict]
    if "roadmap" not in st.session_state:
        st.session_state.roadmap = []  # list[dict]
    if "activity_status" not in st.session_state:
        st.session_state.activity_status = {}  # id -> {"done": bool, "memo": str}
    if "roadmap_open" not in st.session_state:
        st.session_state.roadmap_open = {}  # f"{year}-h1"/"{year}-h2" -> bool


def badge_html(priority: str) -> str:
    meta = PRIORITY_BADGE.get(priority, {"label": priority, "color": "#94a3b8"})
    return f"""
    <span style="
        display:inline-block;
        padding:4px 10px;
        border-radius:999px;
        background:{meta["color"]};
        color:white;
        font-size:12px;
        font-weight:700;
        line-height:1;
    ">{meta["label"]}</span>
    """


def render_activities_table(activities: list[dict]):
    st.subheader("필요활동 / 역량")

    if not activities:
        st.info("아직 생성된 활동이 없어요. 채팅에서 진로 방향을 더 이야기하거나, 계획 생성을 요청해보세요.")
        return

    # 헤더
    header_cols = st.columns([0.6, 2.2, 4.5, 2.6, 3.2])
    header_cols[0].markdown("**완료**")
    header_cols[1].markdown("**제목**")
    header_cols[2].markdown("**내용**")
    header_cols[3].markdown("**관련 링크**")
    header_cols[4].markdown("**메모**")

    st.markdown("<hr style='margin: 6px 0 10px 0;'>", unsafe_allow_html=True)

    for a in activities:
        aid = a.get("id") or str(uuid.uuid4())
        a["id"] = aid

        if aid not in st.session_state.activity_status:
            st.session_state.activity_status[aid] = {"done": False, "memo": ""}

        status = st.session_state.activity_status[aid]

        row = st.columns([0.6, 2.2, 4.5, 2.6, 3.2], vertical_alignment="top")

        # 완료 체크
        status["done"] = row[0].checkbox(
            label="",
            value=status["done"],
            key=f"done_{aid}",
        )

        # 제목 + 중요도 배지
        title = a.get("title", "").strip()
        priority = a.get("priority", "권장")
        row[1].markdown(f"**{title}**<br>{badge_html(priority)}", unsafe_allow_html=True)

        # 내용
        desc = a.get("description", "").strip()
        row[2].write(desc)

        # 링크
        links = a.get("links") or []
        if links:
            for i, link in enumerate(links[:3], start=1):
                row[3].link_button(f"열기 {i}", link)
        else:
            row[3].caption("—")

        # 메모
        status["memo"] = row[4].text_area(
            label="",
            value=status["memo"],
            key=f"memo_{aid}",
            height=80,
            placeholder="예) 언제까지 / 참고자료 / 진행상황",
        )

        st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)


def render_roadmap(roadmap: list[dict], activities: list[dict]):
    st.subheader("연도별 로드맵")

    if not roadmap or not activities:
        st.info("로드맵을 보려면 먼저 활동/로드맵 생성이 필요해요. 채팅에서 계획 생성을 요청해보세요.")
        return

    # id -> 활동 dict
    act_map = {a["id"]: a for a in activities if a.get("id")}

    years = [r.get("year") for r in roadmap if r.get("year")]
    years = [y for y in years if isinstance(y, int)]
    years = sorted(set(years))

    # 가로 타임라인(간단 HTML)
    if years:
        year_marks = " ".join([f"<span style='margin-right:24px;font-weight:700;'>{y}</span>" for y in years])
        st.markdown(
            f"""
            <div style="padding:10px 0 6px 0;">
              <div style="height:6px;background:#e5e7eb;border-radius:999px;position:relative;"></div>
              <div style="margin-top:10px;color:#111827;">{year_marks}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 연도별 상/하반기 버튼 + 펼침
    for r in sorted(roadmap, key=lambda x: x.get("year", 0)):
        year = r.get("year")
        if not isinstance(year, int):
            continue

        st.markdown(f"### {year}년")

        c1, c2 = st.columns([1, 1])
        key_h1 = f"{year}-h1"
        key_h2 = f"{year}-h2"
        if key_h1 not in st.session_state.roadmap_open:
            st.session_state.roadmap_open[key_h1] = False
        if key_h2 not in st.session_state.roadmap_open:
            st.session_state.roadmap_open[key_h2] = False

        if c1.button("상반기(1~6월) 보기/접기", key=f"btn_{key_h1}"):
            st.session_state.roadmap_open[key_h1] = not st.session_state.roadmap_open[key_h1]
        if c2.button("하반기(7~12월) 보기/접기", key=f"btn_{key_h2}"):
            st.session_state.roadmap_open[key_h2] = not st.session_state.roadmap_open[key_h2]

        # 상반기
        if st.session_state.roadmap_open[key_h1]:
            st.markdown("#### 상반기")
            ids = r.get("h1") or []
            if not ids:
                st.caption("배치된 활동이 없어요.")
            for aid in ids:
                a = act_map.get(aid)
                if not a:
                    continue
                st.markdown(f"- {badge_html(a.get('priority','권장'))} <b>{a.get('title','')}</b>: {a.get('description','')}",
                            unsafe_allow_html=True)

        # 하반기
        if st.session_state.roadmap_open[key_h2]:
            st.markdown("#### 하반기")
            ids = r.get("h2") or []
            if not ids:
                st.caption("배치된 활동이 없어요.")
            for aid in ids:
                a = act_map.get(aid)
                if not a:
                    continue
                st.markdown(f"- {badge_html(a.get('priority','권장'))} <b>{a.get('title','')}</b>: {a.get('description','')}",
                            unsafe_allow_html=True)

        st.markdown("---")


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide")
    init_state()

    st.title(APP_TITLE)

    # Sidebar: API Key
    with st.sidebar:
        st.header("설정")
        api_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
        st.caption("키는 브라우저 세션에만 저장됩니다. (서버 저장 X)")

        model_hint = "gpt-5.2"
        st.caption(f"사용 모델: {model_hint}")

        if st.button("대화/데이터 초기화"):
            for k in [
                "messages", "profile", "career_plan", "activities",
                "roadmap", "activity_status", "roadmap_open"
            ]:
                if k in st.session_state:
                    del st.session_state[k]
            init_state()
            st.rerun()

    # Tabs
    tab_chat, tab_act, tab_road = st.tabs(["채팅", "필요활동", "로드맵"])

    # --- Chat Tab ---
    with tab_chat:
        st.markdown("대화를 통해 관심사/진로방향을 파악하고, 그 기반으로 **필요활동**과 **로드맵**을 자동 생성해요.")

        # 기존 메시지 렌더
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        user_input = st.chat_input("예) 나는 교육/데이터에 관심이 있어. 어떤 진로가 좋을까?")

        if user_input:
            if not api_key:
                st.warning("사이드바에 OpenAI API Key를 먼저 입력해줘!")
            else:
                client = OpenAI(api_key=api_key)

                # 1) 유저 메시지 추가
                st.session_state.messages.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)

                # 2) 모델 호출(한 번에: 답변 + 산출물 갱신)
                with st.chat_message("assistant"):
                    with st.spinner("진설이가 진로를 정리하는 중..."):
                        try:
                            data = llm_step(client, st.session_state.messages)

                            assistant_message = data.get("assistant_message", "").strip() or "더 자세히 알려줘!"
                            st.markdown(assistant_message)

                            # 상태 업데이트
                            st.session_state.profile = data.get("profile") or st.session_state.profile
                            st.session_state.career_plan = data.get("career_plan") or st.session_state.career_plan

                            new_acts = data.get("activities") or []
                            # activities id 보정 + 상태 유지
                            if isinstance(new_acts, list) and new_acts:
                                fixed = []
                                for a in new_acts:
                                    if not isinstance(a, dict):
                                        continue
                                    a.setdefault("id", str(uuid.uuid4()))
                                    a.setdefault("links", [])
                                    fixed.append(a)
                                st.session_state.activities = fixed

                                for a in st.session_state.activities:
                                    aid = a["id"]
                                    st.session_state.activity_status.setdefault(aid, {"done": False, "memo": ""})

                            new_roadmap = data.get("roadmap") or []
                            if isinstance(new_roadmap, list) and new_roadmap:
                                st.session_state.roadmap = new_roadmap

                            # 3) 어시스턴트 메시지 저장
                            st.session_state.messages.append({"role": "assistant", "content": assistant_message})

                        except Exception as e:
                            st.error(f"응답 처리 중 오류가 났어요: {e}")

        # 빠른 요약 카드
        if st.session_state.career_plan:
            with st.expander("현재 정리된 진로 계획(요약)"):
                cp = st.session_state.career_plan
                st.markdown(f"**방향**: {cp.get('direction','')}")
                st.markdown("**전략**")
                for s in cp.get("strategy", [])[:8]:
                    st.write(f"- {s}")
                st.markdown("**단기 목표(3~6개월)**")
                for g in cp.get("short_term_goals", [])[:6]:
                    st.write(f"- {g}")
                st.markdown("**중기 목표(1~2년)**")
                for g in cp.get("mid_term_goals", [])[:6]:
                    st.write(f"- {g}")

    # --- Activities Tab ---
    with tab_act:
        render_activities_table(st.session_state.activities)

    # --- Roadmap Tab ---
    with tab_road:
        render_roadmap(st.session_state.roadmap, st.session_state.activities)


if __name__ == "__main__":
    main()
