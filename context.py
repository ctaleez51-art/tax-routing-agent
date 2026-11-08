"""문서 쪼개기 · 카테고리별 근거 조립.

- 국세상담 Q&A: `####` 질문 하나가 근거 하나. 번호는 파일 순서대로 QA-001 ~ QA-107.
- 키워드 연말정산: `##` 항목 하나가 근거 하나. 번호는 항목 번호 그대로 KW-006, KW-019 ...
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DOCS = Path(__file__).parent / "docs"
QA_FILE = DOCS / "국세상담-인적공제QnA.md"
KW_FILE = DOCS / "키워드연말정산-인적공제.md"

CATEGORIES = ["FAMILY", "INCOME", "EXTRA", "CREDIT", "OTHER"]
ANSWER_CATEGORIES = ["FAMILY", "INCOME", "EXTRA", "CREDIT"]

# 카테고리 ↔ 문서 매핑표 (PRD 7절)
# QA: 국세상담 Q&A 묶음(## 제목의 앞부분), KW: 키워드 연말정산 항목 번호
MAPPING = {
    "FAMILY": {
        "qa": ["09", "10", "11", "12", "13", "14"],
        "kw": ["19", "23", "24", "28", "31", "34", "39", "63", "84", "98"],
    },
    "INCOME": {
        "qa": ["※"],
        "kw": ["19"],
    },
    "EXTRA": {
        "qa": ["15", "16", "17", "18"],
        "kw": ["06", "42", "63", "71", "89"],
    },
    "CREDIT": {
        "qa": ["06", "33"],
        "kw": ["66", "67", "90", "99"],
    },
    "OTHER": {"qa": [], "kw": []},
}


@dataclass
class Chunk:
    id: str          # QA-006, KW-031
    group: str       # QA 묶음 번호("09", "※") 또는 KW 항목 번호("31")
    title: str       # 사람이 읽는 제목
    text: str        # 본문

    def render(self) -> str:
        return f"[{self.id}] {self.title}\n{self.text.strip()}"


def _qa_group(heading: str) -> str:
    h = heading.strip()
    if h.startswith("※"):
        return "※"
    m = re.match(r"(\d+)", h)
    return m.group(1) if m else h


def load_qa() -> list[Chunk]:
    chunks: list[Chunk] = []
    group, group_title, sub = "", "", ""
    cur_title, cur_lines = None, []

    def flush():
        if cur_title is not None:
            n = len(chunks) + 1
            title = f"{group_title} > " + (f"{sub} > " if sub else "") + cur_title
            chunks.append(Chunk(f"QA-{n:03d}", group, title, "\n".join(cur_lines)))

    for line in QA_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#### "):
            flush()
            cur_title, cur_lines = line[5:].strip(), []
        elif line.startswith("### "):
            flush(); cur_title = None
            sub = line[4:].strip()
        elif line.startswith("## "):
            flush(); cur_title = None
            group_title = line[3:].strip()
            group, sub = _qa_group(group_title), ""
        elif cur_title is not None:
            cur_lines.append(line)
    flush()
    return chunks


def load_kw() -> list[Chunk]:
    chunks: list[Chunk] = []
    cur, lines = None, []

    def flush():
        if cur:
            num = cur.split()[0]
            chunks.append(Chunk(f"KW-{num}", num, cur, "\n".join(lines)))

    for line in KW_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            cur, lines = line[3:].strip(), []
        elif cur:
            lines.append(line)
    flush()
    return chunks


QA = load_qa()
KW = load_kw()
ALL = {c.id: c for c in QA + KW}


def chunks_for(category: str) -> list[Chunk]:
    """카테고리 하나에 매핑된 근거 조각."""
    m = MAPPING[category]
    return [c for c in QA if c.group in m["qa"]] + [c for c in KW if c.group in m["kw"]]


def build_context(categories: list[str]) -> tuple[str, list[str]]:
    """여러 카테고리의 근거를 겹치지 않게 이어 붙인다. (본문, 근거 번호 목록)"""
    seen, parts = [], []
    for cat in categories:
        for c in chunks_for(cat):
            if c.id not in seen:
                seen.append(c.id)
                parts.append(c.render())
    return "\n\n---\n\n".join(parts), seen


if __name__ == "__main__":
    print("QA", len(QA), "KW", len(KW))
    for cat in CATEGORIES:
        text, ids = build_context([cat])
        print(cat, len(ids), "조각", len(text), "글자")
