# Approved source excerpts

이 파일에는 사용자가 외부 공개를 승인한 원문 코드가 포함되어 있습니다. 주석, docstring, 문자열, 경로와 내부 식별자를 직접 확인하십시오.

## `src/parcel_lab/cleanup.py` — `function choose_reference` — lines 6-11

Boundary exposure approval: none

```python
def choose_reference(primary: str | None, legacy: str | None) -> str:
    if primary is not None and primary.strip():
        return primary.strip()
    if legacy is not None and legacy.strip():
        return legacy.strip()
    raise ValueError("a tracking reference is required")
```
