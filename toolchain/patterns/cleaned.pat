! Cleans up the STM32 SVD's by removing newlines and whitespace inside descriptions
! Terry Porter 8Feb2023

! get rid of all leading whitespace
\N\W=

! Remove newlines and whitespace inside description fields
\<description\>*\n\W*\<\/description\>\n=<description\>$1</description>\n

! change 0x to $ to be Forth friendly
0x<X>=\$$1

