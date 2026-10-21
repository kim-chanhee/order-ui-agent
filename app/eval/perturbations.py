"""Deterministic, meaning-preserving Korean question perturbations for Text2SQL evals."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable


def expand_with_perturbations(
    items: list[dict[str, Any]],
    *,
    variants_per_item: int = 6,
) -> list[dict[str, Any]]:
    """Expand each gold case with bounded wording, spacing, and typo variants."""

    if variants_per_item < 1:
        raise ValueError("variants_per_item must be at least 1")
    expanded: list[dict[str, Any]] = []
    transforms: list[tuple[str, Callable[[str], str]]] = [
        ("polite_wrapper", _polite_wrapper),
        ("compact_spacing", _compact_spacing),
        ("synonym", _synonym_variant),
        ("keyword_spacing", _keyword_spacing),
        ("common_typo", _common_typo),
        ("request_prefix", lambda text: f"데이터에서 다음 내용을 조회해줘: {text.rstrip()}"),
    ]
    for original in items:
        base_id = str(original["id"])
        base = deepcopy(original)
        base["base_id"] = base_id
        base["perturbation_kind"] = "original"
        expanded.append(base)
        seen = {_canonical_question(str(base["question"]))}
        for kind, transform in transforms:
            if len([item for item in expanded if item.get("base_id") == base_id]) >= variants_per_item:
                break
            question = transform(str(original["question"]))
            canonical = _canonical_question(question)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            variant = deepcopy(original)
            variant["id"] = f"{base_id}__p{len(seen) - 1:02d}"
            variant["question"] = question
            variant["base_id"] = base_id
            variant["perturbation_kind"] = kind
            expanded.append(variant)
    return expanded


def _polite_wrapper(text: str) -> str:
    return text.rstrip(" .?") + " 확인 부탁드립니다."


def _compact_spacing(text: str) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    return compact.replace("최근 ", "최근").replace("배송 실패", "배송실패").rstrip(".")


def _synonym_variant(text: str) -> str:
    replacements = (
        ("알려줘", "보여줘"),
        ("확인해줘", "보여줘"),
        ("동안", "간"),
        ("기준으로", "범위에서"),
        ("전체", "모든"),
        ("가장 높은", "최고인"),
    )
    result = text
    for source, target in replacements:
        result = result.replace(source, target)
    return result if result != text else f"{text.rstrip()} 결과를 보여줘."


def _keyword_spacing(text: str) -> str:
    result = text.replace("고객별", "고객 별").replace("일자별", "일자 별")
    result = result.replace("주문 수", "주문수").replace("물품명", "물품 이름")
    return result if result != text else re.sub(r"\s+", "  ", text, count=1)


def _common_typo(text: str) -> str:
    replacements = (
        ("배송", "배숑"),
        ("고객", "고갞"),
        ("주문", "주뮨"),
        ("물품", "물픔"),
    )
    for source, target in replacements:
        if source in text:
            return text.replace(source, target, 1)
    return text + " 조회"


def _canonical_question(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()
