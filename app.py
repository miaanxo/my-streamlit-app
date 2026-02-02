import random
import requests
import streamlit as st

# =============================
# Page config
# =============================
st.set_page_config(
    page_title="🎬 나와 어울리는 영화는?",
    page_icon="🎬",
    layout="centered",
)

# =============================
# TMDB settings
# =============================
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"
DISCOVER_URL = "https://api.themoviedb.org/3/discover/movie"

GENRE_IDS = {
    "action": 28,
    "comedy": 35,
    "drama": 18,
    "sf": 878,
    "romance": 10749,
    "fantasy": 14,
}

# =============================
# Taste mapping (A/B/C/D)
# =============================
# A: romance/drama, B: action/adventure, C: sf/fantasy, D: comedy
CHOICE_TO_TASTE = {0: "romance_drama", 1: "action_adventure", 2: "sf_fantasy", 3: "comedy"}
TASTE_KEYS = ["romance_drama", "action_adventure", "sf_fantasy", "comedy"]

TASTE_TO_TMDB_GENRE = {
    "romance_drama": GENRE_IDS["drama"],
    "action_adventure": GENRE_IDS["action"],
    "sf_fantasy": GENRE_IDS["sf"],
    "comedy": GENRE_IDS["comedy"],
}

# =============================
# Result copy templates
# =============================
RESULT_COPY = {
    "romance_drama": {
        "title": "💗 당신에게 딱인 장르는: 로맨스/드라마!",
        "one_liner": "감정선과 관계의 흐름에 강한 몰입을 하는 타입",
        "desc": [
            "당신은 사건보다 “사람”을 먼저 보는 편이에요.",
            "상황이 힘들수록 누군가의 마음, 선택, 관계의 변화에 더 집중하죠.",
            "잔잔해 보여도 깊게 남는 이야기에서 큰 만족을 느낄 가능성이 높아요.",
        ],
        "why_templates": [
            "이 영화는 인물의 감정 변화와 관계의 디테일이 매력이라, 당신의 몰입 포인트와 잘 맞아요.",
            "여운이 길게 남는 장면이 많아 “보고 나서 생각나는 영화”를 좋아한다면 특히 추천!",
        ],
    },
    "action_adventure": {
        "title": "🔥 당신에게 딱인 장르는: 액션/어드벤처!",
        "one_liner": "답답한 전개 싫어! 속도감과 돌파력이 중요한 타입",
        "desc": [
            "당신은 위기 상황에서 “일단 해보자” 모드로 전환이 빠른 편이에요.",
            "명확한 목표와 빠른 전개, 통쾌한 해결을 볼 때 스트레스가 확 풀리죠.",
            "몰입감 있는 장면과 긴장감 있는 전개가 있는 영화에 만족도가 높아요.",
        ],
        "why_templates": [
            "전개가 빠르고 긴장감이 살아 있어서, 당신이 좋아하는 “몰입형 재미”에 딱이에요.",
            "액션뿐 아니라 미션/탐험 요소가 있어 끝까지 쭉 보게 될 확률이 높아요.",
        ],
    },
    "sf_fantasy": {
        "title": "🌌 당신에게 딱인 장르는: SF/판타지!",
        "one_liner": "상상력과 세계관에 진심인 타입",
        "desc": [
            "당신은 “왜?” “만약?” 같은 질문을 좋아하고, 세계관에 빠지면 깊게 파고들어요.",
            "현실을 잠시 끄고 새로운 규칙의 세계에 들어가는 경험을 중요하게 생각하죠.",
            "독특한 설정, 반전, 확장되는 이야기 구조에 특히 강하게 끌릴 가능성이 높아요.",
        ],
        "why_templates": [
            "설정과 세계관이 탄탄해서, 당신이 좋아하는 “상상 몰입” 포인트를 제대로 건드려요.",
            "한 번 보면 해석하거나 다시 찾게 되는 요소가 있어 만족감이 클 거예요.",
        ],
    },
    "comedy": {
        "title": "😂 당신에게 딱인 장르는: 코미디!",
        "one_liner": "인생은 텐션! 웃음이 최고의 회복템인 타입",
        "desc": [
            "당신은 분위기를 무겁게 끌고 가기보다 “살짝 가볍게” 푸는 센스가 있어요.",
            "재미와 리듬감을 중요하게 보고, 기분 전환에 능한 편이죠.",
            "편하게 보면서도 확실히 웃을 수 있는 작품에서 만족도가 높아요.",
        ],
        "why_templates": [
            "포인트가 빠르고 대사가 재밌어서, 당신이 좋아하는 “즉효 웃음”에 잘 맞아요.",
            "가볍게 보기 시작해도 결국 기분이 좋아지는 타입의 영화라 추천!",
        ],
    },
}

# =============================
# NEW Questions (7)
# =============================
QUESTIONS = [
    {
        "q": "재난 영화의 오프닝",
        "scene": "지진으로 캠퍼스 건물이 흔들린다. 경보음이 울리는 순간, 당신은?",
        "options": [
            "주변 사람들과 눈을 마주치며 서로 괜찮은지 확인한다",
            "바로 출구 방향을 파악하고 먼저 움직인다",
            "상황의 원인과 다음 전개를 머릿속으로 예측한다",
            "“이거 영화 시작 같은데…”라며 긴장을 풀어본다",
        ],
    },
    {
        "q": "로맨스 영화의 핵심 장면",
        "scene": "늦은 밤, 친한 친구가 갑자기 진지해진 표정으로 당신을 부른다.",
        "options": [
            "무슨 말을 하든 끝까지 차분히 들어준다",
            "분위기가 무거워질까 봐 다른 이야기로 돌린다",
            "이 순간의 의미를 곰곰이 생각한다",
            "웃으며 농담으로 반응한다",
        ],
    },
    {
        "q": "생존 영화 상황",
        "scene": "낯선 도시에서 지갑과 휴대폰을 모두 잃어버렸다.",
        "options": [
            "감정을 가라앉히고 상황을 받아들인다",
            "해결할 수 있는 방법부터 바로 찾는다",
            "왜 이런 상황이 됐는지 분석한다",
            "이 상황도 나중에 웃을 수 있을 것 같다",
        ],
    },
    {
        "q": "히어로 영화의 선택",
        "scene": "위험하지만 누군가를 도울 수 있는 순간이다.",
        "options": [
            "그 사람이 어떤 마음일지 먼저 생각한다",
            "망설이지 않고 바로 행동한다",
            "이 선택이 불러올 결과를 상상한다",
            "긴장 속에서도 특유의 여유와 농담으로 상황을 버틴다",
        ],
    },
    {
        "q": "판타지 영화 설정",
        "scene": "당신만이 사용할 수 있는 비밀 능력이 생겼다.",
        "options": [
            "소중한 사람을 지키는 데 쓰고 싶다",
            "결정적인 순간에 확실히 쓰고 싶다",
            "능력의 규칙과 한계부터 궁금하다",
            "재밌게 활용할 방법부터 떠오른다",
        ],
    },
    {
        "q": "영화 속 팀플",
        "scene": "팀이 흔들리고 있다. 리더가 필요한 순간.",
        "options": [
            "팀원들의 감정부터 살핀다",
            "빠르게 결정을 내리고 방향을 제시한다",
            "여러 시나리오를 놓고 전략을 세운다",
            "분위기를 살리며 팀을 다독인다",
        ],
    },
    {
        "q": "엔딩 장면",
        "scene": "당신의 이야기가 영화로 끝난다면, 가장 마음에 드는 결말은?",
        "options": [
            "조용히 감정이 정리되는 결말",
            "통쾌하고 시원한 결말",
            "해석이 열려 있는 결말",
            "웃고 나올 수 있는 결말",
        ],
    },
]
TOTAL = len(QUESTIONS)

# =============================
# Helpers
# =============================
@st.cache_data(show_spinner=False, ttl=60 * 30)
def fetch_movies(api_key: str, genre_id: int, min_vote_count: int, language: str = "ko-KR", n: int = 5):
    """
    유명도 = 리뷰 수(vote_count)로 판단
    - vote_count.gte 로 최소 리뷰 수 필터
    - sort_by=vote_count.desc 로 리뷰 많은 순
    """
    params = {
        "api_key": api_key,
        "with_genres": genre_id,
        "language": language,
        "include_adult": "false",
        "page": 1,
        "vote_count.gte": min_vote_count,
        "sort_by": "vote_count.desc",
    }
    r = requests.get(DISCOVER_URL, params=params, timeout=15)
    r.raise_for_status()
    results = (r.json().get("results") or [])[:n]
    return results

def analyze(answers_idx):
    scores = {k: 0 for k in TASTE_KEYS}
    for idx in answers_idx:
        scores[CHOICE_TO_TASTE[idx]] += 1

    # 동점 처리: 우선순위
    priority = ["romance_drama", "action_adventure", "sf_fantasy", "comedy"]
    best = max(scores.values())
    tied = [k for k, v in scores.items() if v == best]
    for p in priority:
        if p in tied:
            return p, scores
    return tied[0], scores

def safe_text(x, fallback=""):
    if x is None:
        return fallback
    s = str(x).strip()
    return s if s else fallback

def pick_why(taste_key):
    return random.choice(RESULT_COPY[taste_key]["why_templates"])

# =============================
# Session state
# =============================
if "step" not in st.session_state:
    st.session_state.step = 0  # 0..TOTAL (TOTAL = result page)
if "answers" not in st.session_state:
    st.session_state.answers = [None] * TOTAL  # 질문별 선택 index 저장
if "show_result" not in st.session_state:
    st.session_state.show_result = False

# =============================
# Sidebar
# =============================
with st.sidebar:
    st.header("설정")
    api_key = st.text_input("TMDB API Key", type="password", placeholder="API Key 입력")

    st.subheader("추천 영화 유명도")
    fame_level = st.select_slider(
        "리뷰 수(투표 수) 기준으로 고를게요",
        options=["아무거나", "보통", "유명", "초유명"],
        value="유명",
    )
    fame_to_min_votes = {"아무거나": 0, "보통": 200, "유명": 1000, "초유명": 5000}
    min_vote_count = fame_to_min_votes[fame_level]
    st.caption("TMDB의 vote_count(리뷰/투표 수)로 유명도를 판단해요.")

    st.divider()
    if st.button("처음부터 다시"):
        st.session_state.step = 0
        st.session_state.answers = [None] * TOTAL
        st.session_state.show_result = False
        st.rerun()

# =============================
# Header
# =============================
st.title("🎬 나와 어울리는 영화는?")
st.caption("상황극 7개로 당신의 영화 취향을 찾아드립니다. 한 문항씩 몰입해서 골라보세요 🙂")

# Progress
current = min(st.session_state.step + 1, TOTAL)
st.progress((st.session_state.step) / TOTAL)
st.markdown(f"#### {current} / {TOTAL}")

# =============================
# Question page
# =============================
if st.session_state.step < TOTAL:
    i = st.session_state.step
    q = QUESTIONS[i]

    with st.container(border=True):
        st.markdown(f"### 🎭 {i+1}. {q['q']}")
        st.write(q["scene"])

        # 라디오의 index를 직접 다루기 위해 옵션 문자열 사용
        selected = st.radio(
            "선택",
            q["options"],
            index=st.session_state.answers[i] if st.session_state.answers[i] is not None else None,
            key=f"radio_{i}",
        )

    # 저장 버튼 영역
    left, right = st.columns([1, 1])

    with left:
        st.button(
            "⬅️ 이전",
            disabled=(i == 0),
            on_click=lambda: (
                setattr(st.session_state, "step", st.session_state.step - 1)
            ),
        )

    with right:
        def go_next():
            st.session_state.answers[i] = q["options"].index(selected)
            st.session_state.step += 1

        st.button("다음 ➡️", type="primary", on_click=go_next)

# =============================
# Result page
# =============================
else:
    # validation
    if any(a is None for a in st.session_state.answers):
        st.warning("아직 선택하지 않은 문항이 있어요. 이전으로 돌아가서 답변을 완료해주세요!")
        if st.button("⬅️ 마지막 문항으로 돌아가기"):
            # 마지막 미완료 문항으로 이동
            first_none = st.session_state.answers.index(None)
            st.session_state.step = first_none
            st.rerun()
        st.stop()

    if not api_key:
        st.error("사이드바에 TMDB API Key를 입력해주세요.")
        st.stop()

    with st.spinner("결과를 분석하고 추천 영화를 불러오는 중..."):
        taste_key, scores = analyze(st.session_state.answers)
        genre_id = TASTE_TO_TMDB_GENRE[taste_key]

        try:
            movies = fetch_movies(api_key, genre_id, min_vote_count=min_vote_count, language="ko-KR", n=5)
            if not movies and min_vote_count > 0:
                # 조건 완화 (UX)
                movies = fetch_movies(api_key, genre_id, min_vote_count=0, language="ko-KR", n=5)
                soften_msg = True
            else:
                soften_msg = False
        except requests.HTTPError:
            st.error("TMDB 요청에 실패했어요. API Key가 올바른지 확인해주세요.")
            st.stop()
        except requests.RequestException:
            st.error("네트워크 문제로 TMDB에 연결하지 못했어요. 잠시 후 다시 시도해주세요.")
            st.stop()

    copy = RESULT_COPY[taste_key]

    st.divider()
    st.markdown(f"## {copy['title']}")
    st.caption(copy["one_liner"])

    with st.container(border=True):
        for line in copy["desc"]:
            st.write("• " + line)

    if soften_msg:
        st.info("선택한 유명도 조건에서 영화가 부족해, 조건을 완화해 추천했어요.")

    st.markdown("### 🍿 추천 영화 5편")
    if not movies:
        st.info("추천할 영화가 없어요.")
        st.stop()

    # 3-column cards
    cols = st.columns(3)
    for idx, m in enumerate(movies):
        col = cols[idx % 3]

        title = safe_text(m.get("title") or m.get("name"), "제목 없음")
        rating = m.get("vote_average")
        rating_text = f"{float(rating):.1f}" if rating is not None else "-"
        vote_count = m.get("vote_count")
        vote_count_text = f"{int(vote_count):,}" if vote_count is not None else "-"
        poster_path = m.get("poster_path")
        poster_url = f"{POSTER_BASE_URL}{poster_path}" if poster_path else None
        overview = safe_text(m.get("overview"), "줄거리 정보가 없어요.")
        why = pick_why(taste_key)

        with col:
            with st.container(border=True):
                if poster_url:
                    st.image(poster_url, use_container_width=True)
                else:
                    st.caption("포스터 없음")

                st.markdown(f"**{title}**")
                st.caption(f"⭐ {rating_text}  ·  🗣️ {vote_count_text}")

                with st.expander("상세 보기"):
                    st.write(overview)
                    st.markdown("**💡 이 영화를 추천하는 이유**")
                    st.write(why)

    st.divider()
    bottom_left, bottom_right = st.columns([1, 1])
    with bottom_left:
        if st.button("⬅️ 답변 다시 보기"):
            st.session_state.step = TOTAL - 1
            st.rerun()
    with bottom_right:
        if st.button("🔄 다시 하기", type="primary"):
            st.session_state.step = 0
            st.session_state.answers = [None] * TOTAL
            st.session_state.show_result = False
            st.rerun()
