# Graph retrieval baseline

Status: **baseline complete / offline comparison only / product change NO-GO**

이 기준선의 목적은 GraphRAG 기능을 정당화하는 것이 아니라, 현재 lexical ranking과 1-hop
확장이 실제 유지보수 요청에서 무엇을 놓치는지 확인하는 것이다. 측정 결과는 개선 실험을
계속할 근거는 되지만, 지금 바로 제품 ranking이나 index schema를 바꿀 근거는 되지 않는다.

## 결과 요약

| 지표 | 현재 기준선 |
|---|---:|
| Hit@10 | 3/12 (25.0%) |
| Mean reciprocal rank | 0.2083 |
| 상위 10개 기대 심볼 recall | 4/17 (23.5%) |
| 선택 및 1-hop 확장 후 기대 심볼 recall | 5/17 (29.4%) |
| 불필요한 상위 후보 | 86개, 과제당 평균 7.17개 |
| 선택 후 확장 노드 | 총 32개, 평균 2.67개, 최대 4개 |
| 상위 후보에서 resolved 2-hop 이내인 기대 심볼 | 9/17 (52.9%) |
| boundary 실제 값 또는 canary 노출 | 0건 |

Hit@10은 기대 심볼이 상위 10개 안에 하나라도 있는 과제 수다. Mean reciprocal rank는 기대
심볼이 앞에 나올수록 높아지며 1.0이 최댓값이다. Recall은 전체 기대 심볼 중 실제로 찾은
비율이다.

공개 fixture의 세 과제는 모두 통과했지만, siloBrief의 과거 Issue에서 만든 아홉 과제는
기대 구현 심볼이 하나도 상위 10개에 들지 않았다. 요구사항 문구를 그대로 포함한 테스트
함수가 구현 코드보다 높은 점수를 받는 것이 가장 큰 원인이었다.

## 동결 범위

- 제품 기준 commit: `41c0c0030d047bc306d77c15245f7d7c485ff00c`
- 기준선 Issue: [#90](https://github.com/d3vksy/silobrief/issues/90)
- 실행 환경: Windows Python 3.14.3, WSL Ubuntu Python 3.12.3
- repository corpus: 45개 Python 파일, 598개 node, 7,441개 edge
- repository source digest:
  `04201562756532286b42536aadf13abe1efc38881fcedf56289017584a627069`
- fixture corpus: 5개 Python 파일, 10개 node, 38개 edge
- fixture source digest:
  `39bad3c745e233443def7665189d5518d48852bc5b1d2857b3ddb5970ed5568f`
- canonical result SHA-256:
  `4c3bd3590b44ae517552f44d2a66f5d33522354d17cea2c9205f070ae19e5bc2`

두 실행 환경에서 새 기준선 테스트 3개가 통과했고 canonical result SHA-256도 같았다.

repository corpus에서는 `examples/`, `validation/`과 기준선 실행기 자체를 제외했다. 제품
소스와 일반 테스트는 함께 포함했다. fixture corpus에서는 `private_adapter/`를 등록된
boundary로 제외했다.

## 고정 과제

| ID | 변경 | 기대 구현 | 근거 |
|---|---|---|---|
| T01-MODIFY | 수정 | `retry.py:retry_request` | v0.2 T01 |
| T02-ADD | 추가 | `labels.py:LabelOptions`, `format_label` | v0.2 T02 |
| T03-REMOVE | 삭제 | `cleanup.py:choose_reference` | v0.2 T03 |
| S01-SETUP | 추가 | `state.py:setup_project` | Issue #5, `c1933bf` |
| S02-BOUNDARY | 추가 | `boundaries.py:register_boundary` | Issue #7, `b7622c8` |
| S03-SOURCES | 추가 | `sources.py:snapshot_sources`, `compare_snapshots` | Issue #9, `40fc7af` |
| S04-AST | 추가 | `python_structure.py:extract_structures`, `extract_module_structure` | Issue #11, `75fbbb6` |
| S05-PLACEHOLDER | 추가 | `BoundaryMatcher`와 공개 match 메서드 | Issue #15, `b4ab6c3` |
| S06-NOTES | 추가 | `notes.py:add_note` | Issue #17, `dbeec78` |
| S07-RANKING | 추가 | `ranking.py:rank_candidates` | Issue #19, `18bafc4` |
| S08-REVIEW | 추가 | `review.py:review_selection` | Issue #21, `f389ef3` |
| S09-OUTPUT | 추가 | `output.py:approve_and_write` | Issue #25, `6e1ca1e` |

각 과제의 전체 요청 문장, 기대 심볼과 허용 가능한 보조 심볼은
`tests/test_graph_retrieval_baseline.py`에 고정했다. 과거 Issue 제목만 흉내 낸 것이 아니라,
각 merge commit에서 실제로 추가된 현재 심볼을 정답으로 사용했다.

## 측정 계약

1. 현재 `rank_candidates`가 반환하는 최대 10개를 순위 후보로 사용한다.
2. 기대 심볼이 후보에 있으면 가장 높은 기대 심볼 하나를 선택한다.
3. 기대 심볼이 하나도 없으면 1위 후보 하나를 선택한다.
4. 현재 `review_selection`으로 resolved 내부 edge를 정확히 1-hop 확장한다.
5. 불필요한 후보는 기대 심볼과 과제별 허용 보조 심볼에 모두 속하지 않는 후보다.
6. 2-hop 도달성은 상위 10개 전체를 seed로 삼은 진단값이다. 제품 결과에는 사용하지 않는다.
7. `target_id`가 없는 외부 참조와 boundary placeholder는 탐색하지 않는다.

선택 규칙은 사람이 임의로 좋은 후보를 고르는 편차를 제거하기 위한 것이다. 기대 심볼이
이미 검색된 경우에는 정답을 선택하므로, 1-hop context recall은 실제 사용자보다 낙관적일 수
있다.

## 과제별 원시 비교

`순위`가 `-`이면 기대 심볼이 상위 10개에 없다는 뜻이다.

| ID | 첫 기대 순위 | 직접 recall | 1-hop context recall | 불필요 후보 | 확장 수 | 2-hop 도달 |
|---|---:|---:|---:|---:|---:|---:|
| T01-MODIFY | 2 | 1/1 | 1/1 | 0 | 1 | 1/1 |
| T02-ADD | 1 | 2/2 | 2/2 | 1 | 2 | 2/2 |
| T03-REMOVE | 1 | 1/1 | 1/1 | 0 | 1 | 1/1 |
| S01-SETUP | - | 0/1 | 0/1 | 10 | 3 | 0/1 |
| S02-BOUNDARY | - | 0/1 | 0/1 | 10 | 4 | 0/1 |
| S03-SOURCES | - | 0/2 | 0/2 | 10 | 1 | 0/2 |
| S04-AST | - | 0/2 | 0/2 | 10 | 3 | 0/2 |
| S05-PLACEHOLDER | - | 0/3 | 0/3 | 9 | 3 | 3/3 |
| S06-NOTES | - | 0/1 | 1/1 | 7 | 2 | 1/1 |
| S07-RANKING | - | 0/1 | 0/1 | 9 | 4 | 1/1 |
| S08-REVIEW | - | 0/1 | 0/1 | 10 | 4 | 0/1 |
| S09-OUTPUT | - | 0/1 | 0/1 | 10 | 4 | 0/1 |

## 관찰과 해석

### 1. 테스트가 구현보다 높은 점수를 받는다

S01~S05와 S07~S09에서는 acceptance 문구를 긴 함수명으로 가진 테스트가 상위 후보를
대부분 차지했다. 저장소 과제의 상위 후보 90개 중 74개가 `tests/`, 16개가 `src/`였다.
현재 점수는 요청 token과 많이 겹칠수록 올라가므로, 짧고 명확한 제품 함수보다 요구사항을
설명하는 테스트 함수가 유리하다. S06만 같은 제품 파일의 `_note_id`가 1위였고, 이 node의
1-hop에서 `add_note`를 찾았다.

### 2. 현재 graph는 테스트에서 구현으로 돌아가지 못한다

예를 들어 테스트는 `silobrief.cli.main`을 import하지만 src-layout module node는
`src.silobrief.cli`로 기록된다. 이 import edge는 unresolved 상태가 되어 테스트 node에서 제품
node로 확장할 수 없다. 실제로 `tests/`에서 `silobrief.*`로 향한 import edge 144개가 모두
unresolved였고, 서로 다른 target은 73개였다. 단순히 hop 수나 degree 보너스만 늘려서는 이
연결 부재를 해결하지 못한다.

### 3. 무제한 확장은 아직 문제가 되지 않았지만 구조적 위험은 남아 있다

12개 선택에서 실제 1-hop 확장은 최대 4개였다. 반면 repository graph 전체의 최대 resolved
degree는 33개다. 따라서 이번 과제에서 확장 폭발은 재현되지 않았지만, 선택 node가 달라지면
현재의 무제한 1-hop 계약이 많은 문맥을 추가할 수 있다. fixture의 최대 degree는 2개였다.

### 4. 시간은 현재 병목이 아니다

각 과제를 201회 실행한 참고 측정에서 task별 ranking 중앙값의 중앙값은 2.059ms였고 최대는
4.366ms였다. 이 값은 한 Windows PC의 참고값이며 통과 기준이나 시간 기반 테스트로 사용하지
않는다.

## 가장 큰 반증과 한계

- 같은 저장소 과제에서 `tests/`만 제외한 진단 실행은 Hit@10 7/9, 직접 recall 10/13,
  mean reciprocal rank 0.3105를 기록했다. 기본 corpus의 0/9와 0/13보다 크게 높다. 따라서
  현재 실패를 graph 부족만으로 설명할 수 없고, corpus scoping이 더 작은 해결책일 수 있다.
  이 ablation은 고정 기준선 점수에 합산하지 않았다. 테스트도 유지보수에 필요한 맥락이므로
  제품에서 무조건 제외하는 결론도 내리지 않는다.
- 공개 fixture 3개는 모두 통과했다. 작고 요청에 심볼명이 포함된 프로젝트에서는 현재 방식도
  충분할 수 있다.
- siloBrief가 자기 과거 Issue를 검색하는 작은 단일 저장소 실험이다. 다른 프로젝트나 일반
  사용자 효과를 대표하지 않는다.
- 원래 한국어 Issue를 영어로 축약했다. 현재 tokenizer가 번역하지 않으므로 언어 차이와 graph
  품질을 한 실험에 섞지 않기 위한 선택이지만, 실제 한국어 사용 흐름은 검증하지 않았다.
- 테스트를 corpus에 포함했기 때문에 테스트가 없는 배포 소스만 분석할 때보다 불리하다. 반대로
  유지보수 작업에서는 테스트도 필요한 맥락이므로 단순 제외가 정답이라고 볼 수 없다.
- 기대 심볼이 이미 후보에 있으면 그것을 선택하는 규칙 때문에 1-hop 결과는 낙관적이다.
- source digest는 위 commit의 기준선 비교용이다. 후속 소스 변경 후에는 새 결과를 별도로
  기록해야 하며 이 수치를 조용히 덮어쓰지 않는다.

## 다음 실험의 GO/NO-GO

현재 상태에서는 제품 ranking, CLI, index schema 또는 Markdown 계약 변경을 승인하지 않는다.
다음 단계로 허용하는 것은 같은 12개 과제를 사용하는 **오프라인 알고리즘 비교 한 번**뿐이다.

후보 방식은 다음을 모두 만족해야 제품 Issue로 승격한다.

- 공개 fixture Hit@10 3/3과 기대 심볼 4/4를 유지한다.
- 전체 Hit@10이 9/12 이상이다.
- 직접 기대 심볼 recall이 12/17 이상이다.
- 선택·제한된 확장 후 기대 심볼 recall이 14/17 이상이다.
- mean reciprocal rank가 0.50 이상이다.
- 불필요한 상위 후보가 총 60개 이하이다.
- 과제별 확장은 최대 10개, 전체 평균 5개 이하이다.
- boundary 실제 값·canary 노출과 boundary placeholder 탐색이 0건이다.
- 같은 입력의 결과가 byte 단위로 결정적이다.

하나라도 실패하면 GraphRAG 기능을 제품에 넣지 않는다. 다음 비교에는 source/test corpus
scoping을 최소 대안으로 반드시 포함한다. graph 후보는 src-layout import 해석을 바로잡고
query와 관계 종류를 함께 보는 제한된 2-hop 점수까지만 허용한다. embedding, LLM, community
summary, vector DB는 이 기준선의 다음 단계가 아니다.

## 재현

제품을 수정하지 않고 기준선 JSON을 출력한다. Windows PowerShell에서는 다음을 실행한다.

```text
$env:PYTHONPATH = "src"
python tests/test_graph_retrieval_baseline.py
```

Ubuntu에서는 `PYTHONPATH=src python tests/test_graph_retrieval_baseline.py`를 사용한다.
결정성, 정답 추적과 boundary/canary 조건은 전체 테스트에도 포함된다.

```text
$env:PYTHONPATH = "src"
python -m unittest tests.test_graph_retrieval_baseline -v
```
