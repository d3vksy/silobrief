<p align="center">
  <img src="docs/assets/silobrief-wordmark.svg" alt="siloBrief" width="840">
</p>

---

<p align="center">
  <a href="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml"><img src="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI 상태"></a>
  <a href="https://github.com/d3vksy/silobrief/releases/tag/v0.5.0"><img src="https://img.shields.io/badge/release-v0.5.0-4f46e5" alt="릴리스 v0.5.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10 이상"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache 2.0 라이선스"></a>
</p>

<p align="center">
  <a href="#프로젝트-목표">프로젝트 목표</a> •
  <a href="#설치">설치</a> •
  <a href="#명령어">명령어</a> •
  <a href="#사용법">사용법</a> •
  <a href="#보호-범위와-한계">보호 범위</a> •
  <a href="#문서">문서</a> •
  <a href="README.md">English</a>
</p>

폐쇄망이나 사내 개발 환경에서는 외부 AI가 저장소에 직접 접근할 수 없습니다. 이런 환경에서
AI에게 코드 수정을 요청하려면 관련 코드와 프로젝트 배경을 따로 정리해야 하지만, 저장소 전체를
외부로 넘길 수는 없는 경우가 많습니다.

siloBrief는 **폐쇄 환경의 Python 프로젝트에서 필요한 정보와 공개해도 되는 소스 코드만 골라
AI에 전달할 Markdown 파일로 만드는 로컬 CLI 도구**입니다. 어떤 내용을 넣을지 직접 선택하고,
완성된 파일을 미리 확인한 뒤 조직의 반출 절차에 따라 원하는 AI에 직접 전달합니다.

siloBrief가 AI에 접속하거나 파일을 자동으로 전송하는 일은 없습니다.

- 라이선스: Apache License 2.0
- 지원 운영체제: Windows, Ubuntu
- 지원 Python: 3.10 이상
- 런타임 외부 의존성: 없음

## 프로젝트 목표

siloBrief의 목표는 외부 AI가 직접 접근할 수 없는 프로젝트에서도 저장소를 통째로 넘기지 않고
작업에 필요한 정보를 전달할 수 있게 하는 것입니다.

- 색인을 만들기 전에 읽으면 안 되는 경로를 등록합니다.
- 허용된 Python 파일 안에서 작업과 관련된 함수와 클래스를 찾습니다.
- 포함할 프로젝트 정보와 소스 코드를 사용자가 하나씩 검토합니다.
- 파일을 만들기 전에 전체 내용을 미리 보여줍니다.
- 입력과 선택이 같으면 운영체제와 관계없이 같은 Markdown을 만듭니다.

siloBrief가 만드는 것은 AI에 전달할 입력 자료입니다. 코드 수정안 자체를 만들어 주는 도구는
아닙니다.

## 설치

Python 3.10 이상이 필요합니다. 현재 저장소를 설치한 뒤 명령이 정상적으로 등록됐는지
확인합니다.

```console
python -m pip install .
sb --version
```

다음과 같이 출력되면 설치가 끝난 것입니다.

```text
siloBrief 0.5.0
```

## 명령어

| 명령어 | 설명 |
|---|---|
| `sb setup [PATH]` | 기존 프로젝트에 siloBrief 작업 공간을 만듭니다. |
| `sb example PATH` | 유지보수 과제 3개가 담긴 합성 연습 프로젝트를 만듭니다. |
| `sb ignore PATH --as TEXT [--alias NAME]` | 읽지 않을 경로와 그 영역을 대신할 공개용 이름을 등록합니다. |
| `sb unignore SELECTOR` | 저장된 상대 경로나 별칭으로 등록 경계 하나를 해제합니다. |
| `sb init` | 제외하지 않은 Python 파일을 분석해 로컬 색인을 만듭니다. |
| `sb log PATH --comment TEXT` | 코드만 보고는 알 수 없는 프로젝트 정보를 기록합니다. |
| `sb search "PROMPT"` | 관련 코드 후보를 최대 10개까지 찾고 어떤 요청 단어가 일치했는지 보여줍니다. |
| `sb chat "PROMPT" --out FILE` | 전달할 내용을 검토하고 자족적인 Markdown 파일 하나를 만듭니다. |
| `sb --version` | 설치된 siloBrief 버전을 출력합니다. |

`setup`과 `example`을 제외한 명령은 현재 위치에서 프로젝트 루트를 자동으로 찾습니다. `chat`은
대화형 터미널에서만 실행할 수 있으며, 현재 설정으로 만든 색인과 새로운 `.md` 출력 경로가
필요합니다. 프로젝트 안에 파일을 만들 때는 `.silobrief/exports/` 아래만 사용할 수 있고 기존
파일은 덮어쓰지 않습니다.

## 생성되는 파일

검토가 끝나면 자족적인 Markdown 파일 하나가 만들어집니다.

```text
retry-brief.md  작업 요청, 승인한 프로젝트 정보, 공개를 승인한 소스 코드
```

이 파일 하나를 그대로 AI에 전달하면 됩니다. 소스 코드를 하나도 선택하지 않았다면 같은 파일에
작업 요청과 승인한 프로젝트 정보만 들어갑니다.

저장소에는 검증 이력을 위해
[v0.2의 분리 출력 예시](validation/v0.2/packets/T01-MODIFY/t01-modify.md)도 남겨 두었습니다.

## 사용법

### 연습 프로젝트 만들기

실제 소스 코드를 사용하기 전에 버려도 되는 합성 프로젝트에서 전체 흐름을 연습할 수 있습니다.

```console
sb example ./silobrief-practice
cd silobrief-practice
```

생성된 `README.md`에는 코드 수정, 함수 추가, 오래된 기능 삭제 과제가 하나씩 들어 있습니다.
이 명령은 `setup`이나 색인을 자동으로 실행하지 않고, AI에도 접속하지 않으며, 내용이 있는 기존
디렉터리를 덮어쓰지 않습니다.

### 빠르게 써 보기

먼저 합성 예제 프로젝트인
[`parcel-sync-fixture`](examples/parcel-sync-fixture/README.md)를 작업용 디렉터리에 복사합니다.
복사한 프로젝트의 루트에서 다음 명령을 실행하세요.

```console
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb search "Update retry_request to retry HTTP 503 but not 500."
sb chat "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-brief.md
```

이 과정에서 `setup`은 작업 공간을 만들고, `ignore`는 읽으면 안 되는 경로를 등록합니다. `init`은
나머지 Python 파일을 분석해 색인을 만듭니다. `search`는 공개 검토를 시작하지 않고 관련 코드
후보와 선정 근거를 확인할 때 사용합니다. `chat`은 같은 후보를 보여 준 뒤 실제로 포함할 내용을
직접 선택하게 합니다.

### 등록한 제외 경로 해제하기

잘못 등록했거나 더 이상 제외할 필요가 없는 경계는 저장된 상대 경로나 별칭으로 해제한 뒤 색인을
다시 만듭니다.

```console
sb unignore delivery-boundary
sb init
```

`unignore`는 설정만 바꾸며 해제할 경로의 파일을 열지 않습니다. 기존 색인은 즉시 오래된 상태로
표시되므로 `sb init`이 끝나기 전까지 `sb chat`을 실행할 수 없습니다. 색인을 다시 만들면 해당
경로의 파일이 검토 대상이나 소스 코드 후보로 나타날 수 있습니다.

### 프로젝트 정보 더하기

코드 구조만으로 드러나지 않는 규칙이나 배경 정보가 있다면 `sb log`로 메모를 남길 수 있습니다.
외부에 공개해도 된다고 확인한 내용만 입력하세요.

```console
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-with-note.md
```

`chat`을 실행하면 다음 순서로 진행됩니다.

1. 요청한 작업이 맞는지 확인하고 관련 함수나 클래스를 고릅니다. 추천 후보에 원하는 코드가
   없다면 색인에 있는 Python 파일의 정확한 상대 경로를 입력한 뒤 함수나 클래스를 고릅니다.
2. AI 요청 문서에 넣을 프로젝트 정보를 하나씩 검토합니다.
3. 화면에 표시된 소스 코드를 첨부할지 선택합니다. 기본값은 `아니요`입니다.
4. 제외 영역의 실제 식별자가 노출될 때는 내용을 확인한 뒤 `EXPOSE`를 입력해야 합니다.
5. 생성할 Markdown 파일의 전체 내용을 미리 확인합니다.
6. 문제가 없으면 정확히 `WRITE`를 입력해 파일을 만듭니다.

다른 환경으로 옮기기 전에는 생성된 파일을 직접 열어 마지막으로 확인하세요.

### 좋은 요청을 작성하는 방법

`PROMPT`에는 키워드만 나열하지 말고 구체적인 작업을 적으세요. AI가 무엇을 답해야 하는지
판단할 수 있도록 필요한 결과와 완료 조건도 함께 적는 것이 좋습니다.

`sb log`에는 외부 공개를 승인한 정보만 입력해야 합니다. 비공개 소스 코드, 비밀값 또는
제외 영역의 실제 이름을 프로젝트 메모에 적지 마세요. 소스 코드는 사용자가 직접 선택하고 승인한
경우에만 생성 파일에 원문 그대로 포함됩니다. 기본값은 포함하지 않는 것입니다.

## 용어 정리

| 용어 | 뜻 |
|---|---|
| 자족적인 브리프 | 작업 요청, 승인한 프로젝트 정보, 공개를 승인한 소스 코드가 한데 담긴 `.md` 파일입니다. |
| 제외 경로 | `sb ignore`로 등록한 파일이나 디렉터리입니다. siloBrief는 제외한 디렉터리 아래를 분석하지 않습니다. |
| 제외 영역의 공개용 이름 | 제외 경로의 실제 이름 대신 AI 요청 문서에 표시할 별칭과 설명입니다. 기술 문서에서는 boundary alias라고 부릅니다. |
| 로컬 색인 | 허용된 Python 파일과 그 안의 함수·클래스를 기록한 `.silobrief/index.json` 파일입니다. |
| 프로젝트 메모 | `sb log`로 저장한 정보입니다. `chat`에서 AI 요청 문서에 넣을 후보로 제시됩니다. |

## 보호 범위와 한계

다음 동작은 siloBrief 자체에서 강제합니다.

- 색인을 만들 때 심볼릭 링크를 따라가지 않습니다.
- 등록된 제외 디렉터리 안의 파일을 열지 않습니다.
- 등록을 해제하는 동안 해당 경로의 파일을 열지 않습니다.
- 제외된 코드에 대한 참조는 승인한 공개용 이름으로 바꿔 AI 요청 문서에 표시합니다.
- 파일을 쓰기 전에 전체 미리보기와 사용자 승인을 요구합니다.
- 네트워크 연결, 언어 모델 호출, 자동 파일 전송을 하지 않습니다.

하지만 siloBrief가 정보의 공개 가능 여부를 대신 판단해 주지는 않습니다. 허용된 파일 안의
비밀정보를 탐지하지 못하며, `sb log`에 입력한 문장도 자동으로 정리하거나 검열하지 않습니다.
선택한 소스 코드에는 주석, docstring, 문자열, 내부 식별자가 그대로 포함될 수 있습니다.

siloBrief는 보안 검사기나 폐쇄 환경의 반출 승인 시스템이 아니며, 정보 유출 방지를 보장하지도
않습니다. 생성된 파일은 조직의 반출 규정에 따라 공유하기 전에 반드시 직접 검토하세요.

## 검증 현황

현재 공개 버전은 v0.5.0입니다. `sb search`는 요청과 일치한 단어를 근거로 코드 후보를 최대
10개까지 보여줍니다. `sb chat`은 작업 요청, 승인한 맥락, 승인한 소스 조각을
하나의 자족적인 Markdown 파일로 묶습니다.

Django Ninja, pytest, Jinja 저장소에서 Python 소스를 바꾸거나 네트워크에 연결하지 않고 같은
브리프가 반복 생성되는 것을 확인했습니다. 더 넓은 여섯 과제 lexical 회귀 검사에서는 목표
심볼이 세 과제에서만 Top 10에 들었습니다. 후보 검색은 어디까지나 단어 기반 제안이므로, 놓친
경우에는 정확한 파일 경로를 직접 고르는 과정이 필요합니다. 이 결과가 자동 맥락 완성, 비밀정보
탐지, 반출 승인, 시장 수요, 여러 외부 AI 모델과 실제 비공개 프로젝트에서의 효과를 입증하지는
않습니다.

- [설치 wheel 검증](validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md)
- [수동 모델 평가 절차](validation/v0.2/MANUAL_MODEL_GATE.md)
- [Claude 평가 결과](validation/v0.2/results/CLAUDE_GATE_RESULT.md)

## 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 정상적으로 완료됨 |
| `1` | 예상하지 못한 내부 오류가 발생함 |
| `2` | 입력값, 경로 또는 설정에 문제가 있음 |
| `3` | 색인 생성이나 Python 구문 분석에 실패함 |
| `4` | 제외 영역 검증, 사용자 승인 또는 파일 출력 단계에서 차단됨 |

## 문서

- [v0.2 출력 및 보호 범위 계약(과거 문서)](docs/V0_2_CONTRACT.md)
- [보안 문제 신고 안내](SECURITY.md)

## 기여하기

기여를 환영합니다. Issue나 Pull Request를 만들기 전에 [기여 안내](CONTRIBUTING.md)를 확인해
주세요. 프로젝트에 참여할 때는 [행동강령](CODE_OF_CONDUCT.md)을 따라야 합니다.

## 라이선스

siloBrief는 Apache License 2.0으로 배포됩니다. 자세한 내용은 [`LICENSE`](LICENSE)에서 확인할
수 있습니다.

## 면책 조항

siloBrief는 있는 그대로 제공됩니다. 외부에 전달할 파일을 검토하는 과정을 도와주지만, 해당
정보를 공유할 권한이 있는지 또는 안전한지는 대신 판단하지 않습니다. 프로젝트나 조직의 정보
공개 규칙을 따르고 모든 출력물을 직접 확인하세요.
