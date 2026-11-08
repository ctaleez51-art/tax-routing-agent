"""지표 측정.

1) 채점기 검증: 모범 답안(reference)은 모두 통과, forbid 문장으로 만든 오답은 모두 탈락해야 한다.
2) 평가용 문항을 파이프라인에 흘려 세 지표를 잰다.
   - 분류: 정확도, macro F1, 혼동 행렬 (주 카테고리 = categories[0] 기준)
   - 도구 호출 적절성: 부른 도구 집합 == 기대 도구 집합
   - 답변 적절성: 넘겨야 하는 문항은 넘겼으면 통과, 나머지는 채점기(must 전부 + forbid 없음)
결과는 results/ 폴더에 json과 md로 남는다.

사용법:  python evaluate.py            (채점기 검증 + 전체 평가)
         python evaluate.py --judge-only   (채점기 검증만)
         python evaluate.py --note "바꾼 점"  (기록에 남길 메모)
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

import agent
from context import CATEGORIES
from prompts import GOLDEN, JUDGE_SYSTEM

HERE = Path(__file__).parent
RESULTS = HERE / "results"
JUDGE_MODEL = agent.os.environ.get("JUDGE_MODEL", agent.ANSWER_MODEL)


class Verdict(BaseModel):
    must_ok: list[bool] = Field(description="must 항목마다 충족 여부, 순서대로")
    forbid_hit: list[bool] = Field(description="forbid 항목마다 위반 여부, 순서대로")
    passed: bool
    reason: str = Field(description="한두 문장")


_judge = None


def judge(item: dict, answer_text: str) -> Verdict:
    global _judge
    if _judge is None:
        _judge = init_chat_model(JUDGE_MODEL, model_provider="openai", temperature=0,
                                 timeout=60, max_retries=2).with_structured_output(Verdict)
    body = json.dumps({"question": item["question"], "must": item["must"],
                       "forbid": item["forbid"], "answer": answer_text}, ensure_ascii=False, indent=1)
    v: Verdict = _judge.invoke([("system", JUDGE_SYSTEM), ("human", body)])
    # passed는 모델 말이 아니라 항목별 판정으로 다시 계산한다
    v.passed = all(v.must_ok) and len(v.must_ok) == len(item["must"]) and not any(v.forbid_hit)
    return v


def load(split: str) -> list[dict]:
    return [x for x in json.loads(GOLDEN.read_text(encoding="utf-8")) if x["split"] == split]


def validate_judge(items: list[dict]) -> dict:
    rows = []
    for it in items:
        if not it["reference"]:
            continue
        good = judge(it, it["reference"])
        bad_text = it["forbid"][0] + "."
        bad = judge(it, bad_text)
        rows.append({"id": it["id"], "reference_pass": good.passed, "bad_fail": not bad.passed,
                     "reference_reason": good.reason, "bad_reason": bad.reason})
        print(f"  {it['id']}: 모범답안 {'통과' if good.passed else '탈락'} / 오답 {'탈락' if not bad.passed else '통과(문제)'}")
    ok = all(r["reference_pass"] and r["bad_fail"] for r in rows)
    return {"ok": ok, "rows": rows,
            "reference_pass": sum(r["reference_pass"] for r in rows),
            "bad_fail": sum(r["bad_fail"] for r in rows), "n": len(rows)}


def run_eval(items: list[dict]) -> list[dict]:
    rows = []
    for it in items:
        t0 = time.time()
        try:
            s = agent.run(it["question"])
            err = None
        except Exception as e:  # 한 건 실패로 전체가 멈추지 않게
            s, err = {"categories": ["ERROR"], "tools_called": [], "answer": "", "route": "error"}, repr(e)
        sec = round(time.time() - t0, 1)
        pred = s["categories"][0]
        tool_ok = set(s.get("tools_called", [])) == set(it["tools"])
        expect_handoff = it["tools"] == ["handoff"]
        if expect_handoff:
            ans_ok, why = s.get("route") == "handoff", "넘김" if s.get("route") == "handoff" else "넘기지 않음"
            verdict = None
        elif s.get("route") != "answer":
            ans_ok, why, verdict = False, f"답하지 않음({s.get('handoff_reason', err)})", None
        else:
            v = judge(it, s["answer"])
            ans_ok, why, verdict = v.passed, v.reason, v.model_dump()
        rows.append({
            "id": it["id"], "rag": it.get("rag", ""), "question": it["question"],
            "gold": it["categories"], "pred": s["categories"], "confidence": s.get("confidence"),
            "class_ok": pred == it["categories"][0],
            "expected_tools": it["tools"], "tools_called": s.get("tools_called", []), "tool_ok": tool_ok,
            "route": s.get("route"), "handoff_reason": s.get("handoff_reason"),
            "answer": s.get("answer"), "checks": s.get("checks", []),
            "answer_ok": ans_ok, "judge": verdict, "why": why, "seconds": sec, "error": err,
        })
        mark = lambda b: "O" if b else "X"
        print(f"  {it['id']} 분류{mark(rows[-1]['class_ok'])} 도구{mark(tool_ok)} 답변{mark(ans_ok)} "
              f"{s['categories']} {s.get('tools_called')} {sec}s")
    return rows


def summarize(rows: list[dict]) -> dict:
    y_true = [r["gold"][0] for r in rows]
    y_pred = [r["pred"][0] if r["pred"][0] in CATEGORIES else "OTHER" for r in rows]
    cm = confusion_matrix(y_true, y_pred, labels=CATEGORIES).tolist()
    n = len(rows)
    return {
        "n": n,
        "accuracy": round(accuracy_score(y_true, y_pred), 3),
        "macro_f1": round(f1_score(y_true, y_pred, labels=CATEGORIES, average="macro", zero_division=0), 3),
        "confusion_matrix": {"labels": CATEGORIES, "matrix": cm},
        "tool_score": round(sum(r["tool_ok"] for r in rows) / n, 3),
        "answer_score": round(sum(r["answer_ok"] for r in rows) / n, 3),
        "guardrail_retries": sum(1 for r in rows if len(r["checks"]) > 1),
        "guardrail_blocked": sum(1 for r in rows if r["handoff_reason"] == "검증 위반이 고쳐지지 않음"),
    }


def to_markdown(meta: dict, jv: dict | None, summ: dict, rows: list[dict]) -> str:
    L = [f"# 평가 결과 {meta['time']}", "",
         f"- 메모: {meta['note'] or '-'}",
         f"- 모델: 판정 {meta['router']} / 답변 {meta['answer']} / 채점 {meta['judge']}, 임계값 {meta['threshold']}", ""]
    if jv:
        L += [f"## 채점기 검증", "",
              f"- 모범 답안 통과 {jv['reference_pass']}/{jv['n']}, forbid 오답 탈락 {jv['bad_fail']}/{jv['n']} → {'통과' if jv['ok'] else '문제 있음'}", ""]
    L += ["## 지표", "",
          "| 지표 | 값 |", "|---|---|",
          f"| 분류 정확도 | {summ['accuracy']} |",
          f"| 분류 macro F1 | {summ['macro_f1']} |",
          f"| 도구 호출 적절성 | {summ['tool_score']} |",
          f"| 답변 적절성 | {summ['answer_score']} |",
          f"| 검증 후 재생성 건수 | {summ['guardrail_retries']} |",
          f"| 검증 위반으로 넘긴 건수 | {summ['guardrail_blocked']} |", "",
          "## 혼동 행렬 (행: 정답, 열: 예측)", "",
          "| | " + " | ".join(CATEGORIES) + " |", "|---" * (len(CATEGORIES) + 1) + "|"]
    for lab, row in zip(CATEGORIES, summ["confusion_matrix"]["matrix"]):
        L.append(f"| {lab} | " + " | ".join(map(str, row)) + " |")
    L += ["", "## 문항별", "", "| id | RAG | 분류 | 도구 | 답변 | 예측 | 부른 도구 | 이유 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        o = lambda b: "O" if b else "X"
        L.append(f"| {r['id']} | {r['rag']} | {o(r['class_ok'])} | {o(r['tool_ok'])} | {o(r['answer_ok'])} | "
                 f"{','.join(r['pred'])} | {','.join(r['tools_called'])} | {str(r['why']).replace('|', '/')} |")
    L += ["", "## 틀린 문항 답변", ""]
    for r in rows:
        if not (r["class_ok"] and r["tool_ok"] and r["answer_ok"]):
            L += [f"### {r['id']} {r['question']}", "", f"- 답변: {r['answer']}",
                  f"- 검증: {r['checks'][-1] if r['checks'] else '-'}", f"- 채점: {r['why']}", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge-only", action="store_true")
    ap.add_argument("--skip-judge-check", action="store_true")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    items = load("eval")
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    meta = {"time": stamp, "note": a.note, "router": agent.ROUTER_MODEL, "answer": agent.ANSWER_MODEL,
            "judge": JUDGE_MODEL, "threshold": agent.CONF_THRESHOLD}

    jv = None
    if not a.skip_judge_check:
        print("[1] 채점기 검증")
        jv = validate_judge(items)
        print(f"  → 모범답안 통과 {jv['reference_pass']}/{jv['n']}, 오답 탈락 {jv['bad_fail']}/{jv['n']}")
        if a.judge_only:
            (RESULTS / f"judge-{stamp}.json").write_text(json.dumps(jv, ensure_ascii=False, indent=1), encoding="utf-8")
            return

    print(f"[2] 평가 {len(items)}건")
    rows = run_eval(items)
    summ = summarize(rows)
    print(json.dumps({k: v for k, v in summ.items() if k != "confusion_matrix"}, ensure_ascii=False))

    (RESULTS / f"eval-{stamp}.json").write_text(
        json.dumps({"meta": meta, "judge_check": jv, "summary": summ, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    md = to_markdown(meta, jv, summ, rows)
    (RESULTS / f"eval-{stamp}.md").write_text(md, encoding="utf-8")
    print(f"저장: results/eval-{stamp}.md")


if __name__ == "__main__":
    main()
