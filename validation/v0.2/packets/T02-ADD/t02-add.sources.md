# Approved source excerpts

이 파일에는 사용자가 외부 공개를 승인한 원문 코드가 포함되어 있습니다. 주석, docstring, 문자열, 경로와 내부 식별자를 직접 확인하십시오.

## `src/parcel_lab/labels.py` — `class LabelOptions` — lines 8-11

Boundary exposure approval: none

```python
@dataclass(frozen=True, slots=True)
class LabelOptions:
    prefix: str
    uppercase: bool = False
```

## `src/parcel_lab/labels.py` — `function format_label` — lines 14-16

Boundary exposure approval: none

```python
def format_label(reference: str, options: LabelOptions) -> str:
    label = f"{options.prefix}{reference}"
    return label.upper() if options.uppercase else label
```
