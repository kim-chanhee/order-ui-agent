"""두 모드가 공유하는 SQL 실행 실패 응답 데이터를 만든다.

result_payload의 실패 데이터는 빈 columns/rows와 실패 메타데이터로 구성한다.
메타데이터에는 실행 경로·오류·실패 단계·분류·재시도 가능 여부·기본 표시 형식을 넣는다.
성공 결과가 없는 경우에도 UI와 실행 기록이 같은 데이터 구조를 사용할 수 있게 한다.
이 파일은 오류를 분류하거나 문자열의 비밀 값을 가리는 처리를 직접 수행하지 않는다.
"""


def _failed_payload(
    error: str,
    *,
    failure_stage: str = "unknown",
    failure_category: str = "unclassified",
    retryable: bool = False,
) -> dict:
    """성공한 조회 데이터가 없을 때 사용할 공통 실패 딕셔너리를 만든다.

    빈 컬럼·행과 함께 전달받은 오류·실패 단계·분류·재시도 가능 여부를 메타데이터로 반환한다.
    """

    return {
        "columns": [],
        "rows": [],
        "metadata": {
            "execution_route": "fast_llm_sql_failed",
            "fallback_error": error,
            "failure_stage": failure_stage,
            "failure_category": failure_category,
            "retryable": retryable,
            "result_view": "table",
        },
    }
