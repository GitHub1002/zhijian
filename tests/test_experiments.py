"""在线实验：配置校验、分桶、运行时覆盖和护栏。"""
import pytest

from app import config, db, experiments, tracing

VARIANTS = [
    {
        "variant_key": "control",
        "name": "对照",
        "config": {},
        "traffic_pct": 50,
        "is_control": True,
    },
    {
        "variant_key": "treatment",
        "name": "实验",
        "config": {"MIN_RERANK_SCORE": 0.5, "RRF_K": 40},
        "traffic_pct": 50,
        "is_control": False,
    },
]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    experiments.refresh_cache()
    return db


def _experiment(database, key="demo"):
    experiments.create_experiment(key, "演示实验", variants=VARIANTS)
    experiments.update_experiment(key, status="running")
    return key


def _assign(database, user_id, key, variant_key):
    with database.connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO experiment_assignments(
                user_id, experiment_key, variant_key, assigned_at
            ) VALUES (?, ?, ?, ?)""",
            (user_id, key, variant_key, database.now()),
        )
    experiments.refresh_cache()


def test_validate_config_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        experiments.validate_config({"TOP_K": 3})
    with pytest.raises(ValueError):
        experiments.validate_config({"RRF_K": 1})
    with pytest.raises(ValueError):
        experiments.validate_config({"RERANK_ENABLED": "yes"})
    assert experiments.validate_config({"RRF_K": 60, "RERANK_ENABLED": True}) == {
        "RRF_K": 60,
        "RERANK_ENABLED": True,
    }


def test_variants_require_one_control_and_traffic_limit():
    with pytest.raises(ValueError):
        experiments._normalize_variants(
            [{"variant_key": "a", "traffic_pct": 100, "is_control": False}]
        )
    with pytest.raises(ValueError):
        experiments._normalize_variants(
            [
                {"variant_key": "a", "traffic_pct": 80, "is_control": True},
                {"variant_key": "b", "traffic_pct": 30, "is_control": False},
            ]
        )


def test_resolve_is_disabled_by_default(temp_db, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_ENABLED", False)
    _experiment(temp_db)
    user = temp_db.create_user("alice", "secret123")

    assert experiments.resolve_retrieval_config(user["id"]) == ({}, {})


def test_assignment_is_deterministic(temp_db, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_ENABLED", True)
    key = _experiment(temp_db)
    user = temp_db.create_user("alice", "secret123")

    first = experiments.resolve_retrieval_config(user["id"])
    experiments.refresh_cache()
    second = experiments.resolve_retrieval_config(user["id"])

    assert first == second
    assert first[1][key] in {"control", "treatment"}


def test_sticky_assignment_controls_effective_config(temp_db, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_ENABLED", True)
    key = _experiment(temp_db)
    control_user = temp_db.create_user("alice", "secret123")
    treatment_user = temp_db.create_user("bob", "secret123")
    _assign(temp_db, control_user["id"], key, "control")
    _assign(temp_db, treatment_user["id"], key, "treatment")

    control_config, control_meta = experiments.resolve_retrieval_config(control_user["id"])
    treatment_config, treatment_meta = experiments.resolve_retrieval_config(
        treatment_user["id"]
    )

    assert control_config == {}
    assert control_meta[key] == "control"
    assert treatment_config["MIN_RERANK_SCORE"] == 0.5
    assert treatment_config["RRF_K"] == 40
    assert treatment_meta[key] == "treatment"


def test_paused_experiment_is_not_resolved(temp_db, monkeypatch):
    monkeypatch.setattr(config, "EXPERIMENTS_ENABLED", True)
    key = _experiment(temp_db)
    user = temp_db.create_user("alice", "secret123")
    experiments.update_experiment(key, status="paused")

    assert experiments.resolve_retrieval_config(user["id"]) == ({}, {})


def test_results_and_guardrails(temp_db):
    key = _experiment(temp_db)
    control = temp_db.create_user("alice", "secret123")
    treatment = temp_db.create_user("bob", "secret123")
    _assign(temp_db, control["id"], key, "control")
    _assign(temp_db, treatment["id"], key, "treatment")

    control_answer = temp_db.create_answer(control["id"], "q1", "a1", "[]")
    tracing.record(
        answer_id=control_answer,
        user_id=control["id"],
        question="q1",
        grounded=True,
        timings={"prepare_ms": 100},
    )
    temp_db.save_feedback(
        control_answer, control["id"], 5, sentiment="positive", reasons=["helpful"]
    )

    treatment_answer = temp_db.create_answer(treatment["id"], "q2", "拒答", "[]")
    tracing.record(
        answer_id=treatment_answer,
        user_id=treatment["id"],
        question="q2",
        grounded=False,
        refusal_reason="no_grounded_evidence",
        timings={"prepare_ms": 300},
    )
    temp_db.save_feedback(
        treatment_answer, treatment["id"], 1, sentiment="negative", reasons=["wrong_info"]
    )

    result = experiments.experiment_results(key, days=14)
    items = {item["variant_key"]: item for item in result["variants"]}

    assert items["control"]["answers"] == 1
    assert items["control"]["refusal_rate"] == 0.0
    assert items["treatment"]["refusals"] == 1
    assert items["treatment"]["negative_rate"] == 1.0
    assert items["treatment"]["guardrail_breached"] is True
    assert len(items["treatment"]["guardrail_flags"]) == 3
