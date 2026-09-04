# Vision System Calibration

The QV1 vision cell uses camera CAM-12 to inspect surface regions and assembled edges
before the product proceeds to later quality checks. Stable illumination and a fixed
camera mount are prerequisites for repeatable measurements.

## CAL-42 and calibration plate

Diagnostic CAL-42 means that the stored camera calibration is invalid. Common causes
include a damaged CP-12 calibration plate, a changed lens focus, uneven illumination,
or movement of the CAM-12 mounting bracket.

## Calibration procedure

Clean the lens and CP-12 plate, stabilize the illumination, and place the plate flat in
the fixture. Run the guided calibration sequence and save the calibration record with
the camera identifier, lens setting, operator, and timestamp.

## Verification and drift

Verify a new calibration with reference part QP-REF-7. The maximum residual must be no
greater than 0.15 mm across the inspected field. Repeated edge offsets or declining
feature confidence indicate calibration drift and require a new diagnostic record.
