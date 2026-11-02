from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.a2ui.review import surface_for_plan
from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiPlan, UiBlock, UiOption, UiCondition
from app.planning.a2ui.validator import validate_ui_plan
from app.routes.a2ui import review
from app.runtime.a2ui.surfaces import get_plan_surface


def example_plan():
    return UiPlan(
        summary="고객별 배송 실패 주문을 확인합니다.",
        analysis_plan=AnalysisPlan(
            original_question="최근 7일 고객별 배송 실패 주문 수를 보여줘",
            date_range={"mode": "relative", "relative_days": 7},
            metric={"kind": "count", "unit": "order", "field": "order_id"},
            event_types=["failed delivery"], group_by=["customer_id"], limit=10,
        ),
        ui_blocks=[
            UiBlock(type="option_cards", key="metric", field_path="metric.kind", label="결과 방식", required=True,
                    options=[UiOption(value=x, label=y) for x, y in [("count", "건수"), ("ratio", "비율"), ("rows", "상세 목록")]]),
            UiBlock(type="date_range", key="period", field_path="date_range", label="조회 기간"),
            UiBlock(type="multi_select", key="groups", field_path="group_by", label="집계 기준",
                    options=[UiOption(value="customer_id", label="고객별"), UiOption(value="day", label="일자별")]),
            UiBlock(type="multi_select", key="events", field_path="event_types", label="대상 이벤트", required=True,
                    options=[UiOption(value="failed delivery", label="배송 실패"), UiOption(value="package delivered", label="배송 완료")]),
            UiBlock(type="select", key="numerator", field_path="metric.numerator", label="분자",
                    visible_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
                    required_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
                    options=[UiOption(value="order_id", label="주문 수")]),
            UiBlock(type="select", key="denominator", field_path="metric.denominator", label="분모",
                    visible_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
                    required_if=UiCondition(path="metric.kind", operator="eq", value="ratio"),
                    options=[UiOption(value="order_id", label="주문 수")]),
            UiBlock(type="choice", key="comparison", field_path="comparison", label="비교",
                    options=[UiOption(value="event_vs_event", label="이벤트 비교")]),
            UiBlock(type="number", key="limit", field_path="limit", label="최대 결과 수"),
        ],
    )


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDER_UI_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    app = FastAPI()
    app.include_router(review.router)
    plan = example_plan()
    surface = surface_for_plan(plan, [], participant_id=None, thread_id="test-thread")
    request = dict(question=plan.analysis_plan.original_question, plan=plan.model_dump(mode="json"),
                   surface_id=surface["surface_id"], plan_id=surface["plan_id"], revision=1)
    return TestClient(app), request


def test_update_persists_without_execution_and_rejects_old_revision(session, monkeypatch):
    client, request = session
    monkeypatch.setattr(review, "confirm_response_payload", lambda _: pytest.fail("update must not execute"))
    request["plan"]["analysis_plan"]["date_range"]["relative_days"] = 30
    response = client.post("/api/review/update", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == 2
    assert body["plan"]["analysis_plan"]["date_range"]["relative_days"] == 30
    assert get_plan_surface(request["surface_id"])["revision"] == 2
    assert client.post("/api/review/update", json=request).status_code == 409
    assert client.post("/api/review/confirm", json=request).status_code == 409


@pytest.mark.parametrize("tamper", ["options", "field", "question", "schema"])
def test_rejects_tampered_edit_and_preserves_server_plan(session, tamper):
    client, request = session
    if tamper == "options":
        request["plan"]["analysis_plan"]["group_by"] = ["invented"]
        request["plan"]["ui_blocks"][2]["options"].append({"value": "invented", "label": "invented"})
    elif tamper == "field":
        request["plan"]["analysis_plan"]["target_entity"] = "customer"
    elif tamper == "question":
        request["question"] = "다른 질문"
    else:
        request["plan"]["ui_blocks"].append({"key": "new", "type": "text", "label": "new", "field_path": "output.view"})
        request["plan"]["analysis_plan"]["output"]["view"] = "chart"
    response = client.post("/api/review/update", json=request)
    assert response.status_code == 422, response.text
    assert get_plan_surface(request["surface_id"])["revision"] == 1


def test_incomplete_ratio_is_saved_but_not_executable(session):
    client, request = session
    request["plan"]["analysis_plan"]["metric"]["kind"] = "ratio"
    response = client.post("/api/review/update", json=request)
    assert response.status_code == 200
    plan = response.json()["plan"]
    assert set(plan["missing_fields"]) == {"metric.numerator", "metric.denominator"}
    with pytest.raises(ValueError, match="required analysis fields"):
        validate_ui_plan(UiPlan.model_validate({k: v for k, v in plan.items() if k not in {"surface_id", "plan_id", "revision"}}), request["question"])


def test_invalid_date_does_not_replace_saved_plan(session):
    client, request = session
    request["plan"]["analysis_plan"]["date_range"] = {"mode": "custom", "date_from": "2026-10-24", "date_to": "2026-10-01"}
    assert client.post("/api/review/update", json=request).status_code == 422
    assert get_plan_surface(request["surface_id"])["revision"] == 1


def test_parallel_updates_only_one_wins(session):
    client, request = session
    requests = [deepcopy(request), deepcopy(request)]
    requests[0]["plan"]["analysis_plan"]["limit"] = 20
    requests[1]["plan"]["analysis_plan"]["limit"] = 30
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda body: client.post("/api/review/update", json=body), requests))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert get_plan_surface(request["surface_id"])["revision"] == 2


def test_event_comparison_requires_two_events():
    plan = example_plan()
    plan.analysis_plan.comparison = "event_vs_event"
    with pytest.raises(ValueError, match="두 개 이상"):
        validate_ui_plan(plan, plan.analysis_plan.original_question)
    plan.analysis_plan.event_types.append("package delivered")
    validate_ui_plan(plan, plan.analysis_plan.original_question)


def test_saved_revision_can_be_confirmed_with_exact_values(session, monkeypatch):
    client, request = session
    request["plan"]["analysis_plan"]["limit"] = 20
    saved = client.post("/api/review/update", json=request).json()
    request["revision"] = saved["revision"]
    request["plan"] = {k: v for k, v in saved["plan"].items() if k not in {"surface_id", "plan_id", "revision"}}
    executed = []

    def execute(payload):
        analysis = validate_ui_plan(payload.plan, payload.question)
        executed.append((payload.revision, analysis.limit))
        return dict(thread_id="test-thread", input_source="agent2ui", plan=payload.plan.model_dump(mode="json"),
                    message="ok", execution_result={})

    monkeypatch.setattr(review, "confirm_response_payload", execute)
    for name in ["record_execution_result", "remember_execution_context", "append_experiment_csv", "append_chat_csv"]:
        monkeypatch.setattr(review, name, lambda *args, **kwargs: None)
    response = client.post("/api/review/confirm", json=request)
    assert response.status_code == 200, response.text
    assert executed == [(2, 20)]


def test_natural_language_refinement_uses_saved_revision(session, monkeypatch):
    client, request = session
    request["plan"]["analysis_plan"]["limit"] = 20
    saved = client.post("/api/review/update", json=request).json()
    request["revision"] = saved["revision"]
    request["plan"] = {k: v for k, v in saved["plan"].items() if k not in {"surface_id", "plan_id", "revision"}}
    request["additional_constraint"] = "최근 90일로 변경"

    def refine(plan, **kwargs):
        assert plan.analysis_plan.limit == 20
        plan.analysis_plan.date_range.relative_days = 90
        return plan

    monkeypatch.setattr(review, "refine_review_plan", refine)
    monkeypatch.setattr(review, "append_experiment_csv", lambda **kwargs: None)
    response = client.post("/api/review/refine", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 3
    assert response.json()["plan"]["analysis_plan"]["date_range"]["relative_days"] == 90
    assert client.post("/api/review/refine", json=request).status_code == 409
