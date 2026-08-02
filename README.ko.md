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
만듭니다. 다시 실행하면 기존 상태를 덮어쓰지 않고 호환 여부만 검사합니다. 인덱스는
아직 구현되지 않은 `sb init`에서 생성합니다.

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
