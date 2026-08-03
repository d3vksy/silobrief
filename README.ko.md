# siloBrief

[English](README.md)

siloBrief는 검토한 Python 프로젝트 맥락을 Markdown 조사 브리프 한 파일로 만드는 로컬
CLI입니다. 소스가 있는 개발 환경과 인터넷 검색 환경이 분리된 상황을 대상으로 합니다.

현재는 출시 전 개발 단계입니다. v0.1 동작은
[`docs/V0_1_CONTRACT.md`](docs/V0_1_CONTRACT.md)에 고정되어 있습니다.

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

이 fixture에서는 후보 `1`을 선택하고, 추가·제외 입력은 빈 줄로 끝낸 뒤 다섯 필드 그룹을
승인합니다. 전체 미리보기를 확인하고 정확히 `WRITE`를 입력해야 Markdown 파일이 생성됩니다.

## 명령

| 명령 | 동작 |
|---|---|
| `sb setup [PATH]` | 기존 프로젝트에 `.silobrief/` 상태를 만들거나 검증합니다. |
| `sb ignore PATH --as TEXT [--alias NAME]` | 기존 경로를 제외하고 공개용 경계 설명을 등록합니다. |
| `sb init` | 허용된 Python 파일에서 결정적인 구조 index를 만듭니다. |
| `sb log PATH --comment TEXT` | 브리프에 포함될 수 있는 사용자 작성 메모를 저장합니다. |
| `sb chat "PROMPT" --out FILE` | 후보 맥락을 검토하고 승인된 Markdown 한 파일을 만듭니다. |
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

상태 파일은 로컬 구현 데이터이며 외부 전달용 결과가 아닙니다. 생성된 Markdown만 의도한
산출물이며, 이동하기 전에 사람이 전체 내용을 다시 확인해야 합니다.

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
