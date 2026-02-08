# app.py (CLEAN REBUILD)
# 실행: streamlit run app.py
# 필요 패키지: pip install streamlit openai

import json
import re
import uuid
from pathlib import Path

import streamlit as st
from openai import OpenAI

APP_TITLE = "진설이 - 나만의 진로컨설턴트"
DATA_PATH = Path(".jinsul_state.json")
MAX_DISCOVERY_TURNS = 4

# ======================
# Prompts
# ======================

DISCOVERY_PROMPT = """
너는 전문 진로 컨설턴트다. 현재 단계는 [대화 단계].
목표: 관심사/강점/가치관/제약 파악.
규칙: 질문/요약만, 해결책/계획 제시 금지, 질문 최대 3개.
출력(JSON): assistant_message, discovery_summary, next_action
"""

DESIGN_PROMPT = """
너는 전문 진로 컨설턴트다. 현재 단계는 [설계 단계].
목표: 진로 방향 초안 제시.
규칙: 최종 확정처럼 말하지 말 것, 로드맵 배치 금지.
출력(JSON): assistant_message, career_options, recommended_direction, draft_activities, next_action
"""

FINAL_PROMPT = """
너는 전문 진로 컨설턴트다. 현재 단계는 [확정 단계].
목표: 실행 가능한 계획 완성.
규칙: 활동 10개+, 연도별 상/하반기 로드맵.
출력(JSON): assistant_message, career_plan, activities, roadmap
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
    DATA_PATH.write_text(json.dumps({k: st.session_state.get(k) for k in st.session_state.keys()}, ensure_ascii=False))


def load_state():
    if DATA_PATH.exists():
        for k, v in json.loads(DATA_PATH.read_text()).items():
            st.session_state[k] = v

# ======================
# Utils
# ======================

def extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def llm_call(client: OpenAI, system_prompt: str, messages: list[dict]) -> dict:
    r = client.responses.create(
        model="gpt-5-mini",
        input=[{"role": "system", "content": system_prompt}, *messages],
        text={"verbosity": "low"},
    )
    return extract_json(r.output_text)


def normalize_activities(raw):
    out = []
    for a in raw or []:
        if isinstance(a, dict):
            b = dict(a)
            b.setdefault("id", str(uuid.uuid4()))
            b.setdefault("title", "")
            b.setdefault("description", "")
            b.setdefault("priority", "권장")
            b.setdefault("links", [])
            out.append(b)
    return out


def normalize_roadmap(raw):
    out = []
    for r in raw or []:
        if isinstance(r, dict):
            rr = dict(r)
            if isinstance(rr.get("year"), str) and rr["year"].isdigit(): rr["year"] = int(rr["year"])
            rr.setdefault("h1", [])
            rr.setdefault("h2", [])
            out.append(rr)
    return out

# ======================
# State Init
# ======================

def init_state():
    st.session_state.setdefault("stage", "DISCOVERY")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("discovery_turns", 0)
    st.session_state.setdefault("career_options", [])
    st.session_state.setdefault("recommended_direction", "")
    st.session_state.setdefault("activities", [])
    st.session_state.setdefault("roadmap", [])

# ======================
# UI Helpers
# ======================

def badge(p):
    m = PRIORITY_BADGE.get(p, PRIORITY_BADGE["권장"])
    return f"<span style='background:{m['color']};color:white;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:800'>{m['label']}</span>"


def render_activities():
    st.subheader("필요활동")
    acts = normalize_activities(st.session_state.get("activities", []))
    if not acts:
        st.info("아직 활동이 없습니다.")
        return
    for a in acts:
        st.markdown(f"- {badge(a['priority'])} **{a['title']}**", unsafe_allow_html=True)


def render_roadmap():
    st.subheader("로드맵")
    roadmap = normalize_roadmap(st.session_state.get("roadmap", []))
    if not roadmap:
        st.info("아직 로드맵이 없습니다.")
        return

    acts_list = normalize_activities(st.session_state.get("activities", []))
    acts_by_id = {a.get('id'): a for a in acts_list if a.get('id')}
    acts_by_title = {(a.get('title') or '').strip(): a for a in acts_list if (a.get('title') or '').strip()}

    def _resolve(k):
        if k in acts_by_id:
            return acts_by_id[k]
        if isinstance(k, str) and k.strip() in acts_by_title:
            return acts_by_title[k.strip()]
        return None

    for r in sorted(roadmap, key=lambda x: x.get('year', 0)):
        st.markdown(f"### {r.get('year')}년")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("상반기")
            shown = 0
            for k in r.get('h1', []):
                a = _resolve(k)
                if not a:
                    continue
                shown += 1
                st.markdown(f"- {badge(a.get('priority','권장'))} {a.get('title','')}", unsafe_allow_html=True)
            if shown == 0:
                st.caption("배치된 활동이 없어요.")
        with c2:
            st.markdown("하반기")
            shown = 0
            for k in r.get('h2', []):
                a = _resolve(k)
                if not a:
                    continue
                shown += 1
                st.markdown(f"- {badge(a.get('priority','권장'))} {a.get('title','')}", unsafe_allow_html=True)
            if shown == 0:
                st.caption("배치된 활동이 없어요.")


def build_design_appendix(data: dict) -> str:
    """DESIGN 단계에서 '제안(초안)'을 채팅창에 반드시 보여주기 위한 부록 텍스트."""
    parts = []

    options = data.get("career_options", [])
    if isinstance(options, list) and options:
        parts.append("

---
**초안(진로 옵션)**")
        for i, o in enumerate(options[:3], 1):
            if not isinstance(o, dict):
                continue
            title = o.get("title", "")
            fit = o.get("fit_reason", "")
            risk = o.get("risk", "")
            out = o.get("outlook", "")
            parts.append(
                f"{i}. **{title}**
"
                f"- 적합: {fit}
"
                f"- 리스크: {risk}
"
                f"- 전망: {out}"
            )

    rec = (data.get("recommended_direction") or "").strip()
    if rec:
        parts.append(f"
**현재 유력 방향(초안):** {rec}")

    drafts = normalize_activities(data.get("draft_activities", []))
    if drafts:
        parts.append("
---
**초안(필요활동 TOP 6)**")
        for a in drafts[:6]:
            parts.append(f"- {badge(a.get('priority','권장'))} **{a.get('title','')}**")

    return "
".join(parts)
".join(parts)

# ======================
# Main
# ======================

def main():
    st.set_page_config(APP_TITLE, "🧭", layout="wide")
    load_state(); init_state()
    st.title(APP_TITLE)

    with st.sidebar:
        api_key = st.text_input("OpenAI API Key", type="password")
        st.caption(f"현재 단계: {st.session_state.stage}")
        if st.button("전체 초기화"):
            st.session_state.clear()
            if DATA_PATH.exists(): DATA_PATH.unlink()
            st.rerun()

    tab_chat, tab_act, tab_road = st.tabs(["채팅", "필요활동", "로드맵"])

    with tab_chat:
        for m in st.session_state.messages:
            with st.chat_message(m['role']): st.markdown(m['content'])
        user_input = st.chat_input("자유롭게 이야기해 주세요")
        if user_input and not api_key:
            st.warning("API Key를 입력하세요")
        if user_input and api_key:
            client = OpenAI(api_key=api_key)
            st.session_state.messages.append({"role":"user","content":user_input})
            if st.session_state.stage == "DISCOVERY": st.session_state.discovery_turns += 1
            prompt = DISCOVERY_PROMPT if st.session_state.stage=="DISCOVERY" else DESIGN_PROMPT if st.session_state.stage=="DESIGN" else FINAL_PROMPT
            with st.chat_message("assistant"), st.spinner("생각중..."):
                data = llm_call(client, prompt, st.session_state.messages)
                msg = (data.get('assistant_message') or '').strip()

                # ✅ 결과 내기 전(=DESIGN)에도 제안/초안을 채팅창에 반드시 표시
                if st.session_state.stage == "DESIGN":
                    appendix = build_design_appendix(data)
                    if appendix:
                        msg = msg + appendix

                # FINAL 단계 메시지엔 업데이트 안내를 덧붙임
                if st.session_state.stage == "FINAL":
                    msg += "

---
[완료] 필요활동과 로드맵을 업데이트했어요."

                st.markdown(msg, unsafe_allow_html=True)

            st.session_state.messages.append({"role": "assistant", "content": msg})
            if st.session_state.stage=="DISCOVERY":
                if data.get('next_action')=="READY_FOR_DESIGN" or st.session_state.discovery_turns>=MAX_DISCOVERY_TURNS:
                    st.session_state.stage="DESIGN"
            elif st.session_state.stage == "DESIGN":
             st.session_state.career_options = data.get("career_options", [])
             st.session_state.recommended_direction = (data.get("recommended_direction") or "").strip()
             st.session_state.activities = normalize_activities(data.get("draft_activities", []))

               # ✅ 사용자가 "이대로 진행해" 같은 확정 표현을 하면 FINAL로 확실히 전환
             st.session_state.setdefault("design_turns", 0)
             st.session_state.design_turns += 1

             confirm_re = r"(이대로\s*진행|이대로\s*가자|확정|최종|결정|진행해|좋아요|좋아|오케이|ok|OK|go)"
             user_confirmed = bool(re.search(confirm_re, user_input or "", flags=re.IGNORECASE))

             model_ready = data.get("next_action") == "READY_FOR_FINAL"
             enough_draft = bool(st.session_state.recommended_direction) and len(st.session_state.activities) >= 6
             timeout = st.session_state.design_turns >= 3

             if model_ready or user_confirmed or enough_draft or timeout:
               st.session_state.stage = "FINAL"
               # FINAL 즉시 생성해서 로드맵/활동이 바로 보이게
              try:
                  final_data = llm_call(client, FINAL_PROMPT, st.session_state.messages)
                  final_msg = (final_data.get("assistant_message") or "").strip()
                  final_msg += "\n\n---\n[완료] 필요활동과 로드맵을 업데이트했어요."
                  st.session_state.messages.append({"role": "assistant", "content": final_msg})
                  st.session_state.activities = normalize_activities(final_data.get("activities", []))
                  st.session_state.roadmap = normalize_roadmap(final_data.get("roadmap", []))
              except Exception:
                 pass

            elif st.session_state.stage=="FINAL":
                st.session_state.activities = normalize_activities(data.get('activities', []))
                st.session_state.roadmap = normalize_roadmap(data.get('roadmap', []))
            save_state(); st.rerun()

    with tab_act: render_activities()
    with tab_road: render_roadmap()

if __name__=='__main__': main()
