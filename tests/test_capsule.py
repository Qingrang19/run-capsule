import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_capsule.core import CapsuleError, digest_of, run_label, snapshot, verify


class CapsuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "data/a.csv").write_text("1,2\n", encoding="utf-8")
        (self.root / "data/b.csv").write_text("3,4\n", encoding="utf-8")

    def snap(self, **kw):
        return snapshot(self.root, ["data"], **kw)

    def test_deterministic(self):
        self.assertEqual(self.snap(), self.snap())

    def test_expected_file_digest(self):
        f = self.snap()["files"][0]
        self.assertEqual(f["sha256"], hashlib.sha256(b"1,2\n").hexdigest())
        self.assertEqual(f["path"], "data/a.csv")

    def test_verified(self):
        self.assertTrue(verify(self.root, self.snap())["ok"])

    def test_all_change_categories(self):
        m = self.snap()
        (self.root / "data/a.csv").write_text("new")
        (self.root / "data/b.csv").unlink()
        (self.root / "data/c.csv").write_text("extra")
        result = verify(self.root, m)
        self.assertFalse(result["ok"])
        self.assertEqual(result["modified"], ["data/a.csv"])
        self.assertEqual(result["missing"], ["data/b.csv"])
        self.assertEqual(result["new"], ["data/c.csv"])

    def test_hidden_default_and_opt_in(self):
        (self.root / "data/.env").write_text("synthetic")
        (self.root / "data/.cache").mkdir()
        (self.root / "data/.cache/x").write_text("hidden")
        self.assertEqual(len(self.snap()["files"]), 2)
        self.assertEqual(len(self.snap(include_hidden=True)["files"]), 4)

    def test_explicit_hidden_rejected(self):
        (self.root / ".file").write_text("x")
        with self.assertRaises(CapsuleError):
            snapshot(self.root, [".file"])

    def test_output_excluded(self):
        output = self.root / "data/manifest.json"
        m = self.snap(output=output)
        output.write_text(json.dumps(m))
        self.assertTrue(verify(self.root, m)["ok"])
        self.assertEqual(m["policy"]["exclude"], ["data/manifest.json"])

    def test_duplicate_overlap_deduplication(self):
        m = snapshot(self.root, ["data", "data/a.csv", "data"])
        self.assertEqual(len(m["files"]), 2)
        self.assertEqual(len(m["inputs"]), 2)

    def test_no_implicit_other_inputs(self):
        (self.root / "other.txt").write_text("unselected")
        self.assertEqual(len(self.snap()["files"]), 2)

    def test_config_order_stable_but_values_affect_digest(self):
        a = self.snap(config={"seed": 1, "solver": "x"})
        b = self.snap(config={"solver": "x", "seed": 1})
        self.assertEqual(a["digest"], b["digest"])
        self.assertNotEqual(a["digest"], self.snap(config={"seed": 2})["digest"])

    def test_unsafe_paths(self):
        for value in ("../outside", "/etc/passwd", "data\\a.csv", "data/../data", "./data", "C:/data"):
            with self.subTest(value=value), self.assertRaises(CapsuleError):
                snapshot(self.root, [value])

    def test_manifest_tampering_rejected(self):
        m = self.snap()
        m["config"]["tampered"] = True
        with self.assertRaises(CapsuleError):
            verify(self.root, m)

    def test_symlinks_not_followed(self):
        link = self.root / "data/link"
        try:
            link.symlink_to(self.root / "data/a.csv")
        except (OSError, NotImplementedError):
            self.skipTest("Platform has no symlink support")
        m = self.snap()
        self.assertEqual(m["skipped_symlinks"], ["data/link"])
        self.assertEqual(len(m["files"]), 2)
        with self.assertRaises(CapsuleError):
            snapshot(self.root, ["data/link"])

    def test_symlink_ancestor_rejected(self):
        try:
            (self.root / "alias").symlink_to(self.root / "data", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Platform has no symlink support")
        with self.assertRaises(CapsuleError):
            snapshot(self.root, ["alias/a.csv"])

    def test_root_portability(self):
        m = self.snap()
        with tempfile.TemporaryDirectory() as other:
            target = Path(other)
            (target / "data").mkdir()
            for p in (self.root / "data").iterdir():
                (target / "data" / p.name).write_bytes(p.read_bytes())
            self.assertTrue(verify(target, m)["ok"])
            self.assertEqual(m, snapshot(target, ["data"]))

    def test_mtime_does_not_affect_digest(self):
        import os
        m = self.snap()
        os.utime(self.root / "data/a.csv", (1000, 1000))
        self.assertEqual(m["digest"], self.snap()["digest"])

    def test_empty_directory(self):
        (self.root / "empty").mkdir()
        self.assertEqual(snapshot(self.root, ["empty"])["files"], [])

    def test_unicode_and_empty_file(self):
        (self.root / "data/测量.csv").write_bytes(b"")
        m = self.snap()
        self.assertEqual(m["files"][-1]["size"], 0)
        self.assertTrue(verify(self.root, m)["ok"])

    def test_cli_smoke_and_no_overwrite(self):
        output = self.root / "manifest.json"
        command = [sys.executable, "-m", "run_capsule"]
        create = command + ["snapshot", "data", "--root", str(self.root), "--output", str(output)]
        p = subprocess.run(create, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = subprocess.run(create, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        check = command + ["verify", str(output), "--root", str(self.root)]
        self.assertEqual(subprocess.run(check, capture_output=True).returncode, 0)
        (self.root / "data/new").write_text("new")
        self.assertEqual(subprocess.run(check, capture_output=True).returncode, 1)

    def test_nonfinite_and_nonobject_config_rejected(self):
        for config in ([1], {"value": float("nan")}):
            with self.assertRaises(ValueError):
                self.snap(config=config)

    def test_label_format(self):
        label = self.snap()["label"]
        self.assertEqual(len(label.split("-")), 6)
        self.assertEqual(len(label.split("-")[-1]), 8)

    def test_missing_whole_directory(self):
        m = self.snap()
        for f in (self.root / "data").iterdir():
            f.unlink()
        (self.root / "data").rmdir()
        self.assertEqual(len(verify(self.root, m)["missing"]), 2)


if __name__ == "__main__":
    unittest.main()
