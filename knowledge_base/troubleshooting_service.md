# Troubleshooting and Service Evidence

Troubleshooting starts with the affected station, diagnostic identifier, product or
lot, event timestamp, and current machine state. Preserve measurements before clearing
a diagnostic so later analysis can distinguish a recurring fault from an isolated
event.

## Repeated positioning failures

For recurring POS-31 positioning failures, inspect fixture movement, guide
contamination, and encoder-reference stability before considering servo settings. If
POS-31 returns after a successful reference cycle, escalate to service and attach the
AX-Y2 commanded-versus-actual position trace.

## Unstable inspection images

Flicker, blur, or changing shadows can cause inconsistent inspection classifications.
Check illuminator IL-12, lens cleanliness, exposure time, and the camera bracket before
running calibration. Calibration should begin only after the image is stable.

## Escalation package

A service escalation package should include the event log, recent measurements,
calibration or reference-cycle report, affected product and lot identifiers, and any
mechanical or parameter changes made before the problem appeared.
