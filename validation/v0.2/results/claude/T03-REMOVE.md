## 바로 적용할 변경
파일: `src/parcel_lab/cleanup.py`
목적: `choose_reference`에서 `legacy` 폴백 인자와 해당 분기를 제거하고, `primary` 하나만 받아 strip된 값을 반환하거나 공백/None일 때 `ValueError`를 발생시키도록 단순화합니다.

## 패치
```diff
-def choose_reference(primary: str | None, legacy: str | None) -> str:
+def choose_reference(primary: str | None) -> str:
     if primary is not None and primary.strip():
         return primary.strip()
-    if legacy is not None and legacy.strip():
-        return legacy.strip()
     raise ValueError("a tracking reference is required")
```

인터페이스 영향: 매개변수가 `(primary, legacy)` 2개에서 `(primary,)` 1개로 줄어듭니다. `legacy`를 위치 또는 키워드 인자로 넘기던 기존 호출부가 있다면 `TypeError`가 발생합니다. 공개된 맥락에는 호출부 정보가 없으므로 실제 호출부의 존재나 위치는 추정하지 않습니다.

## 테스트
```python
import unittest

from src.parcel_lab.cleanup import choose_reference


class ChooseReferenceTests(unittest.TestCase):
    def test_returns_stripped_primary(self):
        self.assertEqual(choose_reference("  abc123  "), "abc123")

    def test_raises_on_none(self):
        with self.assertRaises(ValueError):
            choose_reference(None)

    def test_raises_on_blank_string(self):
        with self.assertRaises(ValueError):
            choose_reference("   ")


if __name__ == "__main__":
    unittest.main()
```

이 테스트는 실행하지 않았으므로 통과 여부를 주장하지 않습니다.

## 확인 필요
1. `legacy` 인자를 전달하는 기존 호출부가 존재하는지 — 공개 범위에 호출부가 없어 확인이 필요합니다.
2. 없음
