import importlib
import sys
import unittest


class SubwayBlindPackageInitTests(unittest.TestCase):
    def test_importing_package_does_not_eagerly_import_app(self):
        original_package = sys.modules.pop("subway_blind", None)
        original_app = sys.modules.pop("subway_blind.app", None)
        try:
            package = importlib.import_module("subway_blind")

            self.assertTrue(callable(package.main))
            self.assertNotIn("subway_blind.app", sys.modules)
        finally:
            sys.modules.pop("subway_blind", None)
            sys.modules.pop("subway_blind.app", None)
            if original_package is not None:
                sys.modules["subway_blind"] = original_package
            if original_app is not None:
                sys.modules["subway_blind.app"] = original_app


if __name__ == "__main__":
    unittest.main()
