> 이 문서와 동반된 `t02-add.sources.md` 파일만 사용하여 아래 작업을 수행하고, 적용 가능한 변경 코드와 테스트를 제시하세요.

## 경고와 공개 범위

승인된 source의 민감정보를 자동으로 탐지하거나 반출 안전성을 보장하지 않습니다. 전달 전에 모든 출력 파일을 직접 확인하세요.

## 작업 요청

> Add an optional separator: str setting to LabelOptions. Existing callers that omit it must keep current output. When both prefix and separator are non-empty, place the separator between prefix and reference. Preserve uppercase behavior. Return a minimal patch and focused unittests.

## 승인된 프로젝트 맥락

### 상대 경로

- 승인 항목:
  > src/parcel_lab/labels.py

### 심볼

- 승인 항목:
  > module: src.parcel_lab.labels
- 승인 항목:
  > class: LabelOptions
- 승인 항목:
  > function: format_label

### 공개 import

- 승인 항목:
  > __future__.annotations
- 승인 항목:
  > dataclasses.dataclass

## 소스 동반 파일

- 파일: `t02-add.sources.md`
- main brief와 이 파일을 함께 전달해야 합니다.

## 외부 AI 응답 계약

다음 네 제목을 순서대로 사용하고, 별도 서론은 쓰지 마세요.

```text
## 바로 적용할 변경
## 패치 또는 교체 코드
## 테스트
## 확인 필요
```

- `바로 적용할 변경`에 대상 파일과 변경 목적을 먼저 적으세요.
- 공개된 코드와 맥락만 근거로 작성하고 숨긴 구현을 추측하지 마세요.
- 집중된 테스트를 제시하되, 실행하지 않았다면 통과했다고 표현하지 마세요.
- `확인 필요`는 최대 2개로 제한하고, 외부 API 주장은 가능한 경우 버전이 고정된 공식 문서 URL로 뒷받침하세요. 확인할 내용이 없으면 `없음`이라고 적으세요.
- 별도 요구가 없으면 비어 있지 않은 줄 80개 이내로 답하세요.

## Disclosure manifest

```yaml
disclosure:
  schema_version: 2
  user_prompt: included
  relative_paths: 1
  symbol_names: 3
  public_imports: 2
  human_notes: 0
  human_notes_content: user-supplied-unclassified
  boundary_aliases: 0
  source_companion: "t02-add.sources.md"
  source_excerpts: 2
  source_lines: 7
  source_utf8_bytes: 264
  source_content_mode: verbatim
  boundary_aliases_exposed_in_source: 0
  renderer_added_absolute_paths: 0
  renderer_added_git_remotes: 0
```
