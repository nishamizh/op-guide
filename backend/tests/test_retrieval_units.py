from app.retrieval.bm25 import BM25Index
from app.retrieval.confidence import combine_confidence, label_for_score
from app.retrieval.rrf import reciprocal_rank_fusion
from app.retrieval.service import evidence_supports_query


def test_rrf_formula_and_weights():
    fused = reciprocal_rank_fusion(
        {"bm25": ["a", "b"], "vector": ["b", "a"]},
        weights={"bm25": 1.0, "vector": 2.0},
        k=60,
    )
    scores = {item["id"]: item["rrf_score"] for item in fused}
    assert scores["a"] == (1 / 61) + (2 / 62)
    assert scores["b"] == (1 / 62) + (2 / 61)
    assert fused[0]["id"] == "b"


def test_bm25_ranks_exact_alarm_first():
    index = BM25Index()
    index.rebuild(
        [
            {"id": "coolant", "content": "Alarm E104 coolant flow trip at 1.5 bar on the manifold."},
            {"id": "spindle", "content": "Alarm E221 spindle overheat at 85 deg C."},
        ],
        revision=1,
    )
    hits = index.search("E104 coolant", top_k=2)
    assert hits[0]["id"] == "coolant"
    assert len(hits) == 1
    both = index.search("alarm", top_k=2)
    assert {hit["id"] for hit in both} == {"coolant", "spindle"}


def test_confidence_is_heuristic_and_capped():
    high = combine_confidence(
        retrieval_relevance=0.95,
        source_quality=0.9,
        evidence_coverage=0.9,
        consistency=1,
        groundedness=0.9,
    )
    assert high["label"] == "high"
    assert high["heuristic"] is True
    assert high["calibrated"] is False
    capped = combine_confidence(
        retrieval_relevance=0.95,
        source_quality=0.9,
        evidence_coverage=0.9,
        consistency=1,
        groundedness=0.9,
        caps=["mock_mcp"],
    )
    assert capped["label"] == "medium"
    assert label_for_score(0.2) == "low"


def test_support_requires_the_named_code_not_filler():
    evidence = [
        {
            "content": "Alarm E104 means coolant flow is below 1.5 bar.",
            "section_id": "r200-e104",
            "section_title": "Alarm E104 coolant flow",
            "section_ids": ["r200-e104"],
            "manufacturer": "Rainer",
            "machine_model": "R200",
        }
    ]
    assert evidence_supports_query("What does Zephyr Z9 alarm Z999 mean?", evidence) is False
    assert evidence_supports_query(
        "What does Zephyr Z9 alarm Z999 mean? troubleshooting cause checks setpoint revision",
        evidence,
    ) is False
    assert evidence_supports_query("What does Rainer R200 E104 mean?", evidence) is True
