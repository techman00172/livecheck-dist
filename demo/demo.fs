\ livecheck-demo.fs - work through this file to learn LiveCheck.
\ Loads on the STM32F051 debug kernel (SWD ring buffer).  Open this file in
\ Helix, press F4 (reset + make upload), then work top to bottom.
\
\ HOW IT WORKS:
\   F4 = reset the board + build + upload.  Good lines get a blue check mark
\        in the gutter; bad lines get an ORANGE mark.  Hover to see why.
\   F5 = refresh the summary from the LIVE chip (no rebuild).
\   F6 = run the ( "check": ... ) asserts.
\
\ Each STEP below shows a broken line (or two).  Read the comment, fix the
\ line, press F4, and watch the orange check mark turn blue.  That is the
\ whole lesson: the chip answers you as you type.
\
\ Every bug here is REAL - each one was hit in a real session on the bench.

compiletoram

\ =====================================================================
\ STEP 1: the bare variable - it eats the 42 canary
\ =====================================================================
\ This kernel's `variable` POPS a value from the stack to initialise the
\ variable with.  A BARE `variable` (no value before it) silently eats the
\ 42 stack canary on the first call, then underflows on the next - which is
\ why the second line below fails.
\
\ FIX: put a 0 in front of each.  ( 0 variable a  0 variable b )
variable demo-a                   \ <-- FIX ME: add 0 before 'variable'
variable demo-b                   \ <-- FIX ME: add 0 before 'variable'

\ =====================================================================
\ STEP 2: `continue` does NOT exist in Mecrisp
\ =====================================================================
\ Other Forths have a `continue` word.  Mecrisp does NOT.  Using it aborts
\ the whole colon definition mid-compile and can wedge the chip.
\
\ FIX: invert the test with 0<> if ... then instead of skipping.
: count-odds
  10 0 do
    i 2 mod 0= if continue then   \ <-- FIX ME: 'continue' is not a word
    i . space
  loop ;

\ =====================================================================
\ STEP 3: the semi-colon hiding at the end of a comment line
\ =====================================================================
\ A `;` that sits AFTER a backslash comment is never read as a terminator.
\ The definition stays open, and everything after it gets swallowed into the
\ word - it can look fine on each line and then wedge the whole upload.
\
\ FIX: the `;` must be on its own line (or at least before the backslash).
: say-hi
  ." hello from say-hi " cr      \ ; <-- FIX ME: move this ; off the comment

: say-bye
  ." goodbye " cr ;

\ =====================================================================
\ STEP 4: `char` is a PARSING word - the trap no tool can catch
\ =====================================================================
\ `char` in Forth parses the NEXT word from the input stream.  So
\ `char 5 * font +` does NOT mean "char times 5 plus font" - it means
\ "the ASCII code of the word '5'", i.e. 53.  A silent logic bug.
\
\ NOTE: this one compiles CLEAN.  Every word exists, so LiveCheck and even
\ the chip accept it.  That is the honest limit of compile-time tools - and
\ it is exactly why STEP 6 (the assert) exists: to catch the code that
\ compiles fine but does the wrong thing.
\
\ FIX: leave the value on the stack and do `5 * font +` instead.
: font-addr ( char -- addr )
  char 5 * font +                \ <-- FIX ME: drop the word 'char'
  ;

create font  0 c, 0 c, 0 c, 0 c, 0 c,

\ =====================================================================
\ STEP 5: reversed bfs! operands
\ =====================================================================
\ bfs! expects ( value addr bitpos -- ).  The SVD bitfield name pushes the
\ (addr, bitpos) package, so the VALUE must come first.  Putting the name
\ first silently does the wrong thing - the editor accepts it, the chip
\ misbehaves.
\
\ FIX: value first, then the bitfield name, then bfs!
GPIOB_MODER_MODER0 %01 bfs!      \ <-- FIX ME: value first, then the name

\ =====================================================================
\ STEP 6: the assert - not just "does it compile" but "does it do the thing"
\ =====================================================================
\ A ( "check": ... ) comment on a line turns it into a live test.  The chip
\ snapshots before, runs the line, re-reads after, and reports pass/fail in
\ the gutter.  This is "did it do what I think I told it to do".
\
\ The line below should be GOOD as written - run F6 (asserts) and watch the
\ check mark stay blue.
\ ( "check": "GPIOB_ODR", "bit": "ODR0", "expect": 1 )
1 GPIOB_ODR_ODR0 bfs!

\ =====================================================================
\ DONE - every step blue, you have worked through the LiveCheck lessons.
\ =====================================================================
\ Recap of the six: canary-variable, no-continue, hidden semi-colon,
\ parsing-word char, reversed bitfield operands, and the live assert.
\ Now go write something real - the chip is listening.
