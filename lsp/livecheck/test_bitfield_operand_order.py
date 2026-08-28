import importlib.util
import os
import sys
import unittest

sys.path.append(os.path.dirname(__file__))
# The lint helpers are pygls-free (forth_lint.py) so these tests run in BOTH
# interpreters: system python (has pygls) and the service venv (no pygls).
from forth_lint import (
    is_literal,
    is_svd_helper,
    code_tokens,
    check_bitfield_order,
    _VALUE_CONSTANTS,
    _DICT_WORDS,
    check_unknown_words,
    lint_line,
    extract_defined_words,
)
# Back-compat names the tests were written against:
_is_literal = is_literal
_is_svd_helper = is_svd_helper
_code_tokens = code_tokens
_check_bitfield_order = check_bitfield_order


def _mcp_available():
    """True if the 'mcp' package is importable (only in the service venv)."""
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


class TestBitfieldOperandOrder(unittest.TestCase):
    """The stack-effect operand-order linter for the bfs!/bfc! family.

    bfs! / bfc! have the gate-verified signature ( value addr bitpos -- ),
    where the SVD bitfield-name helper (GPIOA_MODER_MODER9) pushes the
    (addr, bitpos) package.  So the correct order is:
        <value literal>  <SVD bitfield name>  bfs!
    and the silent-failure reversal is:
        <SVD bitfield name>  <value literal>  bfs!
    """

    # ---- token classification --------------------------------------------

    def test_is_literal(self):
        self.assertTrue(_is_literal("%10"))
        self.assertTrue(_is_literal("$20"))
        self.assertTrue(_is_literal("1"))
        self.assertTrue(_is_literal("0x1F"))
        self.assertFalse(_is_literal("GPIOA_MODER_MODER9"))
        self.assertFalse(_is_literal("bfs!"))
        self.assertFalse(_is_literal(""))

    def test_is_svd_helper(self):
        self.assertTrue(_is_svd_helper("GPIOA_MODER_MODER9"))
        self.assertTrue(_is_svd_helper("RCC_AHBENR_IOPCEN"))
        self.assertFalse(_is_svd_helper("%10"))
        self.assertFalse(_is_svd_helper("bfs!"))
        self.assertFalse(_is_svd_helper("led"))
        self.assertFalse(_is_svd_helper("GPIOA"))

    # ---- tokeniser (comment stripping) ------------------------------------

    def test_code_tokens_strips_backslash_comment(self):
        line = "%10 GPIOA_MODER_MODER9 bfs!   \\ PA9 -> AF"
        toks = [t for t, _ in _code_tokens(line)]
        self.assertEqual(toks, ["%10", "GPIOA_MODER_MODER9", "bfs!"])

    def test_code_tokens_strips_inline_comment(self):
        line = "( set PA9 to AF ) %10 GPIOA_MODER_MODER9 bfs!"
        toks = [t for t, _ in _code_tokens(line)]
        self.assertEqual(toks, ["%10", "GPIOA_MODER_MODER9", "bfs!"])

    def test_code_tokens_comment_only_line(self):
        self.assertEqual(_code_tokens("\\ this is all comment"), [])

    # ---- the actual check -------------------------------------------------

    def test_correct_order_no_diagnostic(self):
        line = "%10 GPIOA_MODER_MODER9 bfs!"
        self.assertEqual(_check_bitfield_order(_code_tokens(line)), [])

    def test_reversed_order_diagnostic(self):
        line = "GPIOA_MODER_MODER9 %10 bfs!"
        diags = _check_bitfield_order(_code_tokens(line))
        self.assertEqual(len(diags), 1)
        msg = diags[0][2]
        self.assertIn("Reversed operand order", msg)
        self.assertIn("bfs!", msg)
        self.assertIn("value", msg)

    def test_reversed_order_bfc(self):
        line = "GPIOA_MODER_MODER8 %01 bfc!"
        diags = _check_bitfield_order(_code_tokens(line))
        self.assertEqual(len(diags), 1)
        self.assertIn("bfc!", diags[0][2])

    def test_reversed_order_correct_range(self):
        line = "GPIOA_MODER_MODER9 %10 bfs!"
        diags = _check_bitfield_order(_code_tokens(line))
        start, end, _ = diags[0]
        # Range should span from the SVD helper token to the end of bfs!
        self.assertEqual(line[start:end], line)  # whole line flagged

    def test_literal_then_register_then_bfs_no_false_positive(self):
        # Raw form from the CUSTOM_FORTH example: 1 $40021000 16 bfs!
        # (value addr bitpos bfs!) — should NOT be flagged.
        line = "1 $40021000 16 bfs!"
        self.assertEqual(_check_bitfield_order(_code_tokens(line)), [])

    def test_word_without_known_sig_ignored(self):
        line = "%10 GPIOA_MODER_MODER9 bis!"
        self.assertEqual(_check_bitfield_order(_code_tokens(line)), [])

    def test_short_line_not_flagged(self):
        line = "%10 bfs!"  # missing the helper entirely — leave to the chip
        self.assertEqual(_check_bitfield_order(_code_tokens(line)), [])

    def test_comment_line_not_flagged(self):
        line = "\\ GPIOA_MODER_MODER9 %10 bfs!"
        self.assertEqual(_check_bitfield_order(_code_tokens(line)), [])

    # ---- named value constants (from the build's constants.pat) ------------

    def test_value_constants_loaded(self):
        for name in ("ANALOG", "OUTPUT", "AF", "AF2", "PUSH-PULL", "INPUT"):
            self.assertIn(name, _VALUE_CONSTANTS)

    def test_address_constants_excluded(self):
        # SCB_* are register ADDRESSES, not bitfield values — must be excluded.
        self.assertNotIn("SCB_CPUID", _VALUE_CONSTANTS)
        self.assertNotIn("SCB_ICSR", _VALUE_CONSTANTS)

    def test_named_constant_after_name_flagged(self):
        # Old convention from gpio.fs: value constant AFTER the SVD name.
        for line in (
            "GPIOA_MODER_MODER1 ANALOG bfs!",
            "GPIOA_MODER_MODER5 AF bfs!",
            "GPIOA_AFRL_AFRL5 AF2 bfs!",
            "GPIOC_MODER_MODER9 OUTPUT bfs!",
        ):
            self.assertEqual(
                len(_check_bitfield_order(_code_tokens(line))), 1,
                f"should flag old-convention line: {line}")

    def test_named_constant_first_clean(self):
        # New convention: value constant FIRST, then the SVD name.
        for line in (
            "ANALOG GPIOA_MODER_MODER1 bfs!",
            "AF GPIOA_MODER_MODER5 bfs!",
            "AF2 GPIOA_AFRL_AFRL5 bfs!",
            "OUTPUT GPIOC_MODER_MODER9 bfs!",
        ):
            self.assertEqual(
                _check_bitfield_order(_code_tokens(line)), [],
                f"new-convention line should be clean: {line}")


class TestServerIdentityTag(unittest.TestCase):
    """The shared-tool server tag (Option 2): register_fields / register_lookup
    / chip_info exist on BOTH mecrisp-mcp (8792) and regmon-mcp (8793), so
    every response carries a 'server' field.  A test can assert on it — the
    same assertion the gateway agent suggested would have caught the
    wrong-server confusion."""

    def _load(self, path, name):
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @unittest.skipUnless(_mcp_available(), "mcp package not in this interpreter "
                                           "(run with the .forth-gateway-venv python)")
    def test_mecrisp_tags_shared_tools(self):
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        import mecrisp_mcp
        tools = {t.name: t.fn for t in mecrisp_mcp.build_mcp()._tool_manager._tools.values()}
        import json
        for name, args in [
            ("chip_info", {}),
            ("register_fields", {"peripheral": "GPIOC", "register": "MODER"}),
        ]:
            resp = json.loads(tools[name](**args))
            self.assertEqual(resp.get("server"), "mecrisp-mcp:8792", f"{name} should be tagged")

    @unittest.skipUnless(_mcp_available(), "mcp package not in this interpreter "
                                           "(run with the .forth-gateway-venv python)")
    def test_regmon_tags_shared_tools_and_dedupes(self):
        import sys as _sys
        import json
        regmon_path = os.path.expanduser("~/fossil/swdai/scripts/regmon_mcp.py")
        _sys.path.insert(0, os.path.expanduser("~/fossil/swdai/scripts"))
        spec = importlib.util.spec_from_file_location("regmon_mcp_test", regmon_path)
        regmon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(regmon)
        tools = {t.name: t.fn for t in regmon.build_mcp()._tool_manager._tools.values()}
        # server tag present
        resp = json.loads(tools["register_fields"](peripheral="GPIOC", register="MODER"))
        self.assertEqual(resp.get("server"), "regmon-mcp:8793")
        # dedup against the REAL SVD DB: 16 fields, not 32 (regression guard for
        # the duplicate-row bug — a query, not a live server round-trip).
        self.assertEqual(len(resp["fields"]), 16)
        names = [f["name"] for f in resp["fields"]]
        self.assertEqual(len(names), len(set(names)), "no duplicate field names")
        self.assertEqual(names[0], "MODER0")
        self.assertEqual(names[-1], "MODER15")
        # full descriptions retained (longest wins)
        self.assertIn("(y = 0..15)", resp["fields"][0]["description"] or "")


class TestUnknownWordCheck(unittest.TestCase):
    """The soft unknown-word warning (Terry 2026-08-28): a token that is not
    a literal, SVD helper, dictionary word, or project-defined word is warned
    so agents catch 'not found' bugs (e.g. 'continue') BEFORE the chip does.

    Key DB fact: defining/parsing words are stored with a placeholder suffix
    ('variable name', ': name', 'char *') — the bare word MUST still count as
    known, or every 'variable'/'create'/'char' line would be falsely flagged.
    """

    def test_continue_not_in_dictionary(self):
        self.assertNotIn("continue", _DICT_WORDS)

    def test_define_words_resolve_despite_name_suffix(self):
        for w in ("variable", ":", "create", "constant", "char", "[char]"):
            self.assertIn(w, _DICT_WORDS, f"'{w}' should be known")

    def test_common_words_known(self):
        for w in ("loop", "drop", "if", "then", "begin", "until", "emit"):
            self.assertIn(w, _DICT_WORDS, f"'{w}' should be known")

    def test_continue_line_warned(self):
        diags = lint_line("0= if continue then", known_words=[])
        self.assertTrue(any("continue" in d[2] for d in diags))

    def test_fixed_line_clean(self):
        self.assertEqual(lint_line("0<> if", known_words=[]), [])

    def test_project_words_not_warned(self):
        self.assertEqual(
            lint_line("fb-x @ i fb-s @ * +", known_words=["fb-x", "fb-s"]), [])

    def test_string_literal_not_warned(self):
        self.assertEqual(lint_line('." init #2 run at bootup " cr', known_words=[]), [])

    def test_unknown_word_warned(self):
        diags = lint_line("blorp 1 +", known_words=[])
        self.assertTrue(any("blorp" in d[2] for d in diags))

    def test_extract_defined_words(self):
        defined = extract_defined_words([
            ": fb-char  swap ;",
            "0 variable lcd-x",
            ": beep  tim1-pwm-on ;",
        ])
        self.assertIn("fb-char", defined)
        self.assertIn("lcd-x", defined)
        self.assertIn("beep", defined)


if __name__ == "__main__":
    unittest.main()