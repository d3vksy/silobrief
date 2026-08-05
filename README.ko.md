# siloBrief

[English](README.md)

siloBrief는 Python 개발자가 외부 AI에 전달할 프로젝트 정보와 소스 코드를 직접 고르게
도와주는 로컬 명령줄 도구입니다. 모든 내용을 파일로 쓰기 전에 보여주며, 사용자가 직접
옮길 수 있는 Markdown 파일을 만듭니다.

AI가 저장소에 직접 접근할 수 없고, 일부 프로젝트 경로는 공유 자료에서 제외해야 할 때
사용합니다.

siloBrief는 AI 서비스에 접속하지 않고 파일을 네트워크로 전송하지 않습니다.

## 무엇이 만들어지나요?

개발 작업을 입력하고 siloBrief가 찾은 프로젝트 항목을 검토하면 다음 두 파일이 만들어질 수
있습니다.

```text
retry-brief.md          작업 요청과 승인한 프로젝트 정보
retry-brief.sources.md  사용자가 선택하고 승인한 소스 코드
```

`.sources.md` 파일이 만들어졌다면 두 파일을 함께 AI에 전달합니다. 소스 코드 공개를 모두
거부하면 AI 요청 문서만 만들어집니다.

실제로 생성한 [AI 요청 문서](validation/v0.2/packets/T01-MODIFY/t01-modify.md)와
[코드 첨부 파일](validation/v0.2/packets/T01-MODIFY/t01-modify.sources.md)을 확인할 수 있습니다.

## 어떻게 동작하나요?

1. `setup`이 기존 프로젝트 안에 siloBrief의 로컬 작업 공간을 만듭니다.
2. `ignore`로 siloBrief가 읽으면 안 되는 경로를 등록합니다.
3. `init`이 나머지 Python 파일을 분석해 로컬 검색 목록을 만듭니다.
4. 필요하다면 `log`로 코드 구조만으로 알 수 없는 프로젝트 정보를 기록합니다.
5. `chat`이 관련 함수와 클래스를 찾고, 무엇을 포함할지 사용자에게 묻습니다.
6. 전체 미리보기를 확인하고 정확히 `WRITE`를 입력하면 Markdown 파일을 만듭니다.

생성된 파일은 다른 AI에 전달할 입력 자료입니다. siloBrief가 코드 수정안을 직접 생성하지는
않습니다.

## 설치

요구사항:

- Python 3.10 이상
- Windows 또는 Ubuntu
- 런타임 외부 의존성 없음

현재 저장소를 설치하고 명령을 확인합니다.

```console
python -m pip install .
sb --version
```

예상 출력:

```text
siloBrief 0.2.0
```

## 전체 흐름 체험하기

합성 프로젝트인 [`parcel-sync-fixture`](examples/parcel-sync-fixture/README.md)를 일회용
디렉터리에 복사합니다. 복사한 프로젝트의 최상위 디렉터리에서 다음 명령을 실행합니다.

```console
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "Update retry_request to retry HTTP 503 but not 500. Return a unified diff and tests." --out .silobrief/exports/retry-brief.md
```

`chat` 실행 중에는 다음 순서로 검토합니다.

1. 작업 내용을 확인하고 관련 함수 또는 클래스를 고릅니다.
2. 제안된 프로젝트 정보를 하나씩 확인합니다.
3. 화면에 나온 소스 코드를 포함할지 결정합니다. 기본 선택은 거부입니다.
4. 제외 영역의 실제 식별자가 보이면 내용을 확인한 뒤에만 `EXPOSE`를 입력합니다.
5. AI 요청 문서와 코드 첨부 파일의 전체 미리보기를 확인합니다.
6. `WRITE`를 입력해 파일을 만듭니다.

생성된 두 파일은 다른 환경으로 옮기기 전에 직접 열어 확인하십시오.

## 작업 요청을 잘 작성하는 방법

`PROMPT`에는 짧은 키워드 대신 구체적인 작업을 적습니다. AI 답변에 필요한 결과와 완료 조건도
함께 적어야 어디까지 답해야 하는지 알 수 있습니다.

`sb log`에는 외부 공개를 승인한 정보만 입력합니다. 프로젝트 메모에 비공개 소스 코드,
비밀값 또는 제외 영역의 실제 이름을 적지 마십시오. 사용자가 직접 선택하고 승인한 소스 코드만
코드 첨부 파일에 원문 그대로 포함할 수 있으며, 기본 선택은 거부입니다.

## 이 프로젝트에서 사용하는 용어

| 용어 | 쉬운 설명 |
|---|---|
| AI 요청 문서 | 작업 요청과 승인한 프로젝트 정보가 들어 있는 기본 `.md` 파일입니다. 소스 코드 본문은 들어가지 않습니다. 기술 계약서에서는 main brief라고 부릅니다. |
| 코드 첨부 파일 | 사용자가 선택하고 승인한 소스 코드가 들어 있는 선택적 `.sources.md` 파일입니다. 기술 계약서에서는 source companion이라고 부릅니다. |
| 제외 경로 | `sb ignore`로 등록한 파일 또는 디렉터리입니다. siloBrief는 제외 디렉터리 아래의 파일을 분석하지 않습니다. |
| 제외 영역의 공개용 이름 | 제외 경로의 실제 이름 대신 사용하는 별칭과 설명입니다. 기술 계약서에서는 boundary alias라고 부릅니다. |
| 로컬 검색 목록 | 허용된 Python 파일, 함수와 클래스를 기록한 `.silobrief/index.json`입니다. 기술 계약서에서는 index라고 부릅니다. |
| 프로젝트 메모 | `sb log`로 저장한 사용자 작성 정보입니다. 검토 과정에서 포함 후보로 제시될 수 있습니다. |

## 명령

| 명령 | 하는 일 |
|---|---|
| `sb setup [PATH]` | 기존 프로젝트에 siloBrief의 로컬 작업 공간을 만들거나 확인합니다. |
| `sb ignore PATH --as TEXT [--alias NAME]` | 경로를 제외하고 그 영역을 나타낼 공개용 이름을 저장합니다. |
| `sb init` | 허용된 Python 파일에서 로컬 검색 목록을 만듭니다. |
| `sb log PATH --comment TEXT` | 외부 공개를 승인한 프로젝트 메모를 저장합니다. |
| `sb chat "PROMPT" --out FILE` | 정보를 검토하고 AI 요청 문서와 선택적 코드 첨부 파일을 만듭니다. |
| `sb --version` | 설치된 siloBrief 버전을 출력합니다. |

`setup` 외 명령은 현재 디렉터리에서 프로젝트 최상위 디렉터리를 찾습니다. `chat`을 사용하려면
대화형 터미널, 현재 설정과 일치하는 검색 목록, 새로운 `.md` 출력 경로가 필요합니다. 프로젝트 안에
출력할 때는 `.silobrief/exports/` 아래만 사용할 수 있습니다. 기존 파일은 덮어쓰지 않습니다.

## 보호하는 범위와 보호하지 않는 범위

siloBrief는 다음 원칙을 지킵니다.

- 색인을 만들 때 심볼릭 링크를 따라가지 않습니다.
- 등록된 제외 디렉터리를 열지 않습니다.
- AI 요청 문서에서는 제외 코드에 대한 참조를 승인된 공개용 이름으로 바꿉니다.
- 파일을 쓰기 전에 전체 미리보기와 승인을 요구합니다.
- 네트워크, 언어 모델, 자동 전송 기능을 사용하지 않습니다.

siloBrief는 허용된 파일 안의 비밀정보를 탐지하지 못하고 `sb log`에 입력한 문장을 정리해 주지도
않습니다. 승인한 소스 코드에는 주석, docstring, 문자열과 내부 식별자가 포함될 수 있습니다.
siloBrief는 보안 검사기, 조직의 반출 승인 시스템 또는 정보 노출 방지 보장 도구가 아닙니다.
모든 생성 파일을 공유 전에 직접 확인하십시오.

## 현재까지 확인한 결과

현재 공개 버전은 v0.2.0입니다. 같은 패키지가 Windows와 Ubuntu에서 동일한 Markdown 파일을
생성했고, Claude는 해당 파일로 예제 코드 유지보수 과제 3개를 완료했습니다.
GPT 검증은 후속 과제입니다. 여러 모델, 실제 비공개 프로젝트 또는 독립 사용자를 대상으로 한
효과가 검증된 것은 아닙니다.

- [설치 wheel 검증](validation/v0.2/INSTALLED_WHEEL_VERIFICATION.md)
- [수동 모델 평가 절차](validation/v0.2/MANUAL_MODEL_GATE.md)
- [Claude 평가 결과](validation/v0.2/results/CLAUDE_GATE_RESULT.md)

## 기술 문서

- [v0.2 동작 계약](docs/V0_2_CONTRACT.md)
- [기여 안내](CONTRIBUTING.md)
- [보안 문제 신고 안내](SECURITY.md)

## 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 성공 |
| `1` | 예상하지 못한 내부 오류 |
| `2` | 입력, 경로 또는 설정 오류 |
| `3` | 색인 생성 또는 Python 구문 분석 오류 |
| `4` | 제외 영역 검증, 승인 또는 출력이 차단됨 |

## 라이선스

Apache License 2.0. 자세한 내용은 [`LICENSE`](LICENSE)를 확인해 주세요.
