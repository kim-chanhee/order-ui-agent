"""사용자 표현과 DB에 저장된 표준 값 사이의 별칭 매핑을 제공한다.

Data/docs/value_aliases.json 또는 SCHEMA_VALUE_ALIASES_PATH의 매핑을 캐시해 읽는다.
현재 질문에 나타난 별칭만 골라 SQL 필터와 스키마 검색의 근거로 전달한다.
예를 들어 한국어 상태 표현과 실제 영문 상태 값을 연결할 수 있다.
전체 매핑의 역방향 라벨은 UI 선택지에도 사용해 프런트엔드의 중복 목록을 줄인다.
읽기 실패 시 빈 매핑을 사용하며, 질문에 없는 별칭을 필터로 자동 적용하지 않는다.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from app.data.database import PROJECT_ROOT


ALIASES_ENV = "SCHEMA_VALUE_ALIASES_PATH"


def value_aliases_path() -> Path:
    """별칭 설정 환경 변수 또는 기본 JSON 파일의 경로를 반환한다.

    홈 축약을 확장하며 상대 경로는 프로젝트 루트 기준으로 맞춘다.
    """

    configured = os.environ.get(ALIASES_ENV, "").strip()
    path = Path(configured).expanduser() if configured else PROJECT_ROOT / "Data" / "docs" / "value_aliases.json"
    return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=8)
def _load_aliases(path_text: str) -> dict[str, tuple[str, ...]]:
    """별칭 JSON을 읽어 별칭별 표준 값 튜플로 정리하고 경로별로 캐시한다.

    문자열·리스트 값을 소문자화하고 중복을 제거하며 읽기 실패나 잘못된 구조는 빈 매핑으로 처리한다.
    """

    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    raw_aliases = payload.get("aliases", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw_aliases, dict):
        return {}
    aliases: dict[str, tuple[str, ...]] = {}
    for raw_alias, raw_values in raw_aliases.items():
        alias = str(raw_alias).strip().lower()
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        canonical = tuple(
            dict.fromkeys(
                str(value).strip().lower()
                for value in values
                if str(value).strip()
            )
        )
        if alias and canonical:
            aliases[alias] = canonical
    return aliases


def canonical_values_for_text(text: str) -> dict[str, tuple[str, ...]]:
    """현재 텍스트에 실제로 포함된 별칭과 대응하는 표준 값만 반환한다.

    대소문자를 무시한 부분 문자열 검색을 사용하며 긴 별칭부터 결과를 구성한다.
    """

    lowered = text.lower()
    aliases = _load_aliases(str(value_aliases_path().resolve()))
    return {
        alias: aliases[alias]
        for alias in sorted(aliases, key=len, reverse=True)
        if alias in lowered
    }


def canonical_value_labels() -> dict[str, str]:
    """표준 값에서 사용자 표시용 별칭으로 가는 역방향 매핑을 만든다.

    여러 별칭이 같은 값에 연결되면 먼저 등록된 별칭을 유지해 UI 라벨로 제공한다.
    """

    labels: dict[str, str] = {}
    for alias, values in _load_aliases(str(value_aliases_path().resolve())).items():
        for value in values:
            labels.setdefault(value, alias)
    return labels


def alias_grounding_context(text: str) -> str:
    """현재 발화에서 찾은 별칭과 표준 값을 별칭 → 값 형식의 줄들로 렌더링한다.

    SQL 필터 검증 등에 근거 문자열로 사용하며 일치한 별칭이 없으면 빈 문자열을 반환한다.
    """

    matches = canonical_values_for_text(text)
    if not matches:
        return ""
    return "\n".join(
        f"{alias} -> {', '.join(values)}"
        for alias, values in matches.items()
    )
