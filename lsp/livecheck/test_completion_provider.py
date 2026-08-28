import os
import sys
import unittest

sys.path.append(os.path.dirname(__file__))
from mecrisp_lsp import MCUCompletionProvider, logger


class TestMCUCompletionProvider(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_mecrisp_stellaris.db"
        cls.provider = MCUCompletionProvider(db_path=cls.db_path)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
            logger.info(f"Deleted temporary database file: {cls.db_path}")

    def test_database_exists(self):
        self.assertTrue(os.path.exists(self.provider.db_path),
                        "Database file should exist")

    def test_get_all_completions_returns_data(self):
        completions = self.provider.get_all_completions()
        self.assertIsInstance(completions, list,
                              "get_all_completions should return a list")
        self.assertGreater(len(completions), 0,
                           "Should have completions in database")
        for completion in completions:
            self.assertIsInstance(completion, tuple,
                                 "Each completion should be a tuple")
            self.assertEqual(len(completion), 4,
                             "Each completion should have 4 elements")

    def test_search_completions_all(self):
        results = self.provider.search_completions("")
        self.assertIsInstance(results, list,
                              "search_completions should return a list")
        all_results = self.provider.get_all_completions()
        self.assertEqual(len(results), len(all_results),
                         "Empty prefix search should return all completions")

    def test_search_completions_with_prefix(self):
        results = self.provider.search_completions("key")
        self.assertIsInstance(results, list,
                              "search_completions should return a list")
        for completion in results:
            word = completion[0]
            self.assertTrue(word.lower().startswith("key"),
                            f"Word '{word}' should start with 'key'")

    def test_search_completions_nonexistent(self):
        results = self.provider.search_completions("xyz123")
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 0,
                         "Should return an empty list for unknown prefix")

    def test_search_case_insensitive(self):
        results_lower = self.provider.search_completions("emit")
        results_upper = self.provider.search_completions("EMIT")
        self.assertGreater(len(results_lower), 0,
                           "Should find 'emit' completions")
        self.assertEqual(len(results_lower), len(results_upper),
                         "Case should not affect search results")

    def test_database_structure(self):
        completions = self.provider.get_all_completions()
        self.assertGreater(len(completions), 0)
        for i, completion in enumerate(completions[:5]):
            word, stack, description, example = completion
            self.assertIsInstance(word, str,
                                  f"Word {i} should be a string")
            self.assertIsInstance(stack, str,
                                  f"Stack {i} should be a string")
            self.assertIsInstance(description, (str, type(None)),
                                  f"Description {i} should be string or None")
            self.assertIsInstance(example, (str, type(None)),
                                  f"Example {i} should be string or None")
