"""데모 화면.  실행: streamlit run app.py"""
import streamlit as st

import agent
import context as ctx

# 가운데 정렬 기본 너비(centered)로 둔다. wide로 하면 넓은 모니터에서 글이 퍼지고 빈칸이 생긴다.
st.set_page_config(page_title="인적공제 라우팅 상담", page_icon="🧾", layout="centered")
st.title("인적공제 상담 라우팅 에이전트")
st.write("2025년 귀속 · 근거: 국세상담센터 인적공제 Q&A, 키워드 연말정산 인적공제  \n"
         f"판정 {agent.ROUTER_MODEL} · 답변 {agent.ANSWER_MODEL} · 넘기기 임계값 {agent.CONF_THRESHOLD}")

examples = ["결혼식은 안 하고 혼인신고만 했는데 배우자 공제 되나요?",
            "어머니가 국민연금을 1년에 600만원 받으시는데 기본공제 되나요?",
            "72세 어머니가 국민연금을 1년에 400만원 받으시는데, 기본공제와 경로우대 공제를 둘 다 받을 수 있나요?",
            "첫째가 3살이고 올해 둘째를 낳았는데 자녀세액공제는 얼마예요?",
            "종합소득세 신고 기한이 언제예요?"]
pick = st.selectbox("예시 질문", ["(직접 입력)"] + examples)
q = st.text_input("질문", value="" if pick == "(직접 입력)" else pick)

if st.button("질문하기", type="primary") and q.strip():
    with st.spinner("판정 → 근거 조립 → 답변 → 검증 중..."):
        s = agent.run(q.strip())

    # 처리 순서(판정 → 도구 → 답변 → 검증 → 근거)대로 위에서 아래로 한 줄씩 보여 준다.
    st.subheader("① 판정")
    st.write(f"카테고리: **{', '.join(s['categories'])}** · 확신도: **{s.get('confidence', 0):.2f}**")
    st.write(f"이유: {s.get('reason', '')}")

    st.subheader("② 부른 도구")
    st.write(" → ".join(s.get("tools_called", [])) or "-")

    st.subheader("③ 답변")
    if s.get("route") == "handoff":
        st.warning(f"{s['answer']}  \n넘긴 이유: {s.get('handoff_reason')}")
    else:
        st.success(s["answer"])

    if s.get("checks"):
        st.subheader("④ 검증 결과")
        for c in s["checks"]:
            icon = "✅" if c["ok"] else "⚠️"
            st.write(f"{icon} {c['attempt']}번째 답변 — " + ("통과" if c["ok"] else " / ".join(c["problems"])))
            st.write(f"답변의 숫자 {c['numbers']} · 붙인 근거 {c['cited']}")

    if s.get("chunk_ids"):
        st.subheader(f"⑤ 근거로 넣은 자료 ({len(s['chunk_ids'])}조각)")
        cited = s["checks"][-1]["cited"] if s.get("checks") else []
        for cid in cited:
            with st.expander(f"답변이 인용한 근거 {cid} · {ctx.ALL[cid].title}"):
                st.write(ctx.ALL[cid].text.strip())
        with st.expander("프롬프트에 넣은 근거 번호 전체"):
            st.write(", ".join(s["chunk_ids"]))
