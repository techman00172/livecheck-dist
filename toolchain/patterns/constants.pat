! MODER
INPUT=%00
OUTPUT=%01
AF=%10
ANALOG=%11

! ALTERNATE FUNCTION
AF0=%0000
AF1=%0001
AF2=%0010
AF3=%0011
AF4=%0100
AF5=%0101
AF6=%0110
AF7=%0111

! OTYPER
PUSH-PULL=0
OPEN-DRAIN=1

! PUPDR
NO-PULL=%00! No pull-up or pull-down
PULL-UP=%01
PULL-DOWN=%10

! OSPEEDR
LOW-SPEED=%00
MEDIUM-SPEED=%01
HIGH-SPEED=%11

! SCB
SCB_CPUID=0xE000ED00   ! RO $410CC200 Section 4.3.1: CPUID base register (CPUID) on page 77
SCB_ICSR=0xE000ED04    ! RW(1) $00000000   Section 4.3.2: Interrupt control and state register (ICSR) on page 78
SCB_AIRCR=0xE000ED0C   ! RW(1)  $FA050000  Section 4.3.3: Application interrupt and reset control register (AIRCR) on page 80
SCB_SCR=0xE000ED10     ! RW $00000000 Section 4.3.4: System control register (SCR) on page 81
SCB_CCR=0xE000ED14     ! RW $00000204  Section 4.3.5: Configuration and control register (CCR) on p82
SCB_SHPR2=0xE000ED1C   ! RW $00000000 Section 4.3.6: System handler priority registers (SHPR2) on page 83
SCB_SHPR3=0xE000ED20   ! RW $00000000 Section 4.3.6: System handler priority registers (SHPR3) on page 83
