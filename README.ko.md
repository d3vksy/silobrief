# siloBrief

[English](README.md)

siloBrief는 Python 프로젝트에서 공개 가능한 맥락을 골라, 사람이 검토한 Markdown
조사 브리프를 만드는 로컬 CLI입니다. 소스가 있는 개발 환경과 인터넷 검색 환경이
분리된 상황을 대상으로 합니다.

현재는 출시 전 개발 단계입니다. v0.1 동작은
[`docs/V0_1_CONTRACT.md`](docs/V0_1_CONTRACT.md)에 고정되어 있습니다.

현재 개발 빌드는 로컬 설치 후 버전 명령을 제공합니다.

```console
python -m pip install .
sb --version
```

예상 출력:

```text
siloBrief 0.1.0
```

현재 디렉터리 또는 지정한 기존 프로젝트 디렉터리에 로컬 상태를 초기화합니다.

```console
sb setup [PATH]
```

이 명령은 `.silobrief/config.json`, `.silobrief/notes.json`, `.silobrief/exports/`를
만듭니다. 다시 실행하면 기존 상태를 덮어쓰지 않고 호환 여부만 검사합니다.

기존 프로젝트 파일이나 디렉터리를 제외 경계로 등록합니다.

```console
sb ignore PATH --as "공개 가능한 설명" [--alias NAME]
```

프로젝트 루트 또는 하위 디렉터리에서 실행해야 합니다. `PATH`는 현재 디렉터리 기준
상대경로여야 하며 `..`를 포함하거나 symbolic link를 통과할 수 없습니다. 저장 경로는
`/` 구분자를 사용합니다. `--alias`를 생략하면 실제 경로명과 무관한 `boundary-N`이
부여됩니다. 설명은 공개 가능한 문장으로 간주합니다.

경계를 등록한 다음 로컬 소스 인덱스를 생성하거나 갱신합니다.

```console
sb init
```

이 명령은 symbolic link를 따라가지 않고 허용된 Python 파일만 읽습니다. 파싱에 성공하고
소스 snapshot이 바뀌지 않은 경우에만 `.silobrief/index.json`을 교체합니다.

## 범위와 한계

- Python 3.10 이상, Windows와 Ubuntu
- 런타임 외부 의존성, 네트워크, 언어 모델, 자동 전송 없음
- 요청 한 건마다 사람의 명시적 승인 후 Markdown 한 파일 생성
- 경로 단위 제외는 허용된 파일 안의 민감한 이름을 판별하지 못함

siloBrief는 보안 검사기, 반출 승인 시스템 또는 정보 누출 방지 보장 도구가 아닙니다.

## 기여

변경은 Issue를 먼저 만들고 `develop` 대상 Pull Request로 제출합니다. 자세한 절차는
[`CONTRIBUTING.md`](CONTRIBUTING.md)를 확인해 주세요.

## 라이선스

Apache License 2.0. 자세한 내용은 [`LICENSE`](LICENSE)를 확인해 주세요.
