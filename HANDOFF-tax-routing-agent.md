# HANDOFF — tax-routing-agent

- 처음 쓴 날: 2026-11-04
- 고친 날: 2026-11-08

---

## 1. 무엇인가

- cs-agent 교안 10장 「[실습 프로젝트] 라우팅 에이전트 만들기」 과제. 과제 조건·제출물·루브릭은 [cs-agent/교안정리.md](../cs-agent/교안정리.md) 10장.
- RAG 가이드 챗봇 과제([class/rag-chatbot](../class/rag-chatbot))에서 쓴 인적공제 자료로, 질문을 카테고리별로 나눠 그 카테고리 근거만으로 답하는 라우팅 에이전트를 만든다.
- 설계 문서: [PRD.md](PRD.md)

## 2. 끝난 것

- PRD 초안 작성 (2026-11-04)
- (2026-11-08) PRD의 [결정 필요] 칸을 모두 정함. Claude가 docs/ 복사, data/goldenset.json(평가 22건·예시 5건), context.py·prompts.py·agent.py·evaluate.py·app.py·requirements.txt·.gitignore 작성. Claude는 OpenAI에 접속할 수 없어 가짜 모델로 흐름만 시험했다(그래프·검증·채점 집계가 끝까지 돈다). 실제 모델로는 아직 한 번도 돌리지 않았다.
- (2026-11-08) 사용자가 PC에서 evaluate.py 실행: 기준 실행(results/eval-20261108-1913) 분류 1.0·도구 0.955·답변 0.909, 개선 1(prompts.py 답변 규칙 한 줄 추가, results/eval-20261108-1921) 분류 1.0·도구 1.0·답변 0.955. 채점기 검증 모범답안 18/18 통과·오답 18/18 탈락.
- (2026-11-08) Claude가 app.py를 한 줄 배치(centered)로 고침. 사용자가 데모 화면을 1.png, 2.png로 저장. Claude가 REPORT.md 작성.

## 3. 정한 것

- (2026-11-04) 폴더는 `claudecode` 바로 아래 [tax-routing-agent](.)에 둔다.
- (2026-11-04) 자료: RAG 과제 자료 2개 + 고친곳 8곳 — [PRD.md](PRD.md) 5절
- (2026-11-04) 카테고리 5개(`FAMILY`·`INCOME`·`EXTRA`·`CREDIT`·`OTHER`)와 매핑표 — [PRD.md](PRD.md) 6·7절
- (2026-11-08) 모델: OpenAI 판정 `gpt-5.6-luna`, 답변·채점 `gpt-5.6-terra`로 바꿈(원래 Ollama `qwen3.5:2b`). 제출 시간이 빠듯해서. — [PRD.md](PRD.md) 8절
- (2026-11-08) 제출 마감이 2026-11-08 약 2시간 뒤라서 개선 기록은 시간이 남으면 한 번만 넣는다.
- (2026-11-04) RAG 고정 질문 11개를 모두 평가셋에 넣는다 — [PRD.md](PRD.md) 9절
- (2026-11-04) RAG 챗봇과의 비교는 과제와 별개로 한다 — [personal/diy-wai/HANDOFF.md](../personal/diy-wai/HANDOFF.md) 6절 13번

## 4. 정하지 않은 것

- 없음. [결정 필요] 칸은 2026-11-08에 모두 정했다.

## 5. 환경에서 알아 둘 것

- 이 폴더는 아직 git 저장소가 아니다. git commit/push는 사용자가 PC 터미널에서 한다.
- API 키: agent.py가 이 폴더의 `.env`에서 읽는다. `.env`는 .gitignore에 있다.
- 실행(PC 터미널, 이 폴더에서): `pip install -r requirements.txt` → `python evaluate.py --note "기준 실행"` → 결과는 results/eval-날짜.md. 데모는 `streamlit run app.py`.

## 6. 다음 할 일

1. 사용자가 PC 터미널에서 git init → commit → 깃허브 저장소 tax-routing-agent에 push하고 주소를 제출한다.
2. (제출 뒤) M02(⑪) 실패 개선 — REPORT.md 7절 보완점. cs-agent 교안 실습 6~8장 이어서 하기.
