"""管理端质量、内容任务、精选正例、实验和评测接口。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from . import analytics, audit, content, content_store, curated_store, eval_store, experiments
from .schemas import (
    ContentTaskFromFeedbackRequest,
    ContentTaskRequest,
    ContentTaskUpdateRequest,
    CuratedExampleUpdateRequest,
    ExperimentRequest,
    ExperimentUpdateRequest,
)
from .security import admin_user

router = APIRouter()


@router.get("/api/admin/analytics/overview")
def admin_analytics_overview(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return analytics.overview(days)


@router.get("/api/admin/analytics/timeseries")
def admin_analytics_timeseries(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.timeseries(days)}


@router.get("/api/admin/analytics/libraries")
def admin_analytics_libraries(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.libraries(days)}


@router.get("/api/admin/analytics/reasons")
def admin_analytics_reasons(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.reasons(days)}


@router.get("/api/admin/analytics/categories")
def admin_analytics_categories(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.categories(days)}


@router.get("/api/admin/analytics/clusters")
def admin_analytics_clusters(
    days: int = analytics.DEFAULT_DAYS,
    limit: int = 20,
    _admin=Depends(admin_user),
):
    return {"items": analytics.clusters(days, limit)}


@router.get("/api/admin/content-tasks")
def admin_content_tasks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    kind: Optional[str] = None,
    library: Optional[str] = None,
    q: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return content_store.list_content_tasks(
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        kind=kind,
        library=library,
        q=(q or "")[:100] or None,
    )


@router.post("/api/admin/content-tasks")
def admin_create_content_task(req: ContentTaskRequest, admin=Depends(admin_user)):
    if req.kind not in content.KINDS:
        raise HTTPException(status_code=422, detail="未知任务类型")
    if req.priority not in content.PRIORITIES:
        raise HTTPException(status_code=422, detail="未知优先级")
    try:
        task = content_store.create_content_task(
            title=req.title,
            description=req.description,
            source=req.source,
            heading=req.heading,
            library=req.library,
            kind=req.kind,
            priority=req.priority,
            owner_id=req.owner_id,
            eval_run_id=req.eval_run_id,
            created_by=admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit.log(
        admin["id"], "content_task.create", "content_task", task["id"],
        {"kind": req.kind, "priority": req.priority},
    )
    return {"ok": True, "task": task}


@router.get("/api/admin/content-tasks/{task_id}")
def admin_content_task_detail(task_id: int, _admin=Depends(admin_user)):
    task = content_store.get_content_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="内容任务不存在")
    return {"task": task}


@router.patch("/api/admin/content-tasks/{task_id}")
def admin_update_content_task(
    task_id: int, req: ContentTaskUpdateRequest, admin=Depends(admin_user)
):
    if req.kind is not None and req.kind not in content.KINDS:
        raise HTTPException(status_code=422, detail="未知任务类型")
    try:
        task = content_store.update_content_task(
            task_id,
            status=req.status,
            priority=req.priority,
            kind=req.kind,
            owner_id=req.owner_id,
            resolution_note=req.resolution_note,
            eval_run_id=req.eval_run_id,
            updated_by=admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not task:
        raise HTTPException(status_code=404, detail="内容任务不存在")
    audit.log(
        admin["id"], "content_task.update", "content_task", task_id,
        {"status": req.status, "priority": req.priority, "kind": req.kind},
    )
    return {"ok": True, "task": task}


@router.post("/api/admin/feedback/{feedback_id}/task")
def admin_task_from_feedback(
    feedback_id: int,
    req: Optional[ContentTaskFromFeedbackRequest] = None,
    admin=Depends(admin_user),
):
    try:
        result = content.create_task_for_feedback(
            feedback_id, admin["id"], req.model_dump() if req else {}
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="反馈不存在")
    audit.log(
        admin["id"], "content_task.from_feedback", "feedback", feedback_id,
        {"task_id": result["task"]["id"], "created": result["created"]},
    )
    return {"ok": True, **result}


@router.get("/api/admin/curated-examples")
def admin_curated_examples(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    library: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return curated_store.list_examples(
        page=page, page_size=page_size, status=status, library=library
    )


@router.get("/api/admin/curated-examples/{example_id}")
def admin_curated_example_detail(example_id: int, _admin=Depends(admin_user)):
    example = curated_store.get_example(example_id)
    if not example:
        raise HTTPException(status_code=404, detail="精选正例不存在")
    return {"example": example}


@router.patch("/api/admin/curated-examples/{example_id}")
def admin_update_curated_example(
    example_id: int, req: CuratedExampleUpdateRequest, admin=Depends(admin_user)
):
    try:
        example = curated_store.update_example(
            example_id,
            status=req.status,
            use_as_few_shot=req.use_as_few_shot,
            eval_passed=req.eval_passed,
            eval_run_id=req.eval_run_id,
            reviewed_by=admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not example:
        raise HTTPException(status_code=404, detail="精选正例不存在")
    audit.log(
        admin["id"], "curated.update", "curated_example", example_id,
        {
            "status": req.status,
            "use_as_few_shot": req.use_as_few_shot,
            "eval_passed": req.eval_passed,
        },
    )
    return {"ok": True, "example": example}


@router.get("/api/admin/experiments")
def admin_experiments(_admin=Depends(admin_user)):
    return {"items": experiments.list_experiments()}


@router.post("/api/admin/experiments")
def admin_create_experiment(req: ExperimentRequest, admin=Depends(admin_user)):
    try:
        item = experiments.create_experiment(
            req.key,
            req.name,
            req.description,
            [variant.model_dump() for variant in req.variants],
            req.guardrails,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit.log(
        admin["id"], "experiment.create", "experiment", item["key"],
        {"variants": [variant["variant_key"] for variant in item["variants"]]},
    )
    return {"ok": True, "experiment": item}


@router.get("/api/admin/experiments/{key}")
def admin_experiment_detail(key: str, _admin=Depends(admin_user)):
    item = experiments.get_experiment(key)
    if not item:
        raise HTTPException(status_code=404, detail="实验不存在")
    return {"experiment": item}


@router.patch("/api/admin/experiments/{key}")
def admin_update_experiment(
    key: str, req: ExperimentUpdateRequest, admin=Depends(admin_user)
):
    try:
        item = experiments.update_experiment(
            key,
            status=req.status,
            variants=[variant.model_dump() for variant in req.variants]
            if req.variants is not None
            else None,
            guardrails=req.guardrails,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail="实验不存在")
    audit.log(
        admin["id"], "experiment.update", "experiment", key,
        {"status": req.status, "variants": req.variants is not None},
    )
    return {"ok": True, "experiment": item}


@router.get("/api/admin/experiments/{key}/results")
def admin_experiment_results(
    key: str, days: int = 14, _admin=Depends(admin_user)
):
    item = experiments.experiment_results(key, days)
    if not item:
        raise HTTPException(status_code=404, detail="实验不存在")
    return item


@router.get("/api/admin/eval/runs")
def admin_eval_runs(page: int = 1, page_size: int = 20, _admin=Depends(admin_user)):
    return eval_store.list_runs(page=page, page_size=page_size)


@router.get("/api/admin/eval/runs/{run_id}")
def admin_eval_run_detail(run_id: int, _admin=Depends(admin_user)):
    item = eval_store.get_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    return {"run": item}


@router.delete("/api/admin/eval/runs/{run_id}")
def admin_delete_eval_run(run_id: int, admin=Depends(admin_user)):
    if not eval_store.delete_run(run_id):
        raise HTTPException(status_code=404, detail="评测记录不存在")
    audit.log(admin["id"], "eval.delete", "eval_run", run_id)
    return {"ok": True}


@router.get("/api/admin/eval/runs/{run_id}/rerun-command")
def admin_eval_rerun_command(run_id: int, _admin=Depends(admin_user)):
    result = eval_store.rerun_command(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    return result


@router.get("/api/admin/audit-log")
def admin_audit_log(
    page: int = 1,
    page_size: int = 20,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return audit.list_events(
        page=page,
        page_size=page_size,
        action=action,
        target_type=target_type,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
    )
