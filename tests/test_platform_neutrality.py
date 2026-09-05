import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
WEB_SOURCE = REPOSITORY / "apps" / "web" / "src"


class PlatformNeutralityTests(unittest.TestCase):
    def test_ui_does_not_embed_company_specific_taxonomy_or_vocabulary(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in WEB_SOURCE.rglob("*")
            if path.suffix in {".ts", ".tsx"} and "test" not in path.parts
        ).casefold()

        for forbidden in (
            "defect_titles",
            "mts net",
            "kafka",
            "hdfs",
            "дата-каталог",
            "витрина-агрегат",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
