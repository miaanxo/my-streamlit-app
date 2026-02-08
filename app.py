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
        "roadmap_open": st.session_state.get("roadmap_open"),
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


def normalize_activities(raw):
    """activities/draft_activities를 UI가 깨지지 않게 정규화"""
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
        # FINAL에서만 links가 오지만, UI 일관성 위해 항상 보유
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
        # year가 문자열로 오면 int 변환 시도
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
    st.session_state.setdefault("roadmap_open", {})

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
    # 핵심(0) -> 권장(1) -> 선택(2)
    if priority == "핵심":
        return 0
    if priority == "권장":
        return 1
    if priority == "선택":
        return 2
    return 9


def _chip_html(title: str, priority: str) -> str:
    meta = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["권장"])
    # 칩: 연한 배경 + 컬러 도트 + 제목
    return (
        "<span class='j-chip'>"
        f"<span class='j-chip-dot' style='background:{meta['color']};'></span>"
        f"<span class='j-chip-text'>{title}</span>"
        "</span>"
    )


def _ensure_roadmap_css_once():
    """로드맵/타임라인/칩 UI에 필요한 CSS를 1회만 로드."""
    if st.session_state.get("_roadmap_css_loaded"):
        return
    st.session_state["_roadmap_css_loaded"] = True

    st.markdown(
        """
        <style>
          /* Timeline */
          .j-tl { position: relative; height: 54px; margin: 10px 0 18px 0; }
          .j-line { position: absolute; top: 22px; left: 0; right: 0; height: 8px; background: #e5e7eb; border-radius: 999px; }
          .j-dot { position: absolute; top: 12px; transform: translateX(-50%); text-align: center; }
          .j-dot-core { width: 14px; height: 14px; border-radius: 999px; background: #111827; border: 3px solid #f9fafb; box-shadow: 0 1px 2px rgba(0,0,0,0.15); margin: 0 auto; }
          .j-year { margin-top: 6px; font-weight: 900; font-size: 13px; color: #111827; }
          .j-sub { margin-top: -10px; color: #6b7280; font-size: 13px; }
          .j-dot-link { text-decoration: none; }
          .j-dot-link:hover .j-dot-core { transform: scale(1.06); }

          /* Cards */
          .j-year-card { padding: 14px 14px 10px 14px; border: 1px solid #e5e7eb; border-radius: 16px; margin: 12px 0; background: #ffffff; }

          /* Chips */
          .j-chip-wrap { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 2px 0; }
          .j-chip { display: inline-flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 999px; background: #f3f4f6; border: 1px solid #e5e7eb; }
          .j-chip-dot { width: 10px; height: 10px; border-radius: 999px; display: inline-block; }
          .j-chip-text { font-size: 13px; font-weight: 700; color: #111827; }
          .j-top-title { font-size: 12px; font-weight: 900; color: #111827; margin: 6px 0 6px 0; }
          .j-chip-top { background: #fff7ed; border: 1px solid #fed7aa; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_timeline_header(years: list[int]):
    """긴 가로선(타임라인) + 연도 점. 연도 점 클릭 시 해당 연도 카드로 스크롤."""
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
                f"<a class='j-dot-link' href='#year-{y}'>"
                f"<div class='j-dot' style='left:{p}%;'>"
                f"<div class='j-dot-core'></div><div class='j-year'>{y}</div>"
                f"</div></a>"
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
        <div class='j-sub'>연도 점을 누르면 해당 연도로 이동해요. 아래에서 상/하반기 계획을 확인할 수 있어요.</div>
        """,
        unsafe_allow_html=True,
    )


def _resolve_activity(act_map: dict, title_map: dict, key):
    """로드맵 항목이 id가 아닐 수도 있어(모델 실수). id 또는 title로 복구."""
    if key in act_map:
        return act_map[key]
    if isinstance(key, str):
        k = key.strip()
        if k in title_map:
            return title_map[k]
    return None


def _chip_html(title: str, priority: str) -> str:
    meta = PRIORITY_BADGE.get(priority, PRIORITY_BADGE["권장"])
    safe_title = (title or "").strip()
    return (
        "<span class='j-chip'>"
        f"<span class='j-chip-dot' style='background:{meta['color']};'></span>"
        f"<span class='j-chip-text'>{safe_title}</span>"
        "</span>"
    )


def render_roadmap():
    """보기 전용 로드맵: 타임라인 + 연도 카드 + 상/하반기 2열 보드 + Top3 강조 + 칩 + 자동정렬."""
    st.subheader("로드맵")

    roadmap = normalize_roadmap(st.session_state.roadmap)
    if not roadmap:
        st.info("아직 로드맵이 없습니다. FINAL 단계에서 생성돼요.")
        return

    _ensure_roadmap_css_once()

    activities = normalize_activities(st.session_state.activities)

    # 활동 맵 (id/title)
    act_map = {a["id"]: a for a in activities if isinstance(a, dict) and a.get("id")}
    title_map = {}
    for a in activities:
        if not isinstance(a, dict):
            continue
        t = (a.get("title") or "").strip()
        if t:
            title_map[t] = a

    # 타임라인
    years = [r.get("year") for r in roadmap if isinstance(r, dict) and isinstance(r.get("year"), int)]
    _render_timeline_header(years)

    def _resolve_many(items):
        resolved = []
        for key in (items or []):
            a = _resolve_activity(act_map, title_map, key)
            if a:
                resolved.append(a)
        # 우선순위(핵심→권장→선택) + 제목
        resolved.sort(
            key=lambda x: (
                _priority_rank((x.get("priority") or "권장").strip()),
                (x.get("title") or ""),
            )
        )
        return resolved

    def _chips(resolved, top=False):
        if not resolved:
            return ""
        chips = []
        for a in resolved:
            title = (a.get("title") or "").strip()
            priority = (a.get("priority") or "권장").strip()
            chip = _chip_html(title, priority)
            if top:
                chip = chip.replace("class='j-chip'", "class='j-chip j-chip-top'")
            chips.append(chip)
        return "".join(chips)

    # 연도 카드 렌더
    for r in sorted(roadmap, key=lambda x: x.get("year", 0)):
        year = r.get("year")
        if not isinstance(year, int):
            continue

        # 앵커(타임라인 클릭 스크롤)
        st.markdown(f"<div id='year-{year}'></div>", unsafe_allow_html=True)

        st.markdown("<div class='j-year-card'>", unsafe_allow_html=True)
        st.markdown(f"### {year}년")

        h1_resolved = _resolve_many(r.get("h1"))
        h2_resolved = _resolve_many(r.get("h2"))

        col1, col2 = st.columns(2)

        def _render_half(col, label, resolved):
            with col:
                st.markdown(f"#### {label}")
                if not resolved:
                    st.caption("배치된 활동이 없어요.")
                    return

                # Top 3 (핵심 우선, 부족하면 전체에서 보충)
                top = [a for a in resolved if (a.get("priority") or "").strip() == "핵심"]
                if len(top) < 3:
                    for a in resolved:
                        if a not in top:
                            top.append(a)
                        if len(top) >= 3:
                            break
                top = top[:3]

                st.markdown("<div class='j-top-title'>이번 반기 Top 3</div>", unsafe_allow_html=True)
                for a in top:
                    st.markdown(f"- {badge(a.get('priority','권장'))} **{a.get('title','')}**", unsafe_allow_html=True)

                st.markdown("<div class='j-top-title'>전체 활동</div>", unsafe_allow_html=True)
                for a in resolved:
                    st.markdown(f"- {badge(a.get('priority','권장'))} {a.get('title','')}", unsafe_allow_html=True)


        _render_half(col1, "상반기(1~6월)", h1_resolved)
        _render_half(col2, "하반기(7~12월)", h2_resolved)

        st.markdown("</div>", unsafe_allow_html=True)



def _build_design_chat_appendix(career_options, recommended_direction, draft_activities) -> str:
    parts = []

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

    if recommended_direction:
        parts.append(f"\n**현재 가장 유력한 방향(초안):** {recommended_direction}")

    if isinstance(draft_activities, list) and draft_activities:
        parts.append("\n---\n**초안(필요활동 TOP 6)**")
        for a in draft_activities[:6]:
            if not isinstance(a, dict):
                continue
            parts.append(f"- {badge(a.get('priority','권장'))} **{a.get('title','')}**")

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
                    try:
                        data = llm_call(client, prompt, st.session_state.messages)
                    except Exception as e:
                        st.error(f"모델 응답 처리 오류: {e}")
                        return

                    msg = (data.get("assistant_message") or "").strip()

                    # DESIGN 단계: 초안을 채팅에서도 바로 보이게 첨부
                    if st.session_state.stage == "DESIGN":
                        career_options = data.get("career_options", [])
                        recommended_direction = data.get("recommended_direction", "")
                        draft_activities = normalize_activities(data.get("draft_activities", []))
                        appendix = _build_design_chat_appendix(career_options, recommended_direction, draft_activities)
                        if appendix:
                            msg = msg + appendix

                    # FINAL 단계: 생성 완료 안내
                    if st.session_state.stage == "FINAL":
                        msg = msg + "\n\n---\n✅ **필요활동**과 **로드맵**을 업데이트했어요. 위 탭에서 바로 확인할 수 있어요."

                    st.markdown(msg, unsafe_allow_html=True)

            # assistant 메시지 저장
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
                if data.get("next_action") == "READY_FOR_FINAL":
                    st.session_state.stage = "FINAL"

            elif st.session_state.stage == "FINAL":
                st.session_state.career_plan = data.get("career_plan", st.session_state.career_plan)
                st.session_state.activities = normalize_activities(data.get("activities", st.session_state.activities))
                st.session_state.roadmap = normalize_roadmap(data.get("roadmap", st.session_state.roadmap))

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
