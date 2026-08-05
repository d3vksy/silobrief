# siloBrief v0.2 기능명세서

- 문서 상태: `FROZEN FOR IMPLEMENTATION`
- 제품 버전: `0.2.0`
- Markdown 계약 버전: `2`
- 작성일: 2026-08-04 (Asia/Seoul)
- 이전 계약: `docs/V0_1_CONTRACT.md`

이 문서는 siloBrief v0.2의 공개 동작과 허용 범위를 고정한다. 사용자 승인 전에는
`FROZEN FOR IMPLEMENTATION`으로 변경하지 않으며, 이 계약을 구현하는 제품 코드도
작성하지 않는다.

v0.2의 목적은 v0.1에서 생성한 브리프에 실제 코드가 없어 외부 AI가 프로젝트 내부
필드, 함수와 제어 흐름을 추측하던 문제를 줄이는 것이다. 이를 위해 사용자가 직접
선택하고 승인한 함수와 클래스의 원문만 별도 Markdown 파일로 내보낸다.

이 기능은 비밀정보 탐지, 자동 마스킹 또는 누출 방지를 보장하지 않는다. 사용자는
모든 원문을 미리 보고 공개 여부를 직접 결정해야 한다.

## 1. 제품 목표와 검증 범위

### 1.1 목표 사용자

공개할 수 없는 일부 코드와 공개 가능한 일반 코드가 섞인 Python 프로젝트를 외부
GPT 또는 Claude에 전달해 유지보수 작업을 수행하려는 개발자를 대상으로 한다.

### 1.2 관찰 가능한 결과

사용자는 `sb chat`에서 실제로 필요한 함수와 클래스를 직접 선택하고 원문을 확인한
뒤 다음 결과물을 만들 수 있다.

```text
retry-brief.md
retry-brief.sources.md
```

두 파일을 외부 AI에 함께 전달했을 때 AI는 공개된 실제 코드에 기반해 수정안과
테스트를 제시해야 한다.

### 1.3 검증의 의미

v0.2의 GO는 공개 합성 fixture에서 승인된 코드 조각이 외부 AI의 답변 적용 가능성을
높였다는 의미로만 사용한다. 시장 수요, 조직 정책 적합성, 보안성과 일반적인 모델
성능이 검증됐다고 표현하지 않는다.

## 2. 버전과 호환성

| 항목 | v0.2 계약 |
|---|---|
| 제품 버전 | `0.2.0` |
| Markdown 계약 버전 | `2` |
| config schema | `1` 유지 |
| index schema | `1` 유지 |
| notes schema | `1` 유지 |
| Python | 3.10 이상 |
| OS | Windows, Ubuntu |
| 런타임 외부 의존성 | 없음 |
| 네트워크·LLM 호출 | 없음 |

- `docs/V0_1_CONTRACT.md`는 수정하지 않는다.
- 기존 `.silobrief/` 상태는 migration 없이 사용할 수 있어야 한다.
- v0.2를 위해 새로운 상태 파일이나 영구 동의 값을 추가하지 않는다.
- Python 라이브러리 API의 호환성은 보장하지 않는다.

## 3. 공개 CLI와 종료 코드

v0.2는 기존 CLI 문법을 변경하지 않는다.

```text
sb setup [PATH]
sb ignore PATH --as TEXT [--alias NAME]
sb init
sb log PATH --comment TEXT
sb chat "PROMPT" --out FILE
sb --version
```

소스 공개를 위한 새 옵션, 자동 승인 옵션과 별도 source 명령을 추가하지 않는다.

| 코드 | 의미 |
|---:|---|
| `0` | 성공 |
| `1` | 예상하지 못한 내부 오류 |
| `2` | 입력, 경로 또는 설정 오류 |
| `3` | 인덱스 또는 Python 파싱 오류 |
| `4` | 공개 범위 검증 실패, 승인 거부 또는 출력 차단 |

## 4. 비무시 소스의 의미

`ignore`하지 않은 파일이 자동으로 외부 공개되는 것은 아니다.

비무시 Python 파일은 다음 두 가지에만 사용될 수 있다.

1. 로컬 구조 분석과 검색 후보 생성
2. 사용자가 직접 선택하고 승인한 함수·클래스 원문 추출

`sb setup` 완료 메시지와 README는 다음 내용을 알려야 한다.

> 무시하지 않은 Python 파일은 분석 대상이 되며, 사용자가 선택하고 승인한 코드
> 조각은 주석, docstring, 문자열과 내부 식별자를 포함한 원문으로 공개될 수 있다.
> siloBrief는 비밀정보 탐지기나 보안 제품이 아니므로 최종 공개 내용을 직접
> 확인해야 한다.

소스 공개의 기본값은 항상 거부다. 비무시 파일 전체, 비무시 모듈 전체 또는 검색
후보 전체를 자동으로 공개하지 않는다.

## 5. 작업 요청 계약

사용자는 기존 위치 인수 `PROMPT`에 다음 정보를 작성해야 한다.

1. 작업 목표
2. 필요한 결과물
3. 완료 조건 또는 acceptance 기준

siloBrief는 자연어의 의미를 자동 판정하지 않는다. `sb chat` 시작 시 다음 체크를 한
번 표시한다.

```text
작업 요청에 다음 내용이 모두 포함되어 있습니까?

- 작업 목표
- 필요한 결과물
- 완료 조건 또는 acceptance 기준

계속하시겠습니까? [y/N]
```

- 소문자 `y`만 계속 진행한다.
- 그 외 입력, EOF와 입력 실패는 코드 `4`로 종료한다.
- 확인하지 않으면 출력 파일을 만들지 않는다.

## 6. `sb chat` 승인 흐름

`sb chat`은 다음 순서를 지킨다.

1. 현재 설정, index와 허용 source digest를 검증한다.
2. 작업 요청 완전성을 `y/N`으로 확인한다.
3. 최대 10개의 lexical 후보와 점수 근거를 표시한다.
4. 사용자가 후보를 직접 선택, 추가 또는 제외한다.
5. 선택 결과에서 허용된 1단계 그래프 확장을 표시한다.
6. 상대 경로, 심볼 이름, 공개 import, 사용자 메모와 경계 alias를 각각 승인받는다.
7. 사용자가 직접 선택한 함수·클래스만 source 공개 후보로 표시한다.
8. 각 source 후보의 전체 원문을 보여주고 `y/N`으로 승인받는다.
9. 승인된 원문에 등록된 경계 참조가 있으면 추가로 `EXPOSE`를 요구한다.
10. main brief와 optional source companion 전체를 미리 보여준다.
11. 사용자가 정확히 `WRITE`를 입력한 경우에만 쓰기를 계속한다.
12. source snapshot을 다시 생성해 preview 시점과 같은지 확인한다.
13. 검증이 끝난 결과 파일만 새로 만든다.

그래프 확장으로 추가된 심볼은 프로젝트 맥락에는 포함할 수 있지만 source 공개 후보가
되지 않는다. 사용자가 직접 선택하거나 정확한 심볼 ID로 추가한 항목만 source 공개
후보가 된다.

기존 UI의 `공개 라이브러리` 표현은 `공개 import`로 변경한다. siloBrief는 import가
표준 라이브러리인지, 외부 의존성인지 또는 어떤 버전인지 추론하지 않는다. 필요한
버전 정보는 사용자가 `PROMPT` 또는 `sb log` 메모로 제공한다.

## 7. Source excerpt 추출 계약

### 7.1 지원하는 정의

다음 Python 정의만 원문으로 공개할 수 있다.

- 일반 함수
- 비동기 함수
- 클래스

다음 항목은 v0.2에서 원문 공개하지 않는다.

- module 전체
- import 문 단독 선택
- 변수 단독 선택
- 그래프 확장으로만 추가된 심볼
- 무시 영역의 심볼
- 안전하게 범위를 계산할 수 없는 심볼

### 7.2 범위 계산

- 함수와 클래스의 decorator가 있으면 첫 decorator 줄부터 포함한다.
- 정의의 마지막 본문 줄까지 포함한다.
- 중첩 정의는 qualified name으로 구분한다.
- 선택한 클래스에 선택한 메서드가 포함되면 클래스 범위만 출력한다.
- 다른 선택 범위가 겹치면 가장 바깥쪽 승인 범위만 출력한다.
- 같은 source 줄을 두 번 출력하지 않는다.
- 각 excerpt에 원본 기준 시작·종료 줄 번호를 기록한다.

### 7.3 원문 보존

승인된 source는 다음 변환만 거친다.

- Python source encoding을 감지한다.
- 출력 encoding을 UTF-8로 통일한다.
- 줄바꿈을 LF로 통일한다.

그 밖의 내용은 그대로 유지한다. 다음 항목을 제거하거나 마스킹하지 않는다.

- 일반 주석
- docstring
- 문자열 리터럴
- URL과 경로 문자열
- 내부 식별자
- 비밀정보처럼 보이는 문자열

encoding 감지, AST 파싱 또는 범위 계산에 실패한 excerpt는 승인 후보에서 제외하고
원인을 표시한다. 일부 excerpt의 실패만으로 다른 정상 excerpt를 제거하지 않는다.
다만 index 기준 source가 변경됐다면 전체 명령을 중단하고 `sb init` 재실행을
안내한다.

### 7.4 용량 제한

한 번의 `sb chat`에서 source 총량은 다음 두 제한을 모두 만족해야 한다.

- 최대 4,000 source lines
- UTF-8 source content 최대 262,144 bytes, 즉 256 KiB

Markdown 제목과 code fence는 이 계산에 포함하지 않는다. 새 excerpt를 추가해 제한을
넘으면 해당 excerpt 전체를 거부하고 현재 누적량을 표시한다. source를 자동으로
자르거나 요약하지 않는다.

## 8. 무시 경계와 `EXPOSE`

### 8.1 계속 유지하는 보장

- `sb ignore`로 등록한 subtree는 열거나 파싱하지 않는다.
- 무시 파일의 본문은 index, 검색어, main brief와 source companion에 포함하지 않는다.
- 무시 영역의 정적 import·call·reference는 기존 boundary placeholder로 처리한다.

### 8.2 허용 파일의 경계 참조

허용 파일의 승인된 원문에 무시 경계를 향하는 정적 참조가 있으면 실제 import 또는
식별자가 source companion에 나타날 수 있다. 원문을 변형하지 않기 때문에 해당 이름만
자동으로 placeholder로 바꾸지 않는다.

이 경우 siloBrief는 다음 순서를 사용한다.

1. 영향을 받는 excerpt와 boundary alias를 표시한다.
2. 실제 식별자가 원문에 포함될 수 있다고 경고한다.
3. 정확한 대문자 `EXPOSE`를 한 번 요구한다.
4. `EXPOSE`가 없으면 영향을 받는 excerpt만 승인 목록에서 제외한다.
5. 영향을 받지 않은 승인 excerpt는 유지한다.

실제 경계 식별자는 `EXPOSE` 후 source companion의 원문 안에서만 나타날 수 있다.
main brief와 disclosure manifest에서 실제 이름을 다시 나열하지 않는다.

정적 분석은 주석과 문자열 안의 경계 이름을 완전히 탐지할 수 없다. 모든 source
preview 전에 다음 의미의 공통 경고를 표시한다.

> 아래 원문에는 자동으로 분류하지 못한 식별자, 경로, URL, 문자열 또는 비밀정보가
> 포함될 수 있습니다. 전체 내용을 직접 확인한 뒤 승인하십시오.

## 9. 출력 파일 계약

### 9.1 이름 파생

다음 명령에서 source가 하나 이상 승인되면:

```text
sb chat "..." --out retry-brief.md
```

다음 두 파일을 만든다.

```text
retry-brief.md
retry-brief.sources.md
```

source가 하나도 승인되지 않으면 `retry-brief.md`만 만든다.

`--out` 값 자체가 `.sources.md`로 끝나면 코드 `2`로 거부한다. main과 companion은 같은
디렉터리에 생성하며 기존 v0.1의 출력 경로 제한을 동일하게 적용한다.

### 9.2 쓰기 전 검증

- 두 대상 중 하나라도 기존 파일이면 전체 쓰기를 차단한다.
- 두 대상 중 하나라도 symbolic link이면 전체 쓰기를 차단한다.
- `WRITE` 전에는 최종 파일이나 임시 출력 파일을 만들지 않는다.
- source가 있으면 두 파일 모두 전체 preview에 포함한다.
- 정확한 `WRITE` 한 번이 현재 preview 전체를 승인한다.
- `WRITE` 후 source 파일 집합과 digest를 다시 검증한다.
- preview 이후 source가 달라졌으면 코드 `4`로 종료하고 아무 출력도 만들지 않는다.

### 9.3 생성과 제한적 rollback

source가 있으면 companion을 exclusive create한 뒤 main을 exclusive create한다. 두 번째
생성이 처리 가능한 오류로 실패하면 이번 명령이 직접 만든 companion만 제거한다.
기존 파일, 경쟁 프로세스가 만든 파일과 소유 여부를 확인할 수 없는 파일은 제거하지
않는다.

siloBrief는 전원 손실, 운영체제 강제 종료 또는 process crash 전체에 대한 파일 시스템
transaction을 보장하지 않는다.

## 10. Main brief Markdown 계약

main brief는 외부 AI가 문서를 요약하지 않고 작업을 수행하도록 한 줄 실행 지시로 시작한다.
source companion이 있으면 파일 이름을 지시에 포함하고, 없으면 이 문서에 공개된 맥락만
사용하라고 명시한다.

다음 필수 섹션을 정확한 순서로 포함한다.

1. `경고와 공개 범위`
2. `작업 요청`
3. `승인된 프로젝트 맥락`
4. `외부 AI 응답 계약`
5. `Disclosure manifest`

내용이 있을 때만 `승인된 프로젝트 맥락` 뒤에 다음 선택 섹션을 순서대로 넣는다.

1. `사용자 작성 메모`
2. `등록된 경계`
3. `소스 동반 파일`

작업 요청을 반복하는 복사용 프롬프트와 사용자용 수동 체크리스트는 외부 AI 입력에 넣지
않는다. 사용자는 대화형 맥락 검토, 전체 preview와 최종 `WRITE` 승인에서 공개 범위를
확인한다.

v0.1의 `조사 질문`과 `추천 검색어` 섹션은 v0.2에서 제거한다.

### 10.1 Main brief 허용 내용

- 사용자가 입력한 작업 요청
- 사용자가 승인한 상대 경로
- 사용자가 승인한 심볼 종류와 이름
- 사용자가 승인한 공개 import
- 사용자가 승인한 사람 작성 메모와 그 출처
- 사용자가 승인한 boundary alias와 공개 설명
- source companion 파일 이름과 사용 안내
- 문서 자체를 실행 요청으로 해석하게 하는 한 줄 지시
- 고정된 외부 AI 응답 계약
- disclosure manifest

main brief에는 source 본문을 넣지 않는다. source companion이 필요한데 외부 AI에
전달되지 않았다면 AI가 숨은 코드를 추측하지 말고 파일 누락을 알리도록 안내한다.

## 11. Source companion Markdown 계약

source companion은 다음 구조를 사용한다.

````text
# Approved source excerpts

이 파일에는 사용자가 외부 공개를 승인한 원문 코드가 포함되어 있습니다.

## `src/example.py` — `function package.example` — lines 10-18

```python
def example() -> None:
    pass
```
````

각 excerpt는 다음 정보만 추가한다.

- 프로젝트 기준 상대 경로
- 심볼 종류
- qualified name
- 시작·종료 줄
- Python code fence
- 승인된 원문

정렬 순서는 상대 경로, 시작 줄, 종료 줄, qualified name 순으로 고정한다. renderer는
절대경로와 Git remote를 추가하지 않는다. 경계 노출이 승인된 경우 실제 이름을 별도
목록으로 반복하지 않고 관련 boundary alias의 승인 상태만 표시한다.

## 12. 외부 AI 응답 계약

main brief에는 특정 과제의 정답이 아닌 다음 범용 규칙을 포함한다.

1. 네 응답 제목을 순서대로 사용하고 별도 서론을 쓰지 않는다.
2. 대상 파일과 변경 목적을 먼저 적고, 공개된 코드와 맥락만 근거로 unified diff를
   작성한다.
3. 집중된 테스트를 제시하되 실행하지 않은 테스트를 통과했다고 표현하지 않는다.
4. 추가 확인은 최대 2개로 제한하고, 외부 API 주장은 가능한 경우 버전이 고정된 공식
   문서 URL로 뒷받침한다. 확인할 내용이 없으면 `없음`이라고 적는다.

작업 요청이 별도로 요구하지 않으면 비어 있지 않은 줄 80개 이내로 답한다.

권장 응답 제목은 다음으로 고정한다.

```text
## 바로 적용할 변경
## 패치
## 테스트
## 확인 필요
```

`패치` 섹션은 다음 형식을 모두 만족해야 한다.

- 하나 이상의 `diff` fenced block만 사용한다.
- 각 파일에 `--- a/상대경로`와 `+++ b/상대경로` header를 쓴다.
- 각 hunk에 `@@` header를 쓴다.
- 삭제 줄은 `-`, 추가 줄은 `+`, 문맥 줄은 공백으로 시작한다.
- 새 파일과 삭제 파일은 해당 header에 `/dev/null`을 사용한다.
- 전체 교체 코드나 diff가 아닌 코드 블록으로 대신하지 않는다.

renderer는 fixture별 정답, 예상 교체 대입문과 숨긴 구현을 prompt에 추가하지 않는다.

## 13. Disclosure manifest schema 2

main brief는 다음 key를 정확히 사용한다.

```yaml
disclosure:
  schema_version: 2
  user_prompt: included
  relative_paths: N
  symbol_names: N
  public_imports: N
  human_notes: N
  human_notes_content: user-supplied-unclassified
  boundary_aliases: N
  source_companion: filename-or-none
  source_excerpts: N
  source_lines: N
  source_utf8_bytes: N
  source_content_mode: verbatim-or-none
  boundary_aliases_exposed_in_source: N
  renderer_added_absolute_paths: 0
  renderer_added_git_remotes: 0
```

`source_lines`와 `source_utf8_bytes`는 정규화된 source content만 계산한다. 겹치는 범위는
한 번만 센다. `boundary_aliases_exposed_in_source`는 실제 이름이 아니라 서로 다른 alias
개수다.

`renderer_added_absolute_paths`와 `renderer_added_git_remotes`는 renderer가 새 값을
추가하지 않았다는 뜻이다. 사용자 원문에 절대경로, remote URL 또는 비밀정보가 없다는
보장이 아니다.

## 14. 안전장치와 비보장 범위

siloBrief가 보장해야 하는 동작:

- 무시 subtree 파일 open과 parse 0회
- source 공개 기본값 거부
- excerpt마다 전체 원문 preview와 명시적 승인
- 경계 참조가 있는 원문에 추가 `EXPOSE` 승인
- 모든 최종 출력에 `WRITE` 승인
- source 변경 시 stale preview 출력 차단
- 기존 source 파일의 실행 전후 SHA-256 불변
- 모든 명령에서 네트워크 연결 시도 0회

siloBrief가 보장하지 않는 동작:

- 사용자 입력과 허용 source의 비밀정보 자동 탐지
- 문자열과 주석 안의 모든 경계 이름 탐지
- 승인한 원문의 안전성 또는 조직 정책 적합성
- 외부 AI 답변의 정확성
- 모든 crash와 전원 손실에 대한 출력 transaction
- 조직 수준 반출 승인, 보안 인증 또는 누출 방지

## 15. v0.2 acceptance criteria

### AC-01 기존 프로젝트 호환성

v0.1 상태 schema와 index schema로 만든 프로젝트에서 migration 없이 v0.2 명령을
실행할 수 있다.

### AC-02 작업 요청 확인

작업 목표, 결과물과 완료 조건 체크에서 `y`가 아닌 값을 입력하면 코드 `4`로 종료하고
출력 파일을 만들지 않는다.

### AC-03 명시적 source 선택

사용자가 직접 선택하거나 정확한 ID로 추가한 함수·클래스만 source 후보가 된다.
module과 그래프 확장 심볼은 source 후보가 되지 않는다.

### AC-04 원문 추출

일반 함수, 비동기 함수, decorator와 클래스의 범위를 정확히 추출하고 UTF-8·LF 외에는
주석, docstring, 문자열과 코드를 변경하지 않는다.

### AC-05 중복과 한도

겹치는 source 범위는 가장 바깥쪽 범위로 한 번만 출력하며, 4,000줄 또는 256 KiB를
넘는 excerpt는 자르지 않고 거부한다.

### AC-06 무시 subtree

무시 subtree의 파일 open과 parse 시도는 0회이며 그 안의 canary는 index, main brief와
source companion 어디에도 나타나지 않는다.

### AC-07 경계 노출 승인

허용 source의 정적 경계 참조는 정확한 `EXPOSE` 없이는 출력되지 않는다. `EXPOSE` 후
실제 식별자는 승인된 source 원문에만 나타날 수 있다.

### AC-08 Main과 companion 분리

source가 승인되면 main과 `.sources.md` 두 파일을 만들고 source 본문은 companion에만
존재한다. source가 없으면 main만 만든다.

### AC-09 출력 안전장치

승인 거부, non-TTY, 기존 파일, symbolic link, source 변경과 정확한 `WRITE` 부재 시
출력 파일을 만들지 않는다.

### AC-10 결정성

같은 프로젝트 상태, 작업 요청과 승인 선택은 Windows와 Ubuntu에서 byte-identical한
UTF-8·LF main과 companion을 만든다.

### AC-11 Renderer 비유출

renderer의 고정 template에는 fixture별 정답과 교체 코드가 없으며 source 본문은 main
brief에 복제되지 않는다.

### AC-12 원본 불변과 오프라인

전체 E2E 실행 전후 `.silobrief/`와 새 출력물을 제외한 기존 프로젝트 파일의 SHA-256이
같고 네트워크 연결 시도는 0회다.

### AC-13 설치 재현

wheel 설치 후 Windows와 Ubuntu의 Python 3.10 이상에서 `setup → ignore → init → log →
chat` 흐름과 paired output을 재현할 수 있다.

## 16. 출시 전 수동 검증 게이트

수동 편집한 packet이 아니라 실제 설치된 `sb`가 생성한 파일만 사용한다.

- 과제별 정답은 `PROMPT`, renderer template과 사용자 메모에 넣지 않는다.
- 고정한 합성 fixture에서 수정, 추가와 제거 유형 과제 3개를 사용한다.
- GPT와 Claude에서 각각 새 채팅을 사용한다.
- source가 승인된 실행은 main과 companion 두 파일만 함께 전달한다.
- 별도의 해설이나 후속 힌트를 제공하지 않는다.

응답은 다음을 만족해야 통과한다.

- 30초 안에 대상 파일과 변경 목적을 파악할 수 있음
- 공개된 실제 필드, 함수와 제어 흐름을 보존함
- 숨긴 구현을 사실처럼 추측하지 않음
- 적용 가능한 unified diff가 있으며 `---`, `+++`, `@@`, 삭제 `-`, 추가 `+` 표기가 있음
- 동작 중심 테스트가 있음
- 실행하지 않은 테스트를 실행했다고 주장하지 않음

GPT와 Claude가 각각 3개 중 2개 이상 통과하고 치명적 비승인 공개가 없을 때만
`v0.2.0` 출시를 진행한다. 어느 한 모델이 0~1개만 통과하거나 무시 영역 내용이
출력되면 출시하지 않는다.

## 17. v0.2에서 하지 않는 것

1. 모든 비무시 파일 또는 module 전체 자동 공개
2. secret scanner, 자동 마스킹과 자동 비식별화
3. LLM 호출, 네트워크 전송과 모델별 API 연동
4. 다국어 UI, `init` progress bar와 ignore 해제 명령
5. 예제 프로젝트 자동 생성과 수정·추가·삭제 학습 모드
6. Python 이외 언어, web UI, plugin과 공개 Python SDK

이 항목들을 위한 미래용 schema, 옵션, 추상화와 빈 확장점을 v0.2 코드에 미리 만들지
않는다.

## 18. 허용·금지 표현

허용하는 설명:

- 사용자가 승인한 코드 조각을 원문으로 내보낸다.
- 등록된 무시 subtree를 읽지 않는다.
- 외부 AI가 실제 공개 코드에 근거하도록 돕는다.
- 합성 fixture에서 답변 적용 가능성을 확인했다.

사용하지 않는 설명:

- 민감정보 누출을 방지한다.
- 안전한 AI 사용을 보장한다.
- 모든 비밀정보를 탐지한다.
- 시장 수요가 검증됐다.
- 모든 프로젝트와 모델에서 효과가 검증됐다.

## 19. 계약 동결 조건

다음 조건을 모두 만족한 후 문서 상태를 `FROZEN FOR IMPLEMENTATION`으로 바꿀 수 있다.

- 사용자가 source 공개 기본값과 원문 보존 범위를 확인함
- 사용자가 경계 참조의 `EXPOSE` 동작을 확인함
- 사용자가 main·companion 두 파일 계약을 확인함
- 사용자가 source 총량 제한을 확인함
- 사용자가 자동 비밀정보 탐지를 제공하지 않는다는 한계를 확인함
- Issue #59와 연결된 계약 PR이 `develop`에 병합됨
