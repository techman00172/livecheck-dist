
! GENERAL
! remove all Stack Comments
(*)=

! align all source on left margin (remove any leading whitespace) 
\N\W=


! COMMENT REMOVAL
! ------------------------------------------------------------------
! remove all comments on newlines
\N\\*\n=

! remove all comments on newlines with leading whitespace (spaces or tabs)
\N\W\\*\n=

! remove inline comments with leading whitespace. replace newline.
\W\\*\n=\n


! BLANK LINE REMOVAL
! -------------------------------------------------------------------
! remove blank lines without whitespace
\N\n=

! remove blank lines with whitespace
\N\W\n=


