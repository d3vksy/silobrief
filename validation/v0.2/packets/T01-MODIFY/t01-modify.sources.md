# Approved source excerpts

이 파일에는 사용자가 외부 공개를 승인한 원문 코드가 포함되어 있습니다. 주석, docstring, 문자열, 경로와 내부 식별자를 직접 확인하십시오.

## `src/parcel_lab/retry.py` — `function retry_request` — lines 11-14

Boundary exposure approval: delivery-boundary

```python
def retry_request(parcel: Parcel) -> object:
    retry_policy = urllib3.Retry(total=2)
    deliver_internal(parcel, retry_policy)
    return retry_policy
```
