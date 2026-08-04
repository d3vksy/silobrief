## 경고와 공개 범위

이 문서는 사용자가 승인한 프로젝트 맥락만 담습니다. 숨긴 구현을 추측하거나 공개 범위를 보안 보장으로 해석하면 안 됩니다.

승인한 source 원문에는 자동으로 분류하지 못한 식별자, 경로, URL, 문자열 또는 비밀정보가 포함될 수 있습니다. siloBrief는 보안 검사나 반출 승인을 보장하지 않으므로 두 파일 전체를 직접 확인해야 합니다.

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

## 사용자 작성 메모

- 없음

## 등록된 경계

- 없음

## 소스 동반 파일

- 파일: `t02-add.sources.md`
- main brief와 이 파일을 함께 전달해야 합니다.
- 파일이 누락되면 숨은 코드를 추측하지 말고 누락 사실을 알려야 합니다.

## 외부 AI 응답 계약

1. 긴 서론 없이 적용할 변경부터 제시합니다.
2. 첫 8개 비어 있지 않은 줄 안에 대상 파일과 변경 목적을 표시합니다.
3. 제공된 코드와 공개 맥락만 근거로 patch 또는 교체 코드를 작성합니다.
4. 숨긴 프로젝트 구조·필드·함수·호출 방식을 추측하지 않습니다.
5. 변경 동작을 검증하는 테스트를 함께 제시합니다.
6. 실제 실행하지 않은 테스트를 실행했다고 표현하지 않습니다.
7. 추가 확인은 최대 2개만 적습니다.
8. 외부 API 주장은 가능한 경우 버전 고정 공식 문서를 근거로 합니다.
9. 별도 요구가 없으면 비어 있지 않은 줄 80개 이내로 답합니다.

권장 응답 제목:

```text
## 바로 적용할 변경
## 패치 또는 교체 코드
## 테스트
## 확인 필요
```

## 외부 AI에 전달할 요청

이 요청은 사용자가 두 Markdown 파일과 함께 복사하는 용도입니다. siloBrief는 외부 AI를 호출하거나 전송하지 않습니다.

> 아래 작업을 공개된 프로젝트 맥락과 source만 사용해 수행하세요.
> 작업 요청:
> Add an optional separator: str setting to LabelOptions. Existing callers that omit it must keep current output. When both prefix and separator are non-empty, place the separator between prefix and reference. Preserve uppercase behavior. Return a minimal patch and focused unittests.
> source companion: t02-add.sources.md
> 숨긴 구현을 추측하지 말고 위 응답 계약을 지키세요.
> 외부 API 사실은 가능한 경우 버전이 고정된 공식 문서 URL로 뒷받침하세요.

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

## 수동 확인 체크리스트

- [ ] 작업 요청이 외부에 공개 가능한지 확인했습니다.
- [ ] 승인한 경로·심볼·메모·경계 설명을 확인했습니다.
- [ ] main과 source companion을 함께 전달했습니다.
- [ ] source 원문에 의도하지 않은 정보가 없는지 확인했습니다.
- [ ] 외부 AI가 공개되지 않은 구현을 추측하지 않았는지 확인할 예정입니다.
