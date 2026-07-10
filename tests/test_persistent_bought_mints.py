import os
import tempfile
import unittest

os.environ.setdefault("TG_API_ID", "1")
os.environ.setdefault("TG_API_HASH", "dummy")
os.environ.setdefault("TG_CHANNELS", "dummy")
os.environ.setdefault("SOL_PRIVATE_KEY", "dummy")

from sniper import PersistentBoughtMints


class PersistentBoughtMintsTests(unittest.TestCase):
    def test_persists_and_loads_mints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "bought_mints.txt")
            store = PersistentBoughtMints(path)

            self.assertFalse(store.contains("mint1"))
            store.mark_bought("mint1", confirmed=True)
            self.assertTrue(store.contains("mint1"))

            store2 = PersistentBoughtMints(path)
            self.assertTrue(store2.contains("mint1"))

            store2.mark_bought("mint2", confirmed=True)
            self.assertTrue(store2.contains("mint2"))

            with open(path, "r", encoding="utf-8") as fh:
                data = fh.read().splitlines()

            self.assertEqual(data, ["mint1", "mint2"])

    def test_does_not_persist_before_confirmation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "bought_mints.txt")
            store = PersistentBoughtMints(path)

            store.mark_bought("mint1", confirmed=False)

            self.assertFalse(store.contains("mint1"))
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
