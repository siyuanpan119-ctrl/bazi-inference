"""Synthetic scoring and freeze-integrity tests; no predictive validity claims."""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from score_frozen_dual import AuditError, MANIFEST, RULINGS, main, score, sha256, write_output


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(base):
    root = base / "frozen"
    root.mkdir()
    rows = [
        {"question": i, "bazi_primary": b, "ziwei_primary": z, "final": f,
         "strongest_backup": backup, "support_state": status, "reason": "Synthetic only"}
        for i, b, z, f, backup, status in [
            (1, "A", "A", "A", "B", "relative"),
            (2, "B", "C", "C", "B", "split_override"),
            (3, "A", "C", "C", "B", "split_override"),
            (4, "A", "B", "B", "C", "forced_low"),
        ]
    ]
    dump(root / RULINGS, {"observation_year": 2026, "records": rows})
    (root / "protocol.md").write_text("Synthetic frozen protocol", encoding="utf-8")
    key = base / "key.json"
    dump(key, {"answer_groups": ["AB", "CD"], "source": "user-provided", "observation_year": 2026})
    refresh_manifest(root)
    return root, key


def refresh_manifest(root):
    rows = json.loads((root / RULINGS).read_text())["records"]
    dump(root / MANIFEST, {
        "observation_year": 2026, "answer_sequence": "".join(r["final"] for r in rows),
        "files_sha256": {name: sha256(root / name) for name in (RULINGS, "protocol.md")},
    })


class FrozenDualScoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.key = fixture(self.base)

    def score(self):
        return score(self.root, self.key, case_size=2, expected_count=4)

    def test_metrics_and_coverage_are_distinct(self):
        result = self.score()
        self.assertEqual(result["systems"]["fusion"], {"correct": 2, "total": 4, "accuracy": .5})
        self.assertEqual(result["agreement"]["count"], 1)
        self.assertEqual(result["disagreement"]["count"], 3)
        self.assertEqual(result["changes_from_bazi"]["wrong_to_correct"]["questions"], [3])
        self.assertEqual(result["changes_from_bazi"]["correct_to_wrong"]["questions"], [2])
        self.assertEqual(result["changes_from_bazi"]["wrong_to_wrong"]["questions"], [4])
        self.assertEqual(result["changes_from_bazi"]["net_correct"], 0)
        coverage = result["coverage"]["fusion_primary_or_backup"]
        self.assertEqual(coverage["coverage"], .75)
        self.assertNotIn("accuracy", coverage)
        self.assertEqual(result["coverage"]["backup_recovers_primary_errors"]["questions"], [2])
        self.assertEqual(result["coverage"]["backup_alone"]["hit_rate"], .25)
        self.assertIsNone(result["coverage"]["independent_system_top_two"])
        self.assertEqual(len(result["by_case"]), 2)
        self.assertEqual(result["records"][1]["correct_key"], "B")
        self.assertTrue(result["records"][1]["correct"]["bazi"])

    def test_wrong_key_length_and_illegal_choice(self):
        for groups, message in [(["ABC"], "Expected 4 key"), (["ABCE"], "A/B/C/D")]:
            with self.subTest(groups=groups):
                dump(self.key, {"answer_groups": groups, "source": "user-provided", "observation_year": 2026})
                with self.assertRaisesRegex(AuditError, message):
                    self.score()

    def test_hash_mismatch_is_rejected_before_scoring(self):
        (self.root / "protocol.md").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(AuditError, "Hash mismatch"):
            self.score()

    def test_duplicate_and_missing_ids_even_with_updated_hashes(self):
        path = self.root / RULINGS
        original = path.read_text()
        for ids, message in [([1, 2, 2, 4], "Duplicate"), ([1, 2, 3, 5], "Missing")]:
            with self.subTest(ids=ids):
                data = json.loads(original)
                for row, qid in zip(data["records"], ids):
                    row["question"] = qid
                dump(path, data)
                refresh_manifest(self.root)
                with self.assertRaisesRegex(AuditError, message):
                    self.score()

    def test_missing_record_is_rejected(self):
        path = self.root / RULINGS
        data = json.loads(path.read_text())
        data["records"].pop()
        dump(path, data)
        refresh_manifest(self.root)
        with self.assertRaisesRegex(AuditError, "missing or extra"):
            self.score()

    def test_frozen_sequence_must_match_records(self):
        path = self.root / MANIFEST
        manifest = json.loads(path.read_text())
        manifest["answer_sequence"] = "AAAA"
        dump(path, manifest)
        with self.assertRaisesRegex(AuditError, "answer_sequence"):
            self.score()

    def test_observation_year_must_match(self):
        data = json.loads(self.key.read_text())
        data["observation_year"] = 2025
        dump(self.key, data)
        with self.assertRaisesRegex(AuditError, "observation_year"):
            self.score()

    def test_cli_preserves_inputs_and_refuses_overwrites(self):
        originals = {p: p.read_bytes() for p in self.root.iterdir()}
        originals[self.key] = self.key.read_bytes()
        output = self.base / "result.json"
        args = ["--root", str(self.root), "--key", str(self.key), "--output", str(output),
                "--case-size", "2", "--expected-questions", "4"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        saved = output.read_bytes()
        with self.assertRaises(SystemExit) as error:
            main(args)
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(output.read_bytes(), saved)
        for protected in (self.key, self.root / MANIFEST, self.root / "new.json"):
            with self.assertRaisesRegex(AuditError, "must not overwrite"):
                write_output(protected, {}, self.root, self.key)
        for path, before in originals.items():
            self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / "new.json").exists())

    def test_failed_cli_does_not_create_output(self):
        (self.root / RULINGS).write_text("{}", encoding="utf-8")
        output = self.base / "result.json"
        with self.assertRaises(SystemExit):
            main(["--root", str(self.root), "--key", str(self.key), "--output", str(output),
                  "--expected-questions", "4"])
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
