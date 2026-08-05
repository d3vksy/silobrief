## 바로 적용할 변경
- 대상 파일: `src/parcel_lab/retry.py`
- 목적: `retry_request` 내 `urllib3.Retry` 생성 시 상태코드 재시도 대상을 503으로 한정하고 500은 재시도 대상에서 제외. `total=2`와 `deliver_internal(parcel, retry_policy)` 호출 순서는 그대로 유지.

## 패치

```diff
--- a/src/parcel_lab/retry.py
+++ b/src/parcel_lab/retry.py
@@
 def retry_request(parcel: Parcel) -> object:
-    retry_policy = urllib3.Retry(total=2)
+    retry_policy = urllib3.Retry(total=2, status_forcelist=[503])
     deliver_internal(parcel, retry_policy)
     return retry_policy
```

## 테스트

실행하지 않았습니다. 아래 테스트는 제시만 하며 통과 여부는 확인되지 않았습니다.

```python
from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock

from parcel_lab.retry import retry_request
from parcel_lab.models import Parcel


class RetryRequestStatusForcelistTest(unittest.TestCase):
    @patch("parcel_lab.retry.deliver_internal")
    def test_retries_503_not_500(self, mock_deliver):
        parcel = MagicMock(spec=Parcel)

        policy = retry_request(parcel)

        self.assertEqual(policy.total, 2)
        self.assertIn(503, policy.status_forcelist)
        self.assertNotIn(500, policy.status_forcelist)
        mock_deliver.assert_called_once_with(parcel, policy)


if __name__ == "__main__":
    unittest.main()
```

## 확인 필요

1. 공개된 소스에는 `status_forcelist`가 설정되어 있지 않습니다(즉 원래 값은 기본값 `None`). urllib3 2.7.0 공식 문서에 따르면 `status_forcelist=None`일 때 상태코드 기반 재시도는 비활성화됩니다(https://urllib3.readthedocs.io/en/2.7.0/reference/urllib3.util.html). 따라서 공개된 코드만으로는 "기존에 500을 재시도했다"는 근거가 없습니다 — 요구사항이 공개되지 않은 상위 설정(서브클래스, 팩토리 등)을 전제하는지 확인 필요.
2. 테스트의 `@patch("parcel_lab.retry.deliver_internal")` 경로는 승인된 모듈 심볼 `src.parcel_lab.retry`를 src-layout 관례에 따라 `parcel_lab.retry`로 추정한 것입니다. 실제 패키지 임포트 경로가 다르면 패치가 실패하므로 확인 필요.
