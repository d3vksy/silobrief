# siloBrief

[English](README.md)

siloBrief는 검토한 Python 프로젝트 맥락을 Markdown 브리프로 만들고, 명시적으로 승인한
경우 선택한 source excerpt를 동반 파일로 만드는 로컬 CLI입니다. 소스가 있는 개발 환경과
인터넷 검색 환경이 분리된 상황을 대상으로 합니다.

현재 공개 버전은 v0.1.0입니다. 해당 동작은
[`docs/V0_1_CONTRACT.md`](docs/V0_1_CONTRACT.md)에 고정되어 있습니다. `develop` 브랜치는
[`docs/V0_2_CONTRACT.md`](docs/V0_2_CONTRACT.md)에 따른 v0.2 출시 전 개발 단계입니다.

## 요구사항과 설치

- Python 3.10 이상
- Windows 또는 Ubuntu
- 런타임 외부 의존성 없음

현재 checkout을 설치하고 명령을 확인합니다.

```console
python -m pip install .
sb --version
```

예상 출력:

```text
siloBrief 0.1.0
```

## 빠른 시작

합성 프로젝트인
[`parcel-sync-fixture`](examples/parcel-sync-fixture/README.md)를 일회용 위치에 복사합니다.
fixture 루트에서 다음을 실행합니다.

```console
sb setup .
sb ignore private_adapter --as "External delivery adapter" --alias delivery-boundary
sb init
sb log src/parcel_sync/service.py --comment "HTTP 503 responses may be retried."
sb chat "retry request" --out .silobrief/exports/retry-brief.md
```

이 fixture에서는 먼저 요청을 `y`로 확인하고 후보 `1`을 선택합니다. 추가·제외 입력은 빈
줄로 끝내고 다섯 맥락 필드를 승인합니다. 이어서 표시되는 함수 원문을 직접 확인한 뒤에만
`y`를 입력하고, 보이는 경계 식별자는 정확한 `EXPOSE`로 승인합니다. 두 파일의 전체
미리보기를 확인하고 `WRITE`를 입력하면 `retry-brief.md`와 `retry-brief.sources.md`가
생성됩니다. source를 거부하면 main 브리프만 생성됩니다.

## 유용한 입력 작성

`PROMPT`를 짧은 키워드가 아니라 구체적인 작업으로 작성하십시오. 답변에 필요한 산출물과
인수 기준을 함께 적어 결과에 무엇이 포함되어야 하는지 분명히 하십시오.

`sb log`에는 코드 구조만으로 알 수 없고 외부 공개를 승인한 맥락만 기록하십시오. 검토하고
비식별화한 제어 흐름 제약이 한 예입니다. 비공개 source body, 비밀값 또는 무시한 경계의 실제
이름을 메모에 복사하지 마십시오.

무시하지 않은 Python 파일은 로컬 분석 대상입니다. 직접 선택하고 승인한 함수·클래스 조각만
원문으로 공개될 수 있으며 source의 기본값은 거부입니다. 원문에는 주석, docstring, 문자열과
내부 식별자가 포함될 수 있습니다. 경계 참조에는 정확한 `EXPOSE`가 추가로 필요하지만,
siloBrief는 비밀정보를 탐지하지 않으며 결과의 안전성을 보장하지 않습니다. main과 모든
`.sources.md` 동반 파일을 공유 전에 직접 확인하십시오.

## 명령

| 명령 | 동작 |
|---|---|
| `sb setup [PATH]` | 기존 프로젝트에 `.silobrief/` 상태를 만들거나 검증합니다. |
| `sb ignore PATH --as TEXT [--alias NAME]` | 기존 경로를 제외하고 공개용 경계 설명을 등록합니다. |
| `sb init` | 허용된 Python 파일에서 결정적인 구조 index를 만듭니다. |
| `sb log PATH --comment TEXT` | 브리프에 포함될 수 있는 사용자 작성 메모를 저장합니다. |
| `sb chat "PROMPT" --out FILE` | 검토한 main 브리프와 선택적인 `.sources.md` 동반 파일을 만듭니다. |
| `sb --version` | 설치된 siloBrief 버전을 출력합니다. |

`setup` 외 명령은 현재 디렉터리에서 프로젝트 루트를 찾습니다. `chat`에는 대화형 터미널,
현재 설정과 일치하는 index, 새로운 `.md` 출력 경로가 필요합니다. 프로젝트 안의 출력은
`.silobrief/exports/` 아래만 허용되며 기존 파일을 덮어쓰지 않습니다.

## 로컬 상태

```text
.silobrief/
├─ config.json
├─ index.json
├─ notes.json
└─ exports/
```

상태 파일은 로컬 구현 데이터이며 외부 전달용 결과가 아닙니다. 생성된 main 브리프와 선택적인
source 동반 파일만 의도한 산출물이며, 이동하기 전에 사람이 둘 다 전체 확인해야 합니다.

## 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 성공 |
| `1` | 예상하지 못한 내부 오류 |
| `2` | 입력, 경로 또는 설정 오류 |
| `3` | 인덱싱 또는 Python 파싱 오류 |
| `4` | 경계 검증, 승인 또는 출력 차단 |

## 범위와 한계

- 인덱싱은 symbolic link를 따라가지 않고 등록한 제외 subtree를 열지 않습니다.
- 경계 참조는 실제 제외 이름 대신 승인된 alias와 설명으로 저장합니다.
- 네트워크 연결, 언어 모델 또는 자동 전송을 사용하지 않습니다.
- 경로 단위 제외는 허용된 파일 안의 민감한 이름을 판별하지 못합니다.

siloBrief는 보안 검사기, 반출 승인 시스템 또는 정보 누출 방지 보장 도구가 아닙니다.
검색 시간 개선 효과와 사용자 수요도 아직 검증되지 않았습니다.

## 기여

변경은 Issue를 먼저 만들고 `develop` 대상 Pull Request로 제출합니다. 자세한 절차는
[`CONTRIBUTING.md`](CONTRIBUTING.md)를 확인해 주세요.

## 라이선스

Apache License 2.0. 자세한 내용은 [`LICENSE`](LICENSE)를 확인해 주세요.
