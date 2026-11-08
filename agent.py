"""파이프라인 (LangGraph).

질문 → classify(카테고리 판정) → gate(넘길지 결정) → retrieve(카테고리별 근거 조회 도구)
     → answer(근거만으로 답변) → verify(숫자·근거 번호 검사) → 끝
                                       ↘ 위반이면 answer 다시(1번) → 또 위반이면 handoff
gate·answer에서 넘겨야 하면 handoff(넘기기 도구)로 간다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Optional, TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

import context as ctx
from prompts import ANSWER_SYSTEM, RETRY_NOTE, ROUTER_SYSTEM

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
load_dotenv(HERE.parent / "cs-agent" / ".env")  # 이 폴더에 .env가 없으면 cs-agent 실습의 키를 쓴다

ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "gpt-5.6-luna")
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "gpt-5.6-terra")
CONF_THRESHOLD = float(os.environ.get("CONF_THRESHOLD", "0.5"))
MAX_ATTEMPTS = 2

Category = Literal["FAMILY", "INCOME", "EXTRA", "CREDIT", "OTHER"]


# ---------- ① 카테고리 판정 ----------
class RouteDecision(BaseModel):
    categories: list[Category] = Field(description="필요한 카테고리 1~2개. 중심이 되는 것을 맨 앞에")
    confidence: float = Field(ge=0, le=1, description="판정이 맞을 확률")
    reason: str = Field(description="한 문장 이유")


_router = None
_answerer = None


def router():
    global _router
    if _router is None:
        _router = init_chat_model(ROUTER_MODEL, model_provider="openai", temperature=0,
                                  timeout=60, max_retries=2).with_structured_output(RouteDecision)
    return _router


def answerer():
    global _answerer
    if _answerer is None:
        _answerer = init_chat_model(ANSWER_MODEL, model_provider="openai", temperature=0,
                                    timeout=90, max_retries=2)
    return _answerer


# ---------- 도구: 카테고리별 근거 조회 4개 + 넘기기 1개 ----------
def _lookup(category: str) -> dict:
    text, ids = ctx.build_context([category])
    return {"category": category, "text": text, "ids": ids}


TOOLS = {
    "lookup_family": lambda: _lookup("FAMILY"),
    "lookup_income": lambda: _lookup("INCOME"),
    "lookup_extra": lambda: _lookup("EXTRA"),
    "lookup_credit": lambda: _lookup("CREDIT"),
}
TOOL_OF = {"FAMILY": "lookup_family", "INCOME": "lookup_income",
           "EXTRA": "lookup_extra", "CREDIT": "lookup_credit"}
HANDOFF_MESSAGE = "이 질문은 인적공제 자료로 답할 수 없어 상담원에게 넘기겠습니다."


class State(TypedDict, total=False):
    question: str
    categories: list[str]
    confidence: float
    reason: str
    tools_called: list[str]
    context: str
    chunk_ids: list[str]
    answer: str
    attempts: int
    problems: list[str]
    checks: list[dict]
    route: str            # "answer" | "handoff"
    handoff_reason: str


def classify(state: State) -> State:
    d: RouteDecision = router().invoke([
        ("system", ROUTER_SYSTEM),
        ("human", state["question"]),
    ])
    cats = list(dict.fromkeys(d.categories))[:2] or ["OTHER"]
    if "OTHER" in cats:
        cats = ["OTHER"]
    return {"categories": cats, "confidence": d.confidence, "reason": d.reason,
            "tools_called": [], "attempts": 0, "checks": []}


def gate_next(state: State) -> str:
    if state["categories"] == ["OTHER"]:
        return "handoff"
    if state["confidence"] < CONF_THRESHOLD:
        return "handoff"
    return "retrieve"


def retrieve(state: State) -> State:
    called, texts, ids = list(state.get("tools_called", [])), [], []
    for cat in state["categories"]:
        name = TOOL_OF[cat]
        called.append(name)
        r = TOOLS[name]()
        for cid, part in zip(r["ids"], r["text"].split("\n\n---\n\n")):
            if cid not in ids:
                ids.append(cid)
                texts.append(part)
    return {"tools_called": called, "context": "\n\n---\n\n".join(texts), "chunk_ids": ids}


def answer(state: State) -> State:
    msgs = [("system", ANSWER_SYSTEM),
            ("human", f"[근거]\n{state['context']}\n\n[질문]\n{state['question']}")]
    if state.get("problems"):
        msgs.append(("ai", state["answer"]))
        msgs.append(("human", RETRY_NOTE.format(problems="\n".join(f"- {p}" for p in state["problems"]))))
    out = answerer().invoke(msgs)
    text = out.content if isinstance(out.content, str) else "".join(
        b.get("text", "") for b in out.content if isinstance(b, dict))
    return {"answer": text.strip(), "attempts": state.get("attempts", 0) + 1}


def answer_next(state: State) -> str:
    return "handoff" if "NO_ANSWER" in state["answer"] else "verify"


# ---------- ④ 검증 (코드로) ----------
CITE = re.compile(r"\[?((?:QA|KW)-\d{2,3})\]?")


def numbers_in(text: str) -> set[int]:
    text = CITE.sub(" ", text)                          # 근거 번호 안의 숫자는 빼고 본다
    text = re.sub(r"(?<=\d),(?=\d)", "", text)          # 5,166,667 → 5166667
    return {int(m) for m in re.findall(r"\d+", text)}


def guardrail(answer_text: str, context_text: str, question: str, chunk_ids: list[str],
              min_check: int = 10) -> dict:
    allowed = numbers_in(context_text) | numbers_in(question)
    found = numbers_in(answer_text)
    bad_numbers = sorted(n for n in found if n >= min_check and n not in allowed)
    cited = list(dict.fromkeys(CITE.findall(answer_text)))
    bad_cites = [c for c in cited if c not in chunk_ids]
    problems = []
    if bad_numbers:
        problems.append(f"근거에 없는 숫자: {bad_numbers}")
    if bad_cites:
        problems.append(f"조립한 근거에 없는 번호: {bad_cites}")
    if not cited:
        problems.append("근거 번호가 없음")
    return {"ok": not problems, "problems": problems, "numbers": sorted(found),
            "cited": cited, "bad_numbers": bad_numbers, "bad_cites": bad_cites}


def verify(state: State) -> State:
    g = guardrail(state["answer"], state["context"], state["question"], state["chunk_ids"])
    checks = list(state.get("checks", [])) + [{"attempt": state["attempts"], **g}]
    if g["ok"]:
        return {"checks": checks, "problems": [], "route": "answer"}
    return {"checks": checks, "problems": g["problems"]}


def verify_next(state: State) -> str:
    if state.get("route") == "answer":
        return "end"
    return "answer" if state["attempts"] < MAX_ATTEMPTS else "handoff"


def handoff(state: State) -> State:
    if state.get("categories") == ["OTHER"]:
        why = "범위 밖(OTHER)"
    elif state.get("confidence", 1) < CONF_THRESHOLD and not state.get("answer"):
        why = f"확신도 {state.get('confidence'):.2f} < {CONF_THRESHOLD}"
    elif "NO_ANSWER" in state.get("answer", ""):
        why = "근거에 답이 없음"
    else:
        why = "검증 위반이 고쳐지지 않음"
    return {"tools_called": list(state.get("tools_called", [])) + ["handoff"],
            "route": "handoff", "handoff_reason": why, "answer": HANDOFF_MESSAGE}


def build_graph():
    g = StateGraph(State)
    g.add_node("classify", classify)
    g.add_node("retrieve", retrieve)
    g.add_node("answer", answer)
    g.add_node("verify", verify)
    g.add_node("handoff", handoff)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", gate_next, {"retrieve": "retrieve", "handoff": "handoff"})
    g.add_edge("retrieve", "answer")
    g.add_conditional_edges("answer", answer_next, {"verify": "verify", "handoff": "handoff"})
    g.add_conditional_edges("verify", verify_next, {"end": END, "answer": "answer", "handoff": "handoff"})
    g.add_edge("handoff", END)
    return g.compile()


GRAPH = None


def run(question: str) -> State:
    global GRAPH
    if GRAPH is None:
        GRAPH = build_graph()
    return GRAPH.invoke({"question": question})


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "경로우대 추가공제는 몇 살부터 받을 수 있나요?"
    s = run(q)
    print("카테고리:", s["categories"], "확신도:", s["confidence"])
    print("도구:", s["tools_called"])
    print("답변:", s["answer"])
    if s.get("checks"):
        print("검증:", s["checks"][-1])
