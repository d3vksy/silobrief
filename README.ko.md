<p align="center">
  <img src=".github/assets/silobrief-wordmark.svg" alt="siloBrief" width="840">
</p>

---

<p align="center">
  <a href="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml"><img src="https://github.com/d3vksy/silobrief/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI 상태"></a>
  <a href="https://github.com/d3vksy/silobrief/releases/tag/v1.0.5"><img src="https://img.shields.io/badge/release-v1.0.5-4f46e5" alt="릴리스 v1.0.5"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776ab" alt="Python 3.10 이상"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache 2.0 라이선스"></a>
</p>

<p align="center">
  <a href="#빠른-시작">빠른 시작</a> •
  <a href="#작동-방식">작동 방식</a> •
  <a href="#명령어">명령어</a> •
  <a href="#보호-범위와-한계">보호 범위</a> •
  <a href="#검증-현황">검증 현황</a> •
  <a href="#보안">보안</a> •
  <a href="README.md">English</a>
</p>

폐쇄망이나 사내 개발 환경에서는 외부 AI가 저장소를 직접 볼 수 없습니다. 작업에 필요한 코드와
프로젝트 정보를 따로 정리해야 합니다.

siloBrief는 허용된 Python 프로젝트 맥락을 정리해 외부 AI에 전달할 Markdown 브리프를 만드는
로컬 CLI입니다. 파일을 쓰기 전에 포함할 정보와 소스를 직접 확인하고 승인합니다. 코드 수정안이
아니라 AI에 전달할 입력 자료를 만듭니다.

- 라이선스: Apache License 2.0
- 지원 운영체제: Windows, Ubuntu
- 지원 Python: 3.10 이상
- 런타임 외부 의존성: 없음
- 네트워크 사용: 없음

WSL에서 실행할 때는 프로젝트를 WSL의 Linux 파일시스템에 두세요. `/mnt/c` 같은 Windows
마운트 경로의 프로젝트는 Windows에서 `sb`를 실행해야 합니다. 기존 항목을 덮어쓰지 않고 상태
파일을 만들 수 없는 마운트에서는 `sb setup`이 중단됩니다.

## 빠른 시작

### 설치

PyPI에서 안정 버전을 설치한 뒤 명령이 정상적으로 등록됐는지 확인합니다.

```console
python -m pip install silobrief
sb --version
```

다음과 같이 출력되면 설치가 끝난 것입니다.

```text
siloBrief 1.0.5
```

### 실습 예제

실습 예제 프로젝트를 생성합니다.

```console
sb example ./silobrief-practice
cd silobrief-practice
```

생성된 `README.md`를 따라 코드 수정, 함수 추가, 오래된 기능 삭제 과제를 하나씩 진행할 수
있습니다.

같은 디렉터리에서 첫 번째 과제를 시작합니다.

```console
sb setup .
sb init
sb log parcel_practice/labels.py --comment "Callers pass uppercase positionally."
sb search "Append an optional separator to format_label. Preserve positional callers and apply uppercase last."
sb brief "Append an optional separator to format_label. Preserve positional callers and apply uppercase last. Return a readable diff and focused unittests." --out .silobrief/exports/task-01-modify.md
```

`setup`은 작업 공간을 준비하고, `init`은 Python 파일을 분석합니다. `log`는 공개를 승인한
프로젝트 정보를 기록합니다. `search`는 관련 코드 후보를 보여 주고, `brief`는 검토를 시작해
Markdown 파일을 만듭니다.

`setup` 도중 작업이 끊겼다면 같은 명령을 다시 실행하세요. 이미 생긴 상태 항목이 프로그램이
만드는 기본값과 정확히 같을 때만 나머지를 이어서 만듭니다. 알 수 없는 항목이나 수정된 항목이
있으면 그대로 두고 오류로 중단합니다.

## 작동 방식

### 읽지 않을 경로 정하기

색인을 만들기 전에 siloBrief가 건너뛸 경로를 등록합니다.

```console
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
```

더 이상 제외할 필요가 없는 경로는 저장된 상대 경로나 별칭으로 해제한 뒤 색인을 다시 만듭니다.

```console
sb unignore delivery-boundary
sb init
```

`unignore`는 대상 경로를 열지 않고 로컬 설정만 바꿉니다. 기존 색인은 즉시 오래된 상태가 되므로
`sb init`이 끝나기 전까지 `sb brief`를 실행할 수 없습니다. 색인을 다시 만들면 해제한 경로의
파일이 검토 후보로 나타날 수 있습니다.

### 프로젝트 정보 더하기

코드만으로 알 수 없는 프로젝트 규칙은 `sb log`로 기록합니다.

```console
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
```

외부 공개를 승인한 정보만 입력하세요. 비공개 소스 코드, 비밀값, 제외 영역의 실제 이름은
프로젝트 메모에 적지 마세요.

### 검토하고 파일 만들기

구체적인 작업을 적어 검토를 시작합니다.

```console
sb brief "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-with-note.md
```

`brief`는 다음 순서로 진행됩니다.

1. 요청한 작업을 확인하고 관련 함수나 클래스를 고릅니다. 추천 후보에 원하는 코드가 없다면
   색인에 있는 Python 파일의 정확한 상대 경로를 입력한 뒤 함수나 클래스를 고릅니다.
2. 한 단계 연관 맥락을 검토하고 추가할 항목에만 `rN` 값을 입력합니다. 빈 입력은 아무것도
   승인하지 않습니다.
3. 브리프에 넣을 프로젝트 정보를 하나씩 검토합니다.
4. 화면에 표시된 소스 코드를 포함할지 선택합니다. 기본값은 `아니요`입니다.
5. 승인할 소스의 본문이나 정의 헤더에 제외 영역의 실제 식별자가 드러나면 내용을 확인한 뒤
   `EXPOSE`를 입력합니다.
6. 완성된 브리프 전체를 미리 확인합니다.
7. 문제가 없으면 `WRITE`를 입력해 파일을 만듭니다.

결과물은 작업 요청, 승인한 프로젝트 정보, 직접 선택하고 승인한 소스 코드가 담긴 Markdown
브리프 하나입니다. 선택한 소스는 원문 그대로 포함됩니다. 소스 코드를 선택하지 않으면 작업
요청과 승인한 프로젝트 정보만 들어갑니다. 다른 환경으로 옮기기 전에 파일을 직접 확인하세요.

### 터미널과 브리프 언어 정하기

터미널과 생성 브리프의 기본 언어는 영어입니다. 설정은 프로젝트별로 저장되며 함께 또는 따로
바꿀 수 있습니다.

```console
sb language --cli ko
sb language --brief en
sb language
```

CLI 설정은 터미널의 고정 안내 문구를 바꿉니다. 브리프 설정은 생성되는 제목과 지시문을
바꿉니다. 작업 요청, 프로젝트 메모, 소스 코드, 경로, 심볼, 식별자는 입력하거나 선택한 원문을
유지합니다. 언어 설정은 색인, 후보 순위, ID, 정렬, 소스 digest에 영향을 주지 않습니다.

### 좋은 요청 작성하기

`PROMPT`에는 키워드만 나열하지 말고 구체적인 작업을 적으세요. 필요한 결과와 완료 조건을 함께
적으면 답변이 작업을 충족했는지 판단하기 쉽습니다.

## 명령어

| 명령어 | 설명 |
|---|---|
| `sb setup [PATH]` | 기존 프로젝트에 siloBrief 작업 공간을 만듭니다. |
| `sb example PATH` | 유지보수 과제 3개가 담긴 합성 연습 프로젝트를 만듭니다. |
| `sb ignore PATH --as TEXT [--alias NAME]` | 읽지 않을 경로와 그 영역을 대신할 공개용 이름을 등록합니다. |
| `sb unignore SELECTOR` | 저장된 상대 경로나 별칭으로 등록 경계 하나를 해제합니다. |
| `sb init` | 제외하지 않은 Python 파일을 분석해 로컬 색인을 만듭니다. |
| `sb log PATH --comment TEXT` | 코드만 보고는 알 수 없는 프로젝트 정보를 기록합니다. |
| `sb search "PROMPT"` | 제한된 수의 관련 코드 후보와 어떤 요청 단어가 일치했는지 보여 줍니다. |
| `sb language [--cli {en,ko}] [--brief {en,ko}]` | 터미널 안내와 생성 브리프의 언어를 각각 설정합니다. |
| `sb brief "PROMPT" --out FILE` | 전달할 내용을 검토하고 Markdown 브리프 하나를 만듭니다. |
| `sb chat "PROMPT" --out FILE` | `sb brief`의 이전 이름으로, 기존 사용자 호환을 위해 남겨 둔 명령입니다. |
| `sb --version` | 설치된 siloBrief 버전을 출력합니다. |

`setup`과 `example`을 제외한 명령은 현재 위치에서 프로젝트 루트를 찾습니다. `brief`는 대화형
터미널, 현재 설정으로 만든 색인, 새로운 `.md` 출력 경로가 필요합니다. 프로젝트 안에 파일을
만들 때는 `.silobrief/exports/` 아래만 사용할 수 있으며 기존 파일은 덮어쓰지 않습니다.

표준 오류가 대화형 터미널이면 `sb init`은 소스 수집, 분석, 색인 생성, 소스 변경 확인, 저장
과정을 한 줄로 표시합니다. 출력을 리디렉션하거나 CI에서 실행하면 진행 표시는 생략하고 완료
메시지만 표준 출력에 기록합니다.

## 보호 범위와 한계

siloBrief는 등록된 제외 경로를 읽지 않고, 색인을 만들 때 심볼릭 링크를 따라가지 않습니다.
제외된 코드에 대한 참조에는 사용자가 승인한 공개용 이름을 씁니다. 브리프를 쓰기 전에는 전체
내용을 미리 확인하고 포함할 소스를 직접 선택합니다.

소스와 상태 파일은 처음 연 프로젝트 루트와 디렉터리 항목에 묶어서 읽고 씁니다. 검토를 시작한
뒤에도 설정, 현재 색인, 승인한 소스 스냅샷, 출력 위치가 같은지 계속 확인합니다. 내용이나
파일시스템 항목이 바뀌면 작업을 중단합니다. 상태 파일과 출력 파일은 기존 항목을 덮어쓰지 않고
만들며, 신뢰할 수 없는 문자를 터미널에 표시할 때는 제어 문자를 이스케이프합니다.

다만 허용된 파일이나 `sb log` 메모에 들어 있는 비밀정보까지 찾아 주지는 않습니다. 승인한 소스
코드에는 주석, docstring, 문자열, 내부 식별자가 포함될 수 있습니다. siloBrief는 보안 검사기나
폐쇄 환경의 반출 승인 시스템이 아닙니다. 생성된 파일은 조직의 반출 규정에 따라 공유하기 전에
직접 검토하세요.

Ubuntu에서 브리프를 안전하게 저장하려면 출력 파일시스템이 `O_TMPFILE`을 지원하고
`/proc/self/fd` 링크를 사용할 수 있어야 합니다. 둘 중 하나라도 사용할 수 없으면 요청한 파일을
만들지 않고 중단합니다. WSL에서 `/mnt/c` 아래 프로젝트를 다룬다면 Windows용 `sb`를 실행하거나
프로젝트와 출력 위치를 WSL의 Linux 파일시스템으로 옮기세요.

## 검증 현황

최신 공개 버전은 v1.0.5이며 1.x 호환성 규칙을 따릅니다. 고정된 검색 벤치마크에서 `sb search`는
12개 과제 중 11개의 기대 심볼을 찾았고 평균 역순위는 72.2%였습니다. 후보 검색은 단어 기반
제안입니다. 원하는 코드를 찾지 못하면 검토 중 정확한 Python 파일 상대 경로를 입력할 수
있습니다.

Django Ninja, pytest, Jinja 저장소에서 Python 소스를 바꾸지 않고 같은 전체 흐름을 반복할 수
있는지 확인했습니다. 벤치마크 규모가 작으므로 다른 AI 모델이나 비공개 프로젝트에서도 같은
효과가 난다고 단정할 수는 없습니다.

- [설치 wheel 검증](validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md)
- [수동 모델 평가 절차](validation/v0.2/MANUAL_MODEL_GATE.md)
- [Claude 평가 결과](validation/v0.2/results/CLAUDE_GATE_RESULT.md)
- [v0.7 검색 결과](validation/v0.7/RETRIEVAL_RESULT.md)
- [v0.8 연관 맥락 결과](validation/v0.8/RELATED_CONTEXT_RESULT.md)
- [1인 현장 시험 절차](validation/v0.9/FIELD_TRIAL.md)
- [v1.0.1 릴리스 검증](validation/v1.0.1/RELEASE_VERIFICATION.md)
- [v1.0 범위 기반 연관 코드 검증](validation/v1.0-scope-related-context/REPORT.md)

## 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 정상적으로 완료됨 |
| `1` | 예상하지 못한 내부 오류가 발생함 |
| `2` | 입력값, 경로 또는 설정에 문제가 있음 |
| `3` | 색인 생성이나 Python 구문 분석에 실패함 |
| `4` | 제외 영역 검증, 사용자 승인 또는 파일 출력 단계에서 차단됨 |

## 보안

취약점 신고 방법은 [보안 정책](SECURITY.md)을 확인하세요.

## 기여하기

기여를 환영합니다. Issue나 Pull Request를 만들기 전에 [기여 안내](CONTRIBUTING.md)를 확인해
주세요. 프로젝트에 참여할 때는 [행동강령](CODE_OF_CONDUCT.md)을 따라야 합니다.

## 라이선스

siloBrief는 Apache License 2.0으로 배포됩니다. 자세한 내용은 [`LICENSE`](LICENSE)에서 확인할
수 있습니다.
