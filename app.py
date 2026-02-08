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
너는 따뜻하지만 날카로운 질문을 던지는 전문 진로 코치다.
현재 단계는 [대화 단계(Discovery)]이다.

[목표]
- 사용자의 관심사, 강점, 가치관, 제약을 탐색한다.
- 정답이나 계획을 주지 말고, “가능성 가설”을 세워 검증한다.

[대화 방식]
- 매 응답마다 반드시 다음 순서를 따른다:
  1) 지금까지의 대화를 바탕으로 한 ‘가설’ 1~2개 제시
     (예: “지금까지 보면 A 성향이 강해 보여요”)
  2) 그 가설을 확인하거나 깨기 위한 질문 1개
  3) 사용자가 쉽게 답할 수 있는 질문 1개
    
- 요약은 매번 하지 않는다.
  단, 새로운 정보가 충분히 쌓였을 때만 1~2줄로 짧게 정리한다.

[금지]
- 진로 계획, 활동 목록, 로드맵 제시 금지
- “정리해보면…”으로 시작하는 장황한 요약 금지

[출력 형식(JSON)]
- assistant_message: 사용자에게 보여줄 자연스러운 대화 문장
- discovery_summary: (선택) 핵심 신호 요약 1~2줄
- next_action: READY_FOR_DESIGN 또는 CONTINUE
"""

DESIGN_PROMPT = """
너는 현실적인 조언을 해주는 진로 설계 컨설턴트다.
현재 단계는 [설계 단계(Design)]이다.

[목표]
- 사용자가 검토할 수 있는 진로 방향 ‘초안’을 제시한다.
- 선택·수정·확정을 유도하는 것이 목표다.

[출력 원칙]
- 진로 옵션은 2~3개만 제시한다.
- 각 옵션에는 반드시 포함한다:
  - 왜 이 방향이 맞는지(적합 근거)
  - 현실적인 리스크 1~2개
  - 이 방향을 시험해볼 수 있는 초기 행동 예시

- 추천 방향은 1개만 제시하되,
  “현재로서는 가장 유력한 초안”임을 분명히 한다.

- 필요활동은 ‘초안’ 수준으로 6~8개만 제시한다.
  (아직 완성본 아님)

[대화 톤]
- “결정하세요”가 아니라
  “이 중 어떤 쪽이 더 끌리는지”를 묻는 톤
- 중간에 반드시 사용자에게 선택/수정 질문을 던질 것

[금지]
- 연도별 로드맵 작성 금지
- 최종 확정처럼 말하기 금지

[⚠️ 출력 제약 — 매우 중요]
- 응답은 반드시 하나의 JSON 객체만 출력한다. (JSON 밖 텍스트/마크다운 금지)
- recommended_direction은 반드시 문자열(string) 한 줄로 출력한다.
  - 객체(dict)나 배열로 출력하지 말 것
  - 이유/설명은 assistant_message 또는 career_options에만 포함할 것

[출력 형식(JSON)]
{
  "assistant_message": "사용자에게 보여줄 자연스러운 대화",
  "career_options": [
    {"title":"", "fit_reason":"", "risk":"", "outlook":""}
  ],
  "recommended_direction": "추천 진로 제목 한 줄",
  "draft_activities": [
    {"title":"", "description":"", "priority":"핵심|권장|선택", "links": []}
  ],
  "next_action": "READY_FOR_FINAL 또는 REFINE"
}
"""

FINAL_PROMPT = """
너는 실행 중심의 진로 컨설턴트다.
현재 단계는 [확정 단계(Final)]이다.

[목표]
- 바로 실행 가능한 진로 계획을 완성한다.
- 결과는 앱의 ‘필요활동’과 ‘로드맵’ 탭에 그대로 사용된다.

[필수 산출물 규칙]
1) activities
- 최소 10개 이상
- 각 활동은 title, description, priority를 포함
- priority는 핵심 / 권장 / 선택 중 하나

2) roadmap
- 최소 2개 연도 이상
- 각 연도는 반드시 h1(상반기), h2(하반기)를 가진다
- 각 반기에는 최소 3개의 활동을 배치한다
- roadmap에 사용하는 활동은 반드시 activities에 존재해야 한다

[대화 톤]
- “이제 이렇게 진행하면 됩니다”라는 확정 톤
- 불확실한 표현 최소화

[검증]
- 활동 또는 로드맵이 비어 있으면 실패로 간주하고 다시 생성한다.

[출력 형식(JSON)]
- assistant_message
- career_plan
- activities
- roadmap
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
    """모델 출력이 JSON이 아닐 때도 앱이 죽지 않도록 최대한 복구."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model output")
    try:
        return json.loads(text)
    except Exception:
        # 응답 중 JSON 블록만 뽑아내기
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
    parts = []

    options = data.get("career_options", [])
    if isinstance(options, list) and options:
        parts.append("\n\n---\n**초안(진로 옵션)**")
        for i, o in enumerate(options[:3], 1):
            title = o.get("title", "")
            fit = o.get("fit_reason", "")
            risk = o.get("risk", "")
            out = o.get("outlook", "")
            parts.append(
                f"{i}. **{title}**\n"
                f"- 적합: {fit}\n"
                f"- 리스크: {risk}\n"
                f"- 전망: {out}"
            )

    rec_val = data.get("recommended_direction")
    if isinstance(rec_val, str):
        rec = rec_val.strip()
    elif isinstance(rec_val, dict):
        # 모델이 실수로 객체로 보낼 때 title만 추출
        rec = str(rec_val.get("title", "")).strip()
    elif rec_val is None:
        rec = ""
    else:
        rec = str(rec_val).strip()
    if rec:
        parts.append(f"\n**현재 유력 방향(초안):** {rec}")

    drafts = normalize_activities(data.get("draft_activities", []))
    if drafts:
        parts.append("\n---\n**초안(필요활동 TOP 6)**")
        for a in drafts[:6]:
            parts.append(f"- {badge(a.get('priority','권장'))} **{a.get('title','')}**")

    return "\n".join(parts)



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
                try:
                    data = llm_call(client, prompt, st.session_state.messages)
                except Exception:
                    # JSON 파싱/모델 출력 문제로 앱이 죽지 않게 폴백
                    data = {"assistant_message": "응답을 JSON으로 해석하지 못했어요. 같은 내용을 한 번만 더 말해줘!"}

                msg = (data.get('assistant_message') or '').strip()

                # ✅ 결과 내기 전(=DESIGN)에도 제안/초안을 채팅창에 반드시 표시
                if st.session_state.stage == "DESIGN":
                    appendix = build_design_appendix(data)
                    if appendix:
                        msg = msg + appendix

                # FINAL 단계 메시지엔 업데이트 안내를 덧붙임
                if st.session_state.stage == "FINAL":
                   msg += "\n\n---\n[완료] 필요활동과 로드맵을 업데이트했어요."


                st.markdown(msg, unsafe_allow_html=True)

            st.session_state.messages.append({"role": "assistant", "content": msg})
            if st.session_state.stage=="DISCOVERY":
                if data.get('next_action')=="READY_FOR_DESIGN" or st.session_state.discovery_turns>=MAX_DISCOVERY_TURNS:
                    st.session_state.stage="DESIGN"
            elif st.session_state.stage == "DESIGN":
                st.session_state.career_options = data.get("career_options", [])
                _rec_val = data.get("recommended_direction")
                if isinstance(_rec_val, str):
                    st.session_state.recommended_direction = _rec_val.strip()
                elif isinstance(_rec_val, dict):
                    st.session_state.recommended_direction = str(_rec_val.get("title", "")).strip()
                elif _rec_val is None:
                    st.session_state.recommended_direction = ""
                else:
                    st.session_state.recommended_direction = str(_rec_val).strip()
                st.session_state.activities = normalize_activities(data.get("draft_activities", []))
    
                # 사용자가 확정 의사를 표현하면 FINAL로 전환
                st.session_state.setdefault("design_turns", 0)
                st.session_state.design_turns += 1

                confirm_re = r"(이대로\s*진행|이대로\s*가자|확정|최종|결정|진행해|좋아요|좋아|오케이|ok|OK|go)"
                user_confirmed = bool(re.search(confirm_re, user_input or "", flags=re.IGNORECASE))

                model_ready = data.get("next_action") == "READY_FOR_FINAL"
                enough_draft = bool(st.session_state.recommended_direction) and len(st.session_state.activities) >= 6
                timeout = st.session_state.design_turns >= 3

                if model_ready or user_confirmed or enough_draft or timeout:
                    st.session_state.stage = "FINAL"
                    try:
                        final_data = llm_call(client, FINAL_PROMPT, st.session_state.messages)
                        final_msg = (final_data.get("assistant_message") or "").strip()
                        final_msg += "\n\n---\n[완료] 필요활동과 로드맵을 업데이트했어요."
                        st.session_state.messages.append(
                            {"role": "assistant", "content": final_msg}
                        )
                        st.session_state.activities = normalize_activities(
                            final_data.get("activities", [])
                        )
                        st.session_state.roadmap = normalize_roadmap(
                            final_data.get("roadmap", [])
                        )
                    except Exception:
                        pass
            elif st.session_state.stage=="FINAL":
                st.session_state.activities = normalize_activities(data.get('activities', []))
                st.session_state.roadmap = normalize_roadmap(data.get('roadmap', []))
            save_state(); st.rerun()

    with tab_act: render_activities()
    with tab_road: render_roadmap()

if __name__=='__main__': main()
