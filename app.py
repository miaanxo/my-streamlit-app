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
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError("JSON 파싱 실패")
        return json.loads(m.group(0))


def llm_call(client: OpenAI, system_prompt: str, messages: list[dict]) -> dict:
    resp = client.responses.create(
        model="gpt-5-mini",
        input=[{"role": "system", "content": system_prompt}, *messages],
        text={"verbosity": "low"},
    )
    return extract_json(resp.output_text)


def normalize_activities(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        a = dict(a)
        a.setdefault("id", str(uuid.uuid4()))
        a.setdefault("title", "")
        a.setdefault("description", "")
        a.setdefault("priority", "권장")
        links = a.get("links")
        if not isinstance(links, list):
            a["links"] = []
        out.append(a)
    return out


def normalize_roadmap(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        rr = dict(r)
        y = rr.get("year")
        if isinstance(y, str) and y.isdigit():
            rr["year"] = int(y)
        rr.setdefault("h1", [])
        rr.setdefault("h2", [])
        if not isinstance(rr.get("h1"), list):
            rr["h1"] = []
        if not isinstance(rr.get("h2"), list):
            rr["h2"] = []
        out.append(rr)
    return out


# ======================
# State Init
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
    st.session_state.setdefault("selected_year", None)


# ======================
# UI Helpers
# ======================


def badge(priority: str) -> str:
    meta = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["권장"])
    return (
        f"<span style='background:{meta['color']};color:white;"
        "padding:3px 10px;border-radius:999px;font-size:12px;font-weight:800'>"
        f"{meta['label']}</span>"
    )


def _priority_rank(priority: str) -> int:
    if priority == "핵심":
        return 0
    if priority == "권장":
        return 1
    if priority == "선택":
        return 2
    return 9


def _ensure_roadmap_css_once():
    if st.session_state.get("_roadmap_css_loaded"):
        return
    st.session_state["_roadmap_css_loaded"] = True
    st.markdown(
        """
        <style>
          .j-tl { position: relative; height: 54px; margin: 10px 0 14px 0; }
          .j-line { position: absolute; top: 22px; left: 0; right: 0; height: 8px; background: #e5e7eb; border-radius: 999px; }
          .j-dot { position: absolute; top: 12px; transform: translateX(-50%); text-align: center; }
          .j-dot-core { width: 14px; height: 14px; border-radius: 999px; background: #111827; border: 3px solid #f9fafb; box-shadow: 0 1px 2px rgba(0,0,0,0.15); margin: 0 auto; }
          .j-year { margin-top: 6px; font-weight: 900; font-size: 13px; color: #111827; }
          .j-year-card { padding: 14px; border: 1px solid #e5e7eb; border-radius: 16px; margin: 12px 0; background: #ffffff; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_timeline_view_only(years: list[int]):
    """보기 전용 타임라인(가로선 + 점). 클릭 동작은 Streamlit에서 불안정하니 버튼으로 대체."""
    years = [y for y in years if isinstance(y, int)]
    years = sorted(list(dict.fromkeys(years)))
    if not years:
        return

    _ensure_roadmap_css_once()

    n = len(years)
    positions = [50] if n == 1 else [int((i / (n - 1)) * 100) for i in range(n)]
    markers = "".join(
        [
            (
                f"<div class='j-dot' style='left:{p}%;'>"
                f"<div class='j-dot-core'></div><div class='j-year'>{y}</div>"
                f"</div>"
            )
            for y, p in zip(years, positions)
        ]
    )

    st.markdown(
        f"""
        <div class='j-tl'>
          <div class='j-line'></div>
          {markers}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _resolve_activity(act_map: dict, title_map: dict, key):
    if key in act_map:
        return act_map[key]
    if isinstance(key, str):
        k = key.strip()
        if k in title_map:
            return title_map[k]
    return None


def render_activities_table():
    st.subheader("필요활동")
    acts = normalize_activities(st.session_state.get("activities", []))
    if not acts:
        st.info("아직 활동이 없습니다. 채팅에서 설계/확정을 진행해 주세요.")
        return

    header = st.columns([0.7, 2.2, 4.5, 2.2, 3.2])
    header[0].markdown("**완료**")
    header[1].markdown("**제목**")
    header[2].markdown("**내용**")
    header[3].markdown("**관련 링크**")
    header[4].markdown("**메모**")
    st.markdown("---")

    st.session_state.setdefault("activity_status", {})

    for a in acts:
        aid = a.get("id") or str(uuid.uuid4())
        a["id"] = aid
        st.session_state.activity_status.setdefault(aid, {"done": False, "memo": ""})

        row = st.columns([0.7, 2.2, 4.5, 2.2, 3.2], vertical_alignment="top")

        st.session_state.activity_status[aid]["done"] = row[0].checkbox(
            label="",
            value=st.session_state.activity_status[aid]["done"],
            key=f"done_{aid}",
        )

        title = (a.get("title") or "").strip()
        priority = (a.get("priority") or "권장").strip()
        row[1].markdown(f"**{title}**<br>{badge(priority)}", unsafe_allow_html=True)

        row[2].write((a.get("description") or "").strip())

        links = a.get("links") or []
        shown = 0
        if isinstance(links, list):
            for l in links:
                if isinstance(l, str) and l.startswith("http"):
                    shown += 1
                    row[3].link_button(f"열기 {shown}", l)
                    if shown >= 3:
                        break
        if shown == 0:
            row[3].caption("—")

        st.session_state.activity_status[aid]["memo"] = row[4].text_area(
            label="",
            value=st.session_state.activity_status[aid]["memo"],
            key=f"memo_{aid}",
            height=80,
            placeholder="예) 마감/진행상황/참고 링크",
        )

        st.markdown("---")


def render_roadmap():
    st.subheader("로드맵")

    roadmap = normalize_roadmap(st.session_state.get("roadmap", []))
    if not roadmap:
        st.info("아직 로드맵이 없습니다. FINAL 단계에서 생성돼요.")
        return

    activities = normalize_activities(st.session_state.get("activities", []))
    act_map = {a["id"]: a for a in activities if isinstance(a, dict) and a.get("id")}
    title_map = {(a.get("title") or "").strip(): a for a in activities if (a.get("title") or "").strip()}

    years = [r.get("year") for r in roadmap if isinstance(r.get("year"), int)]

    # 1) 예쁜 타임라인(보기 전용)
    _render_timeline_view_only(years)

    # 2) '연도 선택' 버튼으로 점 클릭 기능을 대체(이상한 동작 방지)
    years_sorted = sorted(list(dict.fromkeys([y for y in years if isinstance(y, int)])))
    if years_sorted:
        st.caption("연도를 눌러 해당 연도 계획을 위로 띄울 수 있어요.")
        btn_cols = st.columns(min(len(years_sorted), 6))
        for i, y in enumerate(years_sorted):
            if btn_cols[i % len(btn_cols)].button(str(y), key=f"year_btn_{y}"):
                st.session_state.selected_year = y

    selected = st.session_state.get("selected_year")

    def _resolved_sorted(items):
        res = []
        for k in (items or []):
            a = _resolve_activity(act_map, title_map, k)
            if a:
                res.append(a)
        res.sort(key=lambda x: (_priority_rank((x.get("priority") or "권장").strip()), (x.get("title") or "")))
        return res

    cards = sorted([r for r in roadmap if isinstance(r.get("year"), int)], key=lambda x: x.get("year"))
    if selected in years_sorted:
        cards = sorted(cards, key=lambda x: (0 if x.get("year") == selected else 1, x.get("year")))

    for r in cards:
        year = r.get("year")
        if not isinstance(year, int):
            continue

        st.markdown("<div class='j-year-card'>", unsafe_allow_html=True)
        st.markdown(f"### {year}년")

        h1_res = _resolved_sorted(r.get("h1"))
        h2_res = _resolved_sorted(r.get("h2"))

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("#### 상반기(1~6월)")
            if not h1_res:
                st.caption("배치된 활동이 없어요.")
            else:
                for a in h1_res:
                    st.markdown(f"- {badge(a.get('priority','권장'))} {a.get('title','')}", unsafe_allow_html=True)

        with c2:
            st.markdown("#### 하반기(7~12월)")
            if not h2_res:
                st.caption("배치된 활동이 없어요.")
            else:
                for a in h2_res:
                    st.markdown(f"- {badge(a.get('priority','권장'))} {a.get('title','')}", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)


def _build_design_chat_appendix(career_options, recommended_direction, draft_activities) -> str:
    """DESIGN 단계 초안을 채팅에 안전하게 붙이기."""
    parts = []

    if isinstance(career_options, list) and career_options:
        parts.append("

---
**초안(진로 옵션)**")
        for i, opt in enumerate(career_options[:3], start=1):
            if not isinstance(opt, dict):
                continue
            title = opt.get("title", "옵션")
            fit = opt.get("fit_reason", "")
            risk = opt.get("risk", "")
            out = opt.get("outlook", "")
            parts.append(f"{i}. **{title}**
- 적합: {fit}
- 리스크: {risk}
- 전망: {out}")

    if recommended_direction:
        parts.append(f"
**현재 가장 유력한 방향(초안):** {recommended_direction}")

    if isinstance(draft_activities, list) and draft_activities:
        parts.append("
---
**초안(필요활동 TOP 6)**")
        for a in draft_activities[:6]:
            if not isinstance(a, dict):
                continue
            parts.append(f"- {badge(a.get('priority','권장'))} **{a.get('title','')}**")

    return "
".join(parts).join(parts)


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
