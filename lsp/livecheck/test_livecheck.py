import os
import sys
import unittest

sys.path.append(os.path.dirname(__file__))
import forth_livecheck as LC


class TestLiveCheckCore(unittest.TestCase):
    """LiveCheck: per-line live compilation checks + flash-deny + SWD reset."""

    def setUp(self):
        # Mock the bench round-trip so tests never touch the chip.
        self._orig_run = LC.run_line
        self._orig_fast = LC._fast_run
        self._orig_reset = LC.hw_reset
        LC._fast_run = lambda line: line + " ok."
        LC._fast_run = lambda line: line + " ok."
        self.reset_calls = []
        LC.hw_reset = lambda: self.reset_calls.append("reset") or "(mock reset)"

    def tearDown(self):
        LC.run_line = self._orig_run
        LC._fast_run = self._orig_fast
        LC.hw_reset = self._orig_reset

    # ---- line classification ----------------------------------------------

    def test_is_code_line(self):
        self.assertFalse(LC.is_code_line("\\ comment"))
        self.assertFalse(LC.is_code_line("( value addr -- )"))
        self.assertFalse(LC.is_code_line("   "))
        self.assertTrue(LC.is_code_line("1 1 + ."))
        self.assertTrue(LC.is_code_line(": foo 42 ;"))

    # ---- ok / error --------------------------------------------------------

    def test_ok_line(self):
        r = LC.livecheck("1 1 + .")
        self.assertTrue(r["ok"])
        self.assertEqual(r["denied"], None)
        self.assertFalse(r["locked"])

    def test_definition_line(self):
        r = LC.livecheck(": foo 42 ;")
        self.assertTrue(r["ok"])

    def test_strip_ansi(self):
        # Mecrisp wraps replies in ANSI colour codes (\x1b[36m etc.) that would
        # clutter the editor gutter.  strip_ansi removes them (Terry #251/#252).
        self.assertEqual(LC.strip_ansi("\x1b[36mok.\x1b[0m"), "ok.")
        self.assertEqual(LC.strip_ansi("1 1 + . 2  \x1b[36mok.\x1b[0m"),
                         "1 1 + . 2  ok.")
        self.assertEqual(LC.strip_ansi("no codes"), "no codes")
        self.assertEqual(LC.strip_ansi(""), "")

    def test_reset_invalidates_all(self):
        # A hardware reset wipes the WHOLE chip's RAM dictionary, so every open
        # file's history must be invalidated, not just the current one.
        LC.mark_history_valid("file:///a.fs")
        LC.mark_history_valid("file:///b.fs")
        LC.invalidate_all()
        self.assertFalse(LC.history_valid("file:///a.fs"))
        self.assertFalse(LC.history_valid("file:///b.fs"))

    def test_reset_sentinel_one_shot(self):
        # The shell reset path (F4 -> livecheck-reset.sh) touches a sentinel;
        # the LSP consumes it on the next scan and invalidates all files.  It
        # must only fire once.
        LC.mark_history_valid("file:///a.fs")
        LC.touch_reset_sentinel()
        self.assertTrue(os.path.isfile(LC._RESET_SENTINEL))
        self.assertTrue(LC.consume_reset_sentinel())
        self.assertFalse(os.path.isfile(LC._RESET_SENTINEL))
        self.assertFalse(LC.history_valid("file:///a.fs"))
        # second consume does nothing (one-shot)
        self.assertFalse(LC.consume_reset_sentinel())

    def test_redefine_warning(self):
        # Mecrisp prints 'Redefine <word>.' (still ok.) when a word is defined
        # more than once — not an error, but it wastes RAM on a small chip.
        # LiveCheck must flag it as a warning, not plain ok.
        LC._fast_run = lambda line: ": foo 43 ; \x1b[33m Redefine foo.\x1b[0m  \x1b[36mok.\x1b[0m"
        r = LC.livecheck(": foo 43 ;")
        self.assertTrue(r["ok"])
        self.assertTrue(r.get("redefine"), "redefine should be flagged")

    def test_first_definition_no_warning(self):
        LC._fast_run = lambda line: line + "  \x1b[36mok.\x1b[0m"
        r = LC.livecheck(": bar 42 ;")
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("redefine"), "first definition is not a redefine")

    def test_comment_line_trivially_ok(self):
        r = LC.livecheck("\\ just a note")
        self.assertTrue(r["ok"])  # comment = trivially fine, not sent

    # ---- flash deny ---------------------------------------------------------

    def test_deny_flash_words(self):
        for line in ("compiletoflash", "compiletoram", "cornerstone kerneltest",
                     "eraseflash", "eraseflashfrom", "flashpageerase",
                     "flashforget", ": foo compiletoflash ;"):
            r = LC.livecheck(line)
            self.assertIsNotNone(r["denied"], f"should deny: {line}")
            self.assertFalse(r["ok"])

    def test_deny_never_runs(self):
        # A denied line must NOT reach the bench.
        r = LC.livecheck("compiletoflash")
        self.assertTrue(r["denied"])
        self.assertEqual(self.reset_calls, [])  # nothing sent

    # ---- lock detection + SWD reset -----------------------------------------

    def test_locked_bench_triggers_hw_reset(self):
        # No reply = bench locked in a loop.  Forth 'reset' can't help (CPU
        # not executing); a SWD hardware reset (NRST via ST-Link) is sent.
        LC._fast_run = lambda line: ""
        r = LC.livecheck("999999999 0 do loop")
        self.assertTrue(r["locked"])
        self.assertTrue(r["reset"])
        self.assertEqual(len(self.reset_calls), 1, "SWD hardware reset sent")
        self.assertFalse(r["ok"])

    # ---- banner detection + history invalidation -----------------------------

    def test_svd_names_resolved_and_sent(self):
        # SVD register names are NOT Forth words — gema rewrites them to
        # addresses at upload.  LiveCheck RESOLVES the line through gema and
        # sends the RESOLVED form to the chip, so the chip checks the real
        # instruction ('if it passes here, upload passes').
        sent = []
        LC._fast_run = lambda line: sent.append(line) or line + " ok."
        r = LC.livecheck("1 RCC_AHBENR_IOPAEN bfs!")
        self.assertTrue(r["ok"])
        self.assertIn("resolved", r)
        self.assertEqual(sent, ["1 $40021014  17  bfs!"],
                         "SVD line resolved to addresses and sent to the chip")

    def test_svd_resolve_of_other_names(self):
        sent = []
        LC._fast_run = lambda line: sent.append(line) or line + " ok."
        r = LC.livecheck("%10 GPIOA_MODER_MODER9 bfs!")
        self.assertTrue(r["ok"])
        self.assertIn("$48000000", sent[0])
        self.assertIn("18", sent[0])

    def test_real_forth_still_sent(self):
        sent = []
        LC._fast_run = lambda line: sent.append(line) or line + " ok."
        r = LC.livecheck("1 1 + .")
        self.assertFalse(r.get("svd_skip"))
        self.assertFalse("resolved" in r)  # no SVD names -> not resolved
        self.assertTrue(r["ok"])
        self.assertEqual(sent, ["1 1 + ."])

    def test_banner_detection(self):
        self.assertTrue(LC.banner_in_reply(
            "Mecrisp-Stellaris RA 2.5.4 STM32F0 \r\n ok."))
        self.assertFalse(LC.banner_in_reply("1 1 + . ok."))
        self.assertFalse(LC.banner_in_reply(""))

    def test_banner_invalidates_history(self):
        # A reply containing the boot banner means the board just reset and
        # the RAM dictionary was wiped.
        LC._fast_run = lambda line: ("Mecrisp-Stellaris RA 2.5.4 \r\n ok.")
        LC.invalidate_history("file:///bench.fs")
        self.assertFalse(LC.history_valid("file:///bench.fs"))
        r = LC.livecheck("1 1 + .", uri="file:///bench.fs")
        self.assertTrue(r["invalidated"])
        self.assertFalse(r["ok"])

    def test_no_banner_keeps_history_valid(self):
        LC._fast_run = lambda line: line + " ok."
        LC.mark_history_valid("file:///bench.fs")
        r = LC.livecheck("1 1 + .", uri="file:///bench.fs")
        self.assertFalse(r["invalidated"])
        self.assertTrue(r["ok"])
        self.assertTrue(LC.history_valid("file:///bench.fs"))

    def test_history_per_uri(self):
        # Two open files have independent history validity.
        LC.mark_history_valid("file:///a.fs")
        LC.invalidate_history("file:///b.fs")
        self.assertTrue(LC.history_valid("file:///a.fs"))
        self.assertFalse(LC.history_valid("file:///b.fs"))

    def test_recover_marks_valid(self):
        # recover() re-runs make upload and marks history valid again.
        LC._fast_run = lambda line: line + " ok."
        LC.invalidate_history("file:///bench.fs")
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Makefile"), "w") as f:
                f.write("upload:\n\t@echo ok\n")  # trivially succeeding target
            status = LC.recover("file:///bench.fs", project_dir=d)
            self.assertIn("re-upload OK", status)
        self.assertTrue(LC.history_valid("file:///bench.fs"))


class TestLiveCheckOptIn(unittest.TestCase):
    """Opt-in + depends (#1): only files declaring '#livecheck' are checked,
    and '#depends' dependencies are checked first (same directory)."""

    @classmethod
    def setUpClass(cls):
        sys.path.append(os.path.dirname(__file__))
        import cmsis_svd_lsp as L
        cls.L = L

    def _doc(self, lines, path="/tmp/proj/main.fs"):
        return type("FakeDoc", (), {"lines": lines, "uri": "file://" + path})()

    def test_optin_required(self):
        self.assertTrue(self.L._is_opted_in(self._doc(["\\ #livecheck", "1 1 + ."])))
        self.assertTrue(self.L._is_opted_in(self._doc(["#livecheck", "1 1 + ."])))  # no backslash
        self.assertFalse(self.L._is_opted_in(self._doc(["1 1 + ."])))               # no marker

    def test_generated_never_checks(self):
        self.assertFalse(self.L._is_opted_in(self._doc(["\\ #livecheck"], "/tmp/upload.fs")))
        self.assertFalse(self.L._is_opted_in(self._doc(["\\ #livecheck"], "/tmp/bitfields_out.fs")))

    def test_depends_collected(self):
        # #depends files are in the SAME directory as the scanned file (#1).
        doc = self._doc([
            "\\ #livecheck",
            "\\ #depends dependency.fs",
            "\\ #depends util.fs",
            "1 1 + .",
        ], "/tmp/proj/main.fs")
        deps = self.L._depends_of(doc)
        self.assertIn("/tmp/proj/dependency.fs", deps)
        self.assertIn("/tmp/proj/util.fs", deps)

    def test_should_check(self):
        # SIMPLE MODE (Terry 2026-08-26): any non-generated .fs file is
        # checked — no '#livecheck' opt-in marker needed.  Generated files
        # (upload.fs, *_out.fs) are never checked.
        self.assertTrue(self.L._file_should_check(
            self._doc(["\\ #livecheck"], "/tmp/proj/main.fs")))
        self.assertTrue(self.L._file_should_check(
            self._doc(["1 1 + ."], "/tmp/proj/main.fs")))
        self.assertFalse(self.L._file_should_check(
            self._doc(["\\ #livecheck"], "/tmp/upload.fs")))
        self.assertFalse(self.L._file_should_check(
            self._doc(["\\ #livecheck"], "/tmp/bitfields_out.fs")))


if __name__ == "__main__":
    unittest.main()
