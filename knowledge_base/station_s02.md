# Station S02

Station S02 performs precision press-fit assembly for the P4800 product family before
the products enter downstream inspection. The station records commanded and actual
axis positions for each assembly cycle.

## Positioning fault POS-31

Fault POS-31 is raised when the vertical assembly axis AX-Y2 does not reach its target
position within tolerance. Typical causes are contamination on the linear guide, a
loose product fixture, or drift at encoder reference RZ-2. Repeated positioning
attempts must not be used to force a cycle to complete.

## Operator diagnosis

After a positioning alarm, inspect the fixture seating, the AX-Y2 guide rail, and the
encoder connector. Compare the commanded and actual positions in the cycle record. A
reference cycle may be run only after the workspace is clear; operators must not
change servo gain parameters during this check.

## Recovery verification

After the cause has been corrected, confirm successful homing against RZ-2, run one
dry cycle, and inspect the first assembled product. Release S02 only when the dry cycle
and the first-off inspection both pass.
