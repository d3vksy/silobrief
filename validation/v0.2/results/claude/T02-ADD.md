## 바로 적용할 변경

대상 파일: `src/parcel_lab/labels.py`

- `LabelOptions`에 `separator: str = ""` 필드를 추가합니다. 기본값을 빈 문자열로 두어, 기존에 `separator`를 지정하지 않은 호출자의 출력이 변하지 않도록 합니다.
- `format_label`에서 `options.prefix`와 `options.separator`가 모두 비어 있지 않을 때만 둘 사이에 구분자를 삽입합니다. 그 외의 경우(둘 중 하나라도 빈 문자열)는 기존과 동일하게 `prefix`와 `reference`를 바로 이어 붙입니다.
- `uppercase` 처리 순서는 그대로 유지합니다(문자열 조합 후 마지막에 대문자 변환).

## 패치

```diff
 @dataclass(frozen=True, slots=True)
 class LabelOptions:
     prefix: str
     uppercase: bool = False
+    separator: str = ""
```

```diff
 def format_label(reference: str, options: LabelOptions) -> str:
-    label = f"{options.prefix}{reference}"
+    if options.prefix and options.separator:
+        label = f"{options.prefix}{options.separator}{reference}"
+    else:
+        label = f"{options.prefix}{reference}"
     return label.upper() if options.uppercase else label
```

## 테스트

```python
import unittest
from src.parcel_lab.labels import LabelOptions, format_label


class TestFormatLabelSeparator(unittest.TestCase):
    def test_omitted_separator_keeps_current_output(self):
        opts = LabelOptions(prefix="PKG-")
        self.assertEqual(format_label("123", opts), "PKG-123")

    def test_separator_inserted_when_prefix_and_separator_nonempty(self):
        opts = LabelOptions(prefix="PKG", separator="-")
        self.assertEqual(format_label("123", opts), "PKG-123")

    def test_separator_ignored_when_prefix_empty(self):
        opts = LabelOptions(prefix="", separator="-")
        self.assertEqual(format_label("123", opts), "123")

    def test_separator_ignored_when_separator_empty(self):
        opts = LabelOptions(prefix="PKG", separator="")
        self.assertEqual(format_label("123", opts), "PKG123")

    def test_uppercase_preserved_with_separator(self):
        opts = LabelOptions(prefix="pkg", separator="-", uppercase=True)
        self.assertEqual(format_label("abc", opts), "PKG-ABC")


if __name__ == "__main__":
    unittest.main()
```

이 테스트는 작성만 했고 실제로 실행하지 않았습니다. 통과 여부는 확인되지 않았습니다.

## 확인 필요

- `@dataclass(..., slots=True)` 문법은 Python 3.10 이상에서만 지원됩니다(공식 문서: https://docs.python.org/3.10/library/dataclasses.html — "Changed in version 3.10: Added the `slots` parameter"). 대상 프로젝트의 최소 지원 Python 버전이 3.10 미만이면 이 패치는 그대로 적용 불가합니다.
- 없음
