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
MAX_DISCOVERY_TURNS = 4

# ======================
# Prompt Templates
# ======================

DISCOVERY_PROMPT = """
너는 전문 진로 컨설턴트다.
현재 단계는 [대화 단계]다.
목표: 관심사/강점/가치관/제약 파악
규칙: 질문/요약만, 해결책/계획 금지
출력(JSON): assistant_message, discovery_summary, next_action
"""

DESIGN_PROMPT = """
너는 전문 진로 컨설턴트다.
현재 단계는 [설계 단계]다.
목표: 진로 방향 초안 제시
규칙: 최종 확정 금지, 로드맵 배치 금지
출력(JSON): assistant_message, career_options, recommended_direction, draft_activities, next_action
"""

FINAL_PROMPT = """
너는 전문 진로 컨설턴트다.
현재 단계는 [확정 단계]다.
목표: 실행 가능한 계획 완성
규칙: 활동 10개+, 연도별 상/하반기 로드맵
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
    snapshot = {k: st.session_state.get(k) for k in [
        "stage","messages","discovery","discovery_turns","career_options",
        "recommended_direction","career_plan","activities","roadmap",
        "activity_status","selected_year",
    ]}
    DATA_PATH.write_text(json.dumps(snapshot, ensure_ascii=False))


def load_state():
    if DATA_PATH.exists():
        for k, v in json.loads(DATA_PATH.read_text()).items():
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
            raise
        return json.loads(m.group(0))


def llm_call(client: OpenAI, system_prompt: str, messages: list[dict]) -> dict:
    resp = client.responses.create(
        model="gpt-5-mini",
        input=[{"role": "system", "content": system_prompt}, *messages],
        text={"verbosity": "low"},
    )
    return extract_json(resp.output_text)


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
            if isinstance(rr.get("year"), str) and rr["year"].isdigit():
                rr["year"] = int(rr["year"])
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
    return f"<span style='background:{meta['color']};color:white;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:800'>{meta['label']}</span>"


def render_activities_table():
    st.subheader("필요활동")
    acts = normalize_activities(st.session_state.get("activities", []))
    if not acts:
        st.info("아직 활동이 없습니다.")
        return
    header = st.columns([0.7,2.2,4.5,2.2,3.2])
    for h,t in zip(header,["완료","제목","내용","링크","메모"]): h.markdown(f"**{t}**")
    st.markdown("---")
    st.session_state.setdefault("activity_status", {})
    for a in acts:
        aid = a["id"]
        st.session_state.activity_status.setdefault(aid,{"done":False,"memo":""})
        row = st.columns([0.7,2.2,4.5,2.2,3.2])
        st.session_state.activity_status[aid]["done"] = row[0].checkbox("", st.session_state.activity_status[aid]["done"], key=f"done_{aid}")
        row[1].markdown(f"**{a['title']}**<br>{badge(a['priority'])}", unsafe_allow_html=True)
        row[2].write(a['description'])
        if a['links']:
            for i,l in enumerate(a['links'][:2],1): row[3].link_button(f"열기 {i}", l)
        else:
            row[3].caption("—")
        st.session_state.activity_status[aid]["memo"] = row[4].text_area("", st.session_state.activity_status[aid]["memo"], key=f"memo_{aid}", height=60)
        st.markdown("---")


def _resolve_activity_any(acts_by_id: dict, acts_by_title: dict, key):
    """roadmap.h1/h2가 id 또는 title로 들어와도 매칭"""
    if key in acts_by_id:
        return acts_by_id[key]
    if isinstance(key, str):
        k = key.strip()
        if k in acts_by_title:
            return acts_by_title[k]
    return None


def render_roadmap():
    st.subheader("로드맵")
    roadmap = normalize_roadmap(st.session_state.get("roadmap", []))
    if not roadmap:
        st.info("아직 로드맵이 없습니다. 채팅에서 FINAL 결과가 생성되면 표시돼요.")
        return

    acts_list = normalize_activities(st.session_state.get("activities", []))
    acts_by_id = {a.get("id"): a for a in acts_list if a.get("id")}
    acts_by_title = {(a.get("title") or "").strip(): a for a in acts_list if (a.get("title") or "").strip()}

    years = sorted({r.get("year") for r in roadmap if isinstance(r.get("year"), int)})
    if years:
        st.markdown("**타임라인**")
        st.markdown(" | ".join(map(str, years)))

    for r in sorted(roadmap, key=lambda x: x.get("year", 0)):
        year = r.get("year")
        if not isinstance(year, int):
            continue
        st.markdown(f"### {year}년")
        c1, c2 = st.columns(2)

        def _render_half(col, label, items):
            with col:
                st.markdown(f"#### {label}")
                shown = 0
                for k in items or []:
                    a = _resolve_activity_any(acts_by_id, acts_by_title, k)
                    if not a:
                        continue
                    shown += 1
                    st.markdown(
                        f"- {badge((a.get('priority') or '권장'))} {a.get('title','')}",
                        unsafe_allow_html=True,
                    )
                if shown == 0:
                    st.caption("배치된 활동이 없어요.")

        _render_half(c1, "상반기", r.get("h1", []))
        _render_half(c2, "하반기", r.get("h2", []))



def build_design_appendix(career_options, recommended_direction, draft_activities) -> str:
    """DESIGN 단계 초안을 채팅에 안전하게 붙이기 (문자열 안전 버전)."""
    parts = []

    if isinstance(career_options, list) and career_options:
        
---
**초안(진로 옵션)**")
        for i, o in enumerate(career_options[:3], 1):
            if not isinstance(o, dict):
                continue
            title = o.get('title', '')
            fit = o.get('fit_reason', '')
            parts.append(f"{i}. **{title}** - {fit}")

    if recommended_direction:
        parts.append(f"
**유력 방향:** {recommended_direction}")

    if isinstance(draft_activities, list) and draft_activities:
        ---
**초안(필요활동)**")
        for a in draft_activities[:6]:
            if not isinstance(a, dict):
                continue
            parts.append(f"- {a.get('title','')}")

    return "
".join(parts)
".join(parts)
(career_options, recommended_direction, draft_activities) -> str:
    parts = []
    if career_options:
        
---
**초안(진로 옵션)**")
        for i,o in enumerate(career_options[:3],1):
            parts.append(f"{i}. **{o.get('title','')}** - {o.get('fit_reason','')}")
    if recommended_direction:
        parts.append(f"
**유력 방향:** {recommended_direction}")
    if draft_activities:
        ---
**초안(필요활동)**")
        for a in draft_activities[:6]: parts.append(f"- {a.get('title','')}")
    return "
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

    tab_chat, tab_act, tab_road = st.tabs(["채팅","필요활동","로드맵"])

    with tab_chat:
        for m in st.session_state.messages:
            with st.chat_message(m['role']): st.markdown(m['content'], unsafe_allow_html=True)
        user_input = st.chat_input("자유롭게 이야기해 주세요")
        if user_input and not api_key: st.warning("API Key를 입력하세요")
        if user_input and api_key:
            client = OpenAI(api_key=api_key)
            st.session_state.messages.append({"role":"user","content":user_input})
            if st.session_state.stage=="DISCOVERY": st.session_state.discovery_turns+=1
            prompt = DISCOVERY_PROMPT if st.session_state.stage=="DISCOVERY" else DESIGN_PROMPT if st.session_state.stage=="DESIGN" else FINAL_PROMPT
            with st.chat_message("assistant"), st.spinner("생각중..."):
                data = llm_call(client, prompt, st.session_state.messages)
                msg = (data.get('assistant_message') or '').strip()
                if st.session_state.stage=="DESIGN": msg += build_design_appendix(data.get('career_options',[]), data.get('recommended_direction',''), normalize_activities(data.get('draft_activities',[])))
                if st.session_state.stage=="FINAL": msg += "

---
[완료] 필요활동과 로드맵을 업데이트했어요."
                st.markdown(msg, unsafe_allow_html=True)
            st.session_state.messages.append({"role":"assistant","content":msg})
            if st.session_state.stage=="DISCOVERY":
                if data.get('next_action')=="READY_FOR_DESIGN" or st.session_state.discovery_turns>=MAX_DISCOVERY_TURNS:
                    st.session_state.stage="DESIGN"
            elif st.session_state.stage=="DESIGN":
                st.session_state.career_options = data.get('career_options', [])
                st.session_state.recommended_direction = data.get('recommended_direction', '')
                st.session_state.activities = normalize_activities(data.get('draft_activities', []))

                # ✅ DESIGN → FINAL 자동 전환(모델 next_action이 애매할 때도 넘어가게)
                st.session_state.setdefault('design_turns', 0)
                st.session_state.design_turns += 1

                confirm_re = r"(확정|최종|결정|이대로|진행|좋아요|좋아|오케이|ok|OK|go)"
                user_confirmed = bool(re.search(confirm_re, user_input or "", flags=re.IGNORECASE))
                model_ready = data.get('next_action') == "READY_FOR_FINAL"
                enough_draft = bool(st.session_state.recommended_direction) and len(st.session_state.activities) >= 6
                timeout = st.session_state.design_turns >= 3

                if model_ready or user_confirmed or enough_draft or timeout:
                    st.session_state.stage = "FINAL"
                    # FINAL을 즉시 생성해서 로드맵/활동이 바로 보이게
                    try:
                        final_data = llm_call(client, FINAL_PROMPT, st.session_state.messages)
                        final_msg = (final_data.get('assistant_message') or '').strip()
                        final_msg += "

---
[완료] 필요활동과 로드맵을 업데이트했어요."
                        st.session_state.messages.append({"role": "assistant", "content": final_msg})
                        st.session_state.career_plan = final_data.get('career_plan', {})
                        st.session_state.activities = normalize_activities(final_data.get('activities', []))
                        st.session_state.roadmap = normalize_roadmap(final_data.get('roadmap', []))
                    except Exception:
                        pass
            elif st.session_state.stage=="FINAL":
                st.session_state.career_plan=data.get('career_plan',{})
                st.session_state.activities=normalize_activities(data.get('activities',[]))
                st.session_state.roadmap=normalize_roadmap(data.get('roadmap',[]))
            save_state(); st.rerun()

    with tab_act: render_activities_table()
    with tab_road: render_roadmap()

if __name__=='__main__': main()
