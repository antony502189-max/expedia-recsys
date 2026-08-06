import json
from pathlib import Path

from expedia_analytics.contracts import (
    DESTINATION_COLUMNS,
    PROHIBITED_PUBLIC_TERMS,
    PUBLISHED_OBJECTS,
    TEST_COLUMNS,
    TRAIN_COLUMNS,
)


def test_source_contracts_have_unique_columns() -> None:
    for columns in (TRAIN_COLUMNS, TEST_COLUMNS, DESTINATION_COLUMNS):
        names = [item.name for item in columns]
        assert len(names) == len(set(names))


def test_destination_contract_has_all_latent_features() -> None:
    names = {item.name for item in DESTINATION_COLUMNS}
    assert "srch_destination_id" in names
    assert {f"d{index}" for index in range(1, 150)} <= names
    assert len(names) == 150


def test_published_objects_have_unique_names_and_grains() -> None:
    names = [item.name for item in PUBLISHED_OBJECTS]
    assert len(names) == len(set(names))
    assert all(item.grain for item in PUBLISHED_OBJECTS)
    assert all(item.description for item in PUBLISHED_OBJECTS)


def test_public_object_and_metric_names_avoid_prohibited_claims() -> None:
    public_names = [item.name for item in PUBLISHED_OBJECTS if item.layer == "mart"]
    contract_path = Path(__file__).resolve().parents[1] / "config" / "analytics_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    metric_names = list(contract["published_metric_names"].values())
    text = " ".join([*public_names, *metric_names]).lower()
    assert not {term for term in PROHIBITED_PUBLIC_TERMS if term in text}


def test_required_final_layers_exist() -> None:
    names = {item.name for item in PUBLISHED_OBJECTS}
    assert {
        "stg_train_accepted",
        "quarantine_train",
        "fct_hotel_interactions",
        "fct_proxy_search_contexts",
        "fct_user_day",
        "dim_origin",
        "dim_destination",
        "bridge_destination_hotel_market",
        "dm_interaction_outcome_daily",
        "dm_proxy_context_daily",
        "dm_observed_recurrence",
        "dm_missingness_daily",
        "dm_booking_population_drift",
    } <= names


def test_final_contract_contains_binary_acceptance_minimums() -> None:
    contract_path = Path(__file__).resolve().parents[1] / "config" / "analytics_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    minimums = contract["full_dataset_minimums"]
    assert minimums["train"] >= 30_000_000
    assert minimums["test"] >= 2_000_000
    assert minimums["destinations"] >= 60_000
