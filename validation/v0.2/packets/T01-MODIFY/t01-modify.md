## 경고와 공개 범위

이 문서는 사용자가 승인한 프로젝트 맥락만 담습니다. 숨긴 구현을 추측하거나 공개 범위를 보안 보장으로 해석하면 안 됩니다.

승인한 source 원문에는 자동으로 분류하지 못한 식별자, 경로, URL, 문자열 또는 비밀정보가 포함될 수 있습니다. siloBrief는 보안 검사나 반출 승인을 보장하지 않으므로 두 파일 전체를 직접 확인해야 합니다.

## 작업 요청

> Update the retry policy in src/parcel_lab/retry.py so status-code retries apply to HTTP 503 and not HTTP 500. Keep total=2 and preserve the delivery boundary call order. Return a minimal patch and focused unittest. Do not claim you ran tests.

## 승인된 프로젝트 맥락

### 상대 경로

- 승인 항목:
  > src/parcel_lab/retry.py

### 심볼

- 승인 항목:
  > module: src.parcel_lab.retry
- 승인 항목:
  > function: retry_request

### 공개 import

- 승인 항목:
  > __future__.annotations
- 승인 항목:
  > parcel_lab.models.Parcel
- 승인 항목:
  > urllib3

## 사용자 작성 메모

- 승인 항목:
  > urllib3 version is 2.7.0.

## 등록된 경계

- 경계 alias:
  > delivery-boundary
  공개 설명:
  > External delivery adapter

## 소스 동반 파일

- 파일: `t01-modify.sources.md`
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
> Update the retry policy in src/parcel_lab/retry.py so status-code retries apply to HTTP 503 and not HTTP 500. Keep total=2 and preserve the delivery boundary call order. Return a minimal patch and focused unittest. Do not claim you ran tests.
> source companion: t01-modify.sources.md
> 숨긴 구현을 추측하지 말고 위 응답 계약을 지키세요.
> 외부 API 사실은 가능한 경우 버전이 고정된 공식 문서 URL로 뒷받침하세요.

## Disclosure manifest

```yaml
disclosure:
  schema_version: 2
  user_prompt: included
  relative_paths: 1
  symbol_names: 2
  public_imports: 3
  human_notes: 1
  human_notes_content: user-supplied-unclassified
  boundary_aliases: 1
  source_companion: "t01-modify.sources.md"
  source_excerpts: 1
  source_lines: 4
  source_utf8_bytes: 154
  source_content_mode: verbatim
  boundary_aliases_exposed_in_source: 1
  renderer_added_absolute_paths: 0
  renderer_added_git_remotes: 0
```

## 수동 확인 체크리스트

- [ ] 작업 요청이 외부에 공개 가능한지 확인했습니다.
- [ ] 승인한 경로·심볼·메모·경계 설명을 확인했습니다.
- [ ] main과 source companion을 함께 전달했습니다.
- [ ] source 원문에 의도하지 않은 정보가 없는지 확인했습니다.
- [ ] 외부 AI가 공개되지 않은 구현을 추측하지 않았는지 확인할 예정입니다.
