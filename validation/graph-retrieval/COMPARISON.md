# Offline retrieval comparison

Status: **complete / both strategies NO-GO / no product change**

이 비교는 [기준선](BASELINE.md)에서 확인한 두 문제를 가장 작은 범위로 나눠 봤다.

- 테스트 코드가 구현 코드보다 높은 점수를 받는다.
- `src/` layout 때문에 테스트의 `silobrief.*` import가 구현 node와 연결되지 않는다.

제품 ranking, index schema, CLI는 건드리지 않았다. 고정된 12개 과제와 통과 기준을 그대로
사용했고, 첫 결과를 확인한 뒤 quota나 관계 순서를 조정하지 않았다.

## 결론

두 전략 모두 제품 반영 기준을 통과하지 못했다.

| 지표 | 기준선 | source-first | bounded graph | 통과 기준 |
|---|---:|---:|---:|---:|
| fixture Hit@10 | 3/3 | 3/3 | 3/3 | 3/3 |
| fixture 직접 recall | 4/4 | 4/4 | 4/4 | 4/4 |
| 전체 Hit@10 | 3/12 | 8/12 | 9/12 | 9/12 이상 |
| 직접 recall | 4/17 | 9/17 | 10/17 | 12/17 이상 |
| 선택·제한 확장 후 recall | 5/17 | 11/17 | 13/17 | 14/17 이상 |
| MRR | 0.2083 | 0.4236 | 0.4319 | 0.50 이상 |
| 불필요한 후보 | 86 | 76 | 76 | 60 이하 |
| 확장 node | 32 | 54 | 93 | 평균 5 이하 |
| 최대 확장 | 4 | 10 | 10 | 과제당 10 이하 |
| boundary·canary 노출 | 0 | 0 | 0 | 0 |

`source-first`는 Hit@10, 직접 recall, context recall, MRR, 불필요한 후보 기준에 실패했다.
`bounded graph`는 Hit@10만 경계값으로 통과했다. 직접 recall은 2개, context recall은 1개,
불필요한 후보는 16개가 기준에 못 미쳤고 평균 확장은 7.75개로 제한을 넘었다.

따라서 이 결과로 source-first ranking이나 GraphRAG를 제품에 넣지 않는다.

## 고정한 전략

### source-first

현재 `rank_candidates`를 바꾸지 않고 corpus만 두 번 나눠 실행했다.

1. `src/` node에서 최대 7개를 뽑는다.
2. 나머지 node에서 최대 3개를 뽑는다.
3. 한쪽 결과가 quota보다 적을 때만 다른 쪽 결과로 최대 10개까지 채운다.
4. 정답이 후보에 있으면 첫 정답을, 없으면 첫 후보를 선택한다.
5. 현재 resolved graph를 한 번 확장하되 최대 10개에서 멈춘다.

### bounded graph

source-first의 최대 10개 후보를 seed로 사용했다.

1. 평가 메모리에서만 `src/`를 뺀 module alias를 만들고 절대·상대 import를 연결한다.
2. 각 seed와 그 seed를 포함하는 class·module을 시작 context로 삼는다.
3. resolved 관계를 최대 2-hop 탐색한다.
4. 관계 우선순위는 `import`, `call`, `reference`, `contains` 순서다.
5. source-first의 source 후보 7개를 유지하고, 도달한 source node로 남은 세 자리를 먼저
   채운다. 그래프 후보가 부족할 때만 기존 후보를 되돌린다.
6. 선택 후 확장도 같은 그래프에서 최대 2-hop·10개로 제한한다.

동률은 거리, 관계 순서, seed 순위, 안정적인 node key 순서로 결정했다. 링크는 현재 review와
같이 양방향으로 보되 boundary placeholder나 unresolved target은 탐색하지 않았다.

## 과제별 결과

각 셀은 `첫 정답 순위 / 직접 recall / context recall / 불필요한 후보 / 확장 수`다. `-`는
상위 10개에 정답이 없다는 뜻이다.

| 과제 | source-first | bounded graph |
|---|---|---|
| T01-MODIFY | 2 / 1/1 / 1/1 / 0 / 1 | 2 / 1/1 / 1/1 / 2 / 2 |
| T02-ADD | 1 / 2/2 / 2/2 / 1 / 2 | 1 / 2/2 / 2/2 / 1 / 1 |
| T03-REMOVE | 1 / 1/1 / 1/1 / 0 / 1 | 1 / 1/1 / 1/1 / 0 / 0 |
| S01-SETUP | - / 0/1 / 0/1 / 10 / 2 | - / 0/1 / 0/1 / 10 / 10 |
| S02-BOUNDARY | 2 / 1/1 / 1/1 / 8 / 6 | 2 / 1/1 / 1/1 / 8 / 10 |
| S03-SOURCES | 1 / 1/2 / 1/2 / 9 / 3 | 1 / 1/2 / 1/2 / 9 / 10 |
| S04-AST | - / 0/2 / 0/2 / 10 / 4 | 10 / 1/2 / 2/2 / 8 / 10 |
| S05-PLACEHOLDER | 3 / 1/3 / 3/3 / 7 / 6 | 3 / 1/3 / 3/3 / 7 / 10 |
| S06-NOTES | 4 / 1/1 / 1/1 / 6 / 4 | 4 / 1/1 / 1/1 / 6 / 10 |
| S07-RANKING | - / 0/1 / 0/1 / 9 / 5 | - / 0/1 / 0/1 / 9 / 10 |
| S08-REVIEW | - / 0/1 / 0/1 / 10 / 10 | - / 0/1 / 0/1 / 10 / 10 |
| S09-OUTPUT | 2 / 1/1 / 1/1 / 6 / 10 | 2 / 1/1 / 1/1 / 6 / 10 |

## 해석

corpus 역할은 중요한 신호였다. source-first만으로 전체 Hit@10이 3개에서 8개로 늘었다.
따라서 기준선 실패를 graph 부족 하나로 설명할 수는 없다. 다만 source 7개 quota에서도
S01, S04, S07, S08은 정답을 찾지 못했고 불필요한 후보가 여전히 76개였다.

src-layout import 연결은 실제로 한 과제를 복구했다. bounded graph에서 S04의
`extract_structures`가 10위에 들어왔고 선택 후 두 정답을 모두 찾았다. 그러나 S01, S07,
S08은 그대로 실패했다. 전체 불필요 후보 수도 줄지 않았다.

가장 큰 반증은 graph가 context recall을 11개에서 13개로 올리는 동안 확장 node를 54개에서
93개로 늘렸다는 점이다. 현재 관계만으로는 필요한 구현을 좁히기보다 주변 node를 많이 붙이는
경향이 강하다. 이 상태에서 hop, 관계 가중치, 요약 계층을 더 추가하면 작은 개선보다 복잡도가
먼저 커질 가능성이 높다.

## 재현성과 판정

- 제품 기준 commit: `3bf110a537246fe53a34c420ae88bbc8f186b8cc`
- 비교 Issue: [#92](https://github.com/d3vksy/silobrief/issues/92)
- Windows: Python 3.14.3
- Ubuntu: WSL Python 3.12.3
- 기존 baseline SHA-256:
  `4c3bd3590b44ae517552f44d2a66f5d33522354d17cea2c9205f070ae19e5bc2`
- 비교 canonical result 크기: 36,229 bytes
- 두 환경의 비교 SHA-256:
  `1fa91085230ec235d8c547ea7382d5a080ba980995f22831f3db26feed848adb`

두 환경에서 기준선·비교 테스트 9개가 모두 통과했고 canonical SHA-256이 같았다.

```text
$env:PYTHONPATH = "src"
python -m tests.test_graph_retrieval_comparison
```

Ubuntu에서는 `PYTHONPATH=src python3 -m tests.test_graph_retrieval_comparison`을 사용한다.

최종 판정은 **NO-GO**다. 같은 12개 과제에서 quota나 관계 순서를 다시 맞추지 않는다. 별도의
제품 검색 Issue를 만들려면 먼저 새 증거와 새 사전 계약이 필요하다. embedding, LLM, vector DB,
community summary는 이번 결과로 정당화되지 않는다.
