# Station S04

Station S04 performs the final automated quality inspection after products pass
stations S01 and S02. A failed inspection prevents the affected product from completing
production.

## Fault state and E-STOP-17

The demo production history records product P4711 as failed at station S04 with error
code E-STOP-17. While this error is active, the current machine state is FAULTED and
production must not resume.

## Operational checks

For an E-STOP-17 event at S04, operators should check the emergency-stop buttons and
the protective guard circuit. The station must remain stopped until the safety circuit
is closed and the active error has been cleared by qualified personnel.
