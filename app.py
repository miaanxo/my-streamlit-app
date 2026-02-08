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

입력으로는 이미 정리된 사용자 정보와 직전 대화가 주어진다.

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
    # session_state는 dict-like이지만, 내부에 직렬화 불가 객체가 섞이지 않도록 보수적으로 저장
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
        "roadmap_open": st.session_state.get("roadmap_open"),
    }
    DATA_PATH.write_text(json.dumps(snapshot, ensure_ascii=False))


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
        text={"verbosity": "low"},
    )
    return extract_json(resp.output_text)

# ======================
# Init
# ======================

def init_state():
    st.session_state.setdefault("stage", "DISCOVERY")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("discovery", {})
    st.session_state.setdefault("discovery_turns", 0)
    st.session_state.setdefault("career_options", [])
    st.session_state.setdefault("recommended_direction", "")
    st.session_state.setdefault("career_plan", {})
    st.session_state.setdefault("activities", [])
    st.session_state.setdefault("roadmap", [])
    st.session_state.setdefault("activity_status", {})
    st.session_state.setdefault("roadmap_open", {})  # e.g. {"2026-h1": True}

# ======================
# UI Helpers
# ======================

def badge(priority: str) -> str:
    meta = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["권장"])
    return (
        f"<span style='background:{meta['color']};color:white;"
        "padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700'>"
        f"{meta['label']}</span>"
    )


def render_activities_table():
    st.subheader("필요활동")
    acts = st.session_state.activities
    if not acts:
        st.info("아직 확정된 활동이 없습니다")
        return

    header = st.columns([0.7, 2.2, 4.5, 2.2, 3.2])
    header[0].markdown("**완료**")
    header[1].markdown("**제목**")
    header[2].markdown("**내용**")
    header[3].markdown("**관련 링크**")
    header[4].markdown("**메모**")

    st.markdown("---")

    for a in acts:
        if not isinstance(a, dict):
            continue
        aid = a.get("id") or str(uuid.uuid4())
        a["id"] = aid
        st.session_state.activity_status.setdefault(aid, {"done": False, "memo": ""})

        row = st.columns([0.7, 2.2, 4.5, 2.2, 3.2], vertical_alignment="top")

        # 체크박스
        st.session_state.activity_status[aid]["done"] = row[0].checkbox(
            label="",
            value=st.session_state.activity_status[aid]["done"],
            key=f"done_{aid}",
        )

        # 제목 + 중요도
        title = (a.get("title") or "").strip()
        priority = (a.get("priority") or "권장").strip()
        row[1].markdown(f"**{title}**<br>{badge(priority)}", unsafe_allow_html=True)

        # 내용
        row[2].write((a.get("description") or "").strip())

        # 링크
        links = a.get("links") or []
        if isinstance(links, list) and links:
            for i, l in enumerate(links[:3], start=1):
                if isinstance(l, str) and l.startswith("http"):
                    row[3].link_button(f"열기 {i}", l)
        else:
            row[3].caption("—")

        # 메모
        st.session_state.activity_status[aid]["memo"] = row[4].text_area(
            label="",
            value=st.session_state.activity_status[aid]["memo"],
            key=f"memo_{aid}",
            height=80,
            placeholder="예) 마감/진행상황/참고 링크",
        )

        st.markdown("---")


def _render_timeline_header(years: list[int]):
    """긴 가로선(타임라인) + 연도 마커를 HTML/CSS로 렌더."""
    if not years:
        return
    years = sorted(list(dict.fromkeys(years)))

    # 마커를 균등 배치
    markers = "".join(
        [
            f"""
            <div class='tl-marker'>
              <div class='tl-dot'></div>
              <div class='tl-year'>{y}</div>
            </div>
            """
            for y in years
        ]
    )

    st.markdown(
        f"""
        <style>
          .tl-wrap {{ margin: 10px 0 18px 0; }}
          .tl-line {{ height: 8px; background: #e5e7eb; border-radius: 999px; position: relative; }}
          .tl-markers {{ display: flex; justify-content: space-between; align-items: flex-start; margin-top: -18px; }}
          .tl-marker {{ display: flex; flex-direction: column; align-items: center; min-width: 40px; }}
          .tl-dot {{ width: 14px; height: 14px; border-radius: 999px; background: #111827; border: 3px solid #f9fafb; box-shadow: 0 1px 2px rgba(0,0,0,0.15); }}
          .tl-year {{ margin-top: 6px; font-weight: 800; font-size: 14px; color: #111827; }}
          .tl-sub {{ margin-top: 8px; color: #6b7280; font-size: 13px; }}
        </style>
        <div class='tl-wrap'>
          <div class='tl-line'></div>
          <div class='tl-markers'>
            {markers}
          </div>
          <div class='tl-sub'>연도 마커를 기준으로 아래에서 상반기/하반기 활동을 확인할 수 있어요.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_roadmap():
    st.subheader("로드맵")
    roadmap = st.session_state.roadmap
    if not roadmap:
        st.info("아직 로드맵이 없습니다")
        return

    # 활동 ID -> 활동
    act_map = {}
    for a in st.session_state.activities:
        if isinstance(a, dict) and a.get("id"):
            act_map[a["id"]] = a

    # 연도 리스트 추출 + 타임라인 헤더
    years = []
    for r in roadmap:
        if isinstance(r, dict) and isinstance(r.get("year"), int):
            years.append(r["year"])
    _render_timeline_header(years)

    # 연도별 섹션
    for r in sorted([x for x in roadmap if isinstance(x, dict)], key=lambda x: x.get("year", 0)):
        year = r.get("year")
        if not isinstance(year, int):
            continue

        # 카드처럼 보이게
        st.markdown(
            """
            <div style='padding:14px 14px 2px 14px; border:1px solid #e5e7eb; border-radius:16px; margin: 10px 0 14px 0; background:#ffffff;'>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(f"### {year}년")

        c1, c2 = st.columns(2)
        k1 = f"{year}-h1"
        k2 = f"{year}-h2"
        st.session_state.roadmap_open.setdefault(k1, False)
        st.session_state.roadmap_open.setdefault(k2, False)

        if c1.button("상반기(1~6월) 보기/접기", key=f"btn_{k1}"):
            st.session_state.roadmap_open[k1] = not st.session_state.roadmap_open[k1]
        if c2.button("하반기(7~12월) 보기/접기", key=f"btn_{k2}"):
            st.session_state.roadmap_open[k2] = not st.session_state.roadmap_open[k2]

        # 상반기
        if st.session_state.roadmap_open[k1]:
            st.markdown("#### 상반기")
            ids = r.get("h1") or []
            if not ids:
                st.caption("배치된 활동이 없어요.")
            else:
                for aid in ids:
                    a = act_map.get(aid)
                    if not a:
                        continue
                    st.markdown(
                        f"- {badge(a.get('priority','권장'))} <b>{a.get('title','')}</b>",
                        unsafe_allow_html=True,
                    )

        # 하반기
        if st.session_state.roadmap_open[k2]:
            st.markdown("#### 하반기")
            ids = r.get("h2") or []
            if not ids:
                st.caption("배치된 활동이 없어요.")
            else:
                for aid in ids:
                    a = act_map.get(aid)
                    if not a:
                        continue
                    st.markdown(
                        f"- {badge(a.get('priority','권장'))} <b>{a.get('title','')}</b>",
                        unsafe_allow_html=True,
                    )

        st.markdown("</div>", unsafe_allow_html=True)



def _build_design_chat_appendix(career_options, recommended_direction, draft_activities) -> str:
    parts = []

    # 옵션 요약
    if isinstance(career_options, list) and career_options:
        parts.append("\n\n---\n**초안(진로 옵션)**")
        for i, opt in enumerate(career_options[:3], start=1):
            if not isinstance(opt, dict):
                continue
            title = opt.get("title", "옵션")
            fit = opt.get("fit_reason", "")
            risk = opt.get("risk", "")
            out = opt.get("outlook", "")
            parts.append(f"{i}. **{title}**\n- 적합: {fit}\n- 리스크: {risk}\n- 전망: {out}")

    # 추천 방향
    if recommended_direction:
        parts.append(f"\n**현재 가장 유력한 방향(초안):** {recommended_direction}")

    # 활동(상위 일부만)
    if isinstance(draft_activities, list) and draft_activities:
        parts.append("\n---\n**초안(필요활동 TOP 6)**")
        for a in draft_activities[:6]:
            if not isinstance(a, dict):
                continue
            parts.append(f"- {badge(a.get('priority','권장'))} **{a.get('title','')}**",)

    # markdown에 배지 HTML이 들어가므로 unsafe_html은 렌더 단계에서 적용
    return "\n".join(parts)

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
        st.caption(f"Discovery 자동 전환: 유저 발화 {MAX_DISCOVERY_TURNS}회 이후 설계로")
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
                # DESIGN 단계에서 배지 HTML이 포함될 수 있어 unsafe 허용
                st.markdown(m["content"], unsafe_allow_html=True)

        user_input = st.chat_input("자유롭게 이야기해 주세요")

        if user_input and api_key:
            client = OpenAI(api_key=api_key)

            # 유저 메시지 기록
            st.session_state.messages.append({"role": "user", "content": user_input})

            # discovery 길이 제한을 위한 카운트
            if st.session_state.stage == "DISCOVERY":
                st.session_state.discovery_turns += 1

            # 단계별 프롬프트
            if st.session_state.stage == "DISCOVERY":
                prompt = DISCOVERY_PROMPT
            elif st.session_state.stage == "DESIGN":
                prompt = DESIGN_PROMPT
            else:
                prompt = FINAL_PROMPT

            # 모델 호출 + 스피너
            with st.chat_message("assistant"):
                with st.spinner("생각중이에요 🤔"):
                    data = llm_call(client, prompt, st.session_state.messages)

                    msg = (data.get("assistant_message") or "").strip()

                    # DESIGN 단계: 초안을 채팅에서도 바로 보이게 첨부
                    if st.session_state.stage == "DESIGN":
                        career_options = data.get("career_options", [])
                        recommended_direction = data.get("recommended_direction", "")
                        draft_activities = data.get("draft_activities", [])
                        appendix = _build_design_chat_appendix(career_options, recommended_direction, draft_activities)
                        if appendix:
                            msg = msg + appendix

                    # FINAL 단계: 생성 완료 안내를 채팅에서도 명확히
                    if st.session_state.stage == "FINAL":
                        msg = msg + "\n\n---\n✅ **필요활동**과 **로드맵**을 업데이트했어요. 위 탭에서 바로 확인할 수 있어요."

                    st.markdown(msg, unsafe_allow_html=True)

            # assistant 메시지 저장
            st.session_state.messages.append({"role": "assistant", "content": msg})

            # 단계별 상태 반영
            if st.session_state.stage == "DISCOVERY":
                st.session_state.discovery = data.get("discovery_summary", st.session_state.discovery)

                # 1) 모델이 전환 신호를 줬거나
                # 2) 유저 발화가 일정 횟수 이상이면 (길어지지 않게) 자동 전환
                if data.get("next_action") == "READY_FOR_DESIGN" or st.session_state.discovery_turns >= MAX_DISCOVERY_TURNS:
                    st.session_state.stage = "DESIGN"

            elif st.session_state.stage == "DESIGN":
                st.session_state.career_options = data.get("career_options", st.session_state.career_options)
                st.session_state.recommended_direction = data.get("recommended_direction", st.session_state.recommended_direction)
                st.session_state.activities = data.get("draft_activities", st.session_state.activities)
                # 모델이 준비 완료라고 하면 FINAL로
                if data.get("next_action") == "READY_FOR_FINAL":
                    st.session_state.stage = "FINAL"

            elif st.session_state.stage == "FINAL":
                st.session_state.career_plan = data.get("career_plan", st.session_state.career_plan)
                st.session_state.activities = data.get("activities", st.session_state.activities)
                st.session_state.roadmap = data.get("roadmap", st.session_state.roadmap)

            save_state()
            st.rerun()

        elif user_input and not api_key:
            st.warning("사이드바에 OpenAI API Key를 먼저 입력해줘!")

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
