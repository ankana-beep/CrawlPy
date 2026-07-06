from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scraper_framework.utils.accela_persistence as accela_persistence


class FakeCollection:
    def __init__(self) -> None:
        self.operations = None

    def bulk_write(self, operations, ordered=False):
        self.operations = operations
        return type("Result", (), {"upserted_count": 1, "modified_count": 0})()


class FakeDB:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def __getitem__(self, name: str):
        assert name == "sample_collection"
        return self.collection


def test_upsert_many_keeps_created_at_out_of_set_payload(monkeypatch):
    mongo = type("FakeMongo", (), {})()
    mongo.db = FakeDB()

    monkeypatch.setattr(
        accela_persistence,
        "UpdateOne",
        lambda key, update, upsert=True: {"key": key, "update": update, "upsert": upsert},
    )

    count = accela_persistence._upsert_many_documents(
        mongo,
        [
            {
                "target": "https://example.test",
                "category": "Residential Roof Express",
                "row_signature": "abc123",
                "data": {"Record Number": "123"},
            }
        ],
        collection="sample_collection",
        key_fields=["target", "category", "record_number", "row_signature"],
    )

    assert count == 1
    op = mongo.db.collection.operations[0]
    update = op["update"]
    assert "$set" in update
    assert "$setOnInsert" in update
    assert "created_at" not in update["$set"]
    assert "created_at" in update["$setOnInsert"]


def test_build_record_docs_flattens_csv_row_fields():
    docs = accela_persistence._build_record_docs(
        {"permit_type_keyword": "Residential"},
        "https://example.test",
        [
            {
                "path": "downloads/accela_building/Residential_Roof_Express_results.csv",
                "rows": [
                    {
                        "Date": "07/06/2026",
                        "Record Number": "BLD2607-0196",
                        "Record Type": "Residential Roof Express",
                        "Address": "133 N MCGOWAN AVE, CRYSTAL RIVER FL 34429",
                        "Status": "Permit Issued",
                        "Expiration Date": "",
                    }
                ],
            }
        ],
    )

    assert len(docs) == 1
    assert "data" not in docs[0]
    assert docs[0]["Date"] == "07/06/2026"
    assert docs[0]["Record Number"] == "BLD2607-0196"
    assert docs[0]["Address"] == "133 N MCGOWAN AVE, CRYSTAL RIVER FL 34429"
