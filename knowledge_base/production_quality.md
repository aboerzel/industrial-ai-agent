# Production and Quality Records

Production records link each product to its lot, process route, station results, and
inspection outcomes. Quality decisions must use the recorded evidence for the affected
product rather than assumptions based only on the latest machine state.

## Surface inspection outcome REJECT_SURFACE

QV1 records REJECT_SURFACE when the measured surface region is classified outside the
approved appearance grade while dimensional checks still pass. Review the source
image, region identifier, classification confidence, and approved defect sample before
confirming the disposition.

## Repeated defects and lot correlation

When several products show the same defect, compare lot, fixture, station, and event
time before assigning a common cause. Lot L2409 is the demonstration lot for this
workflow. A single defect is not sufficient evidence of a lot-wide or machine-wide
problem.

## Disposition and release

Products with a confirmed reject remain quarantined until a quality engineer records
scrap, rework, or concession. After rework, the affected inspection must pass again
before the quality engineer releases the product.
