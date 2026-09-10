"""Run the corrected normal acceptance catalogue against a local Agent API.

This live evaluator deliberately persists only bounded transport and structured-output
metadata. It never writes prompts, answers, tool payloads, or document content.
"""

import json
import time
import urllib.error
import urllib.request
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path

from evals.run_outcome import classify_run_outcome


@dataclass(frozen=True, slots=True)
class Case:
    identifier: str
    clearance: str
    prompt: str


CASES = (
    Case(
        "UC-01",
        "PUBLIC",
        "Liste die in dieser Demo verfuegbaren Produktionsstationen auf.",
    ),
    Case(
        "UC-02",
        "INTERNAL",
        "Gib einen vollstaendigen Ueberblick ueber die mir verfuegbaren Produktionsstationen.",
    ),
    Case(
        "UC-03",
        "RESTRICTED",
        "Liste alle in dieser Demo verfuegbaren Produktionsstationen mit ihren Stations-IDs auf.",
    ),
    Case(
        "UC-04",
        "PUBLIC",
        "Liste die mir verfuegbaren Produkte auf und fasse ihren finalen Status zusammen.",
    ),
    Case(
        "UC-05",
        "INTERNAL",
        "Gib einen Ueberblick ueber die mir verfuegbaren Produkte und ihren finalen Status.",
    ),
    Case(
        "UC-06",
        "INTERNAL",
        "Gib einen Ueberblick ueber Station S02 einschliesslich ihres aktuellen Status und ihrer Rolle in der Produktion.",
    ),
    Case(
        "UC-07",
        "CONFIDENTIAL",
        "Untersuche Produkt P4801 und fasse seinen sichtbaren Produktionspfad und neuesten Status zusammen.",
    ),
    Case(
        "UC-08",
        "INTERNAL",
        "Ermittle die aktuell verfuegbaren Produktionsstationen und berichte ihren Betriebsstatus.",
    ),
    Case(
        "UC-09",
        "RESTRICTED",
        "Pruefe den aktuellen Status von Station S07 und erklaere jeden gemeldeten Fehler oder Fehlercode.",
    ),
    Case(
        "UC-10",
        "CONFIDENTIAL",
        "Ermittle kuerzlich fehlgeschlagene Produkte und fasse ihren sichtbaren Fehlerstatus zusammen.",
    ),
    Case(
        "UC-11",
        "CONFIDENTIAL",
        "Liste die Produkte auf, die Station S04 durchlaufen haben, und fasse ihren sichtbaren Verarbeitungsstatus zusammen.",
    ),
    Case(
        "UC-12",
        "PUBLIC",
        "Untersuche die Produktionshistorie von P4101 und fasse seinen abgeschlossenen Produktionspfad zusammen.",
    ),
    Case(
        "UC-13",
        "INTERNAL",
        "Untersuche, was mit Produkt P4901 passiert ist, und erklaere seinen finalen Verarbeitungsstatus sowie jeden Fehler.",
    ),
    Case(
        "UC-14",
        "CONFIDENTIAL",
        "Untersuche die vollstaendige Produktionshistorie von P4711. Fasse seine Stationsfolge, Warnungen und den finalen Fehler zusammen.",
    ),
    Case(
        "UC-15",
        "RESTRICTED",
        "Untersuche, warum Produkt P4711 an Station S04 ausgefallen ist. Pruefe die relevante Produkthistorie, Inspektionsergebnisse und Fehlercodes und nutze bei Bedarf die verfuegbare Dokumentation.",
    ),
    Case(
        "UC-16",
        "INTERNAL",
        "Untersuche die verfuegbare Historie und Fehlerdetails zu Produkt P4711 an Station S04.",
    ),
    Case(
        "UC-17",
        "CONFIDENTIAL",
        "Pruefe die Produktionshistorie von P4711 und bewerte, ob fruehere Warnungen fuer den spaeteren Fehler an Station S04 relevant sind.",
    ),
    Case(
        "UC-18",
        "CONFIDENTIAL",
        "Erklaere QUALITY-09 anhand der verfuegbaren technischen Dokumentation und fasse zusammen, was der Fehler bedeutet.",
    ),
    Case(
        "UC-19",
        "CONFIDENTIAL",
        "Erklaere anhand der verfuegbaren technischen Dokumentation, wie POSITION-ENC-02 untersucht werden sollte.",
    ),
    Case(
        "UC-20",
        "CONFIDENTIAL",
        "Suche die fuer Station S04 verfuegbare technische Dokumentation und fasse die relevante Troubleshooting-Anleitung zusammen.",
    ),
    Case(
        "UC-21",
        "CONFIDENTIAL",
        "Suche die verfuegbare Dokumentation zu Produkt P9001 an Station S07 und fasse alle zugaenglichen Hinweise zusammen.",
    ),
    Case(
        "UC-22",
        "CONFIDENTIAL",
        "Untersuche, an welcher Station P4711 ausgefallen ist, und erklaere den gemeldeten Fehlercode. Nutze die relevante Produkthistorie und Dokumentation.",
    ),
    Case(
        "UC-23",
        "CONFIDENTIAL",
        "Pruefe die frueheren Warnungen von P4711 und den aktuellen Zustand der Station, an der es ausgefallen ist. Unterscheide dabei klar zwischen Beobachtungen und Schlussfolgerungen.",
    ),
    Case(
        "UC-24",
        "RESTRICTED",
        "Untersuche Produkt P9001 an Station S07. Pruefe seine Produktionshistorie, den aktuellen Stationsstatus und die verfuegbare Dokumentation und fasse die Ergebnisse zusammen.",
    ),
    Case(
        "UC-25",
        "CONFIDENTIAL",
        "Gib die mir verfuegbaren Informationen zu Produkt P9001 einschliesslich seines aktuellen oder finalen Status an, falls zugaenglich.",
    ),
    Case(
        "UC-26",
        "CONFIDENTIAL",
        "Gib die mir verfuegbaren Informationen zu Station S07 einschliesslich ihres aktuellen Status an, falls zugaenglich.",
    ),
    Case(
        "UC-27",
        "CONFIDENTIAL",
        "Zeige die verfuegbaren Details zum Wartungsticket MT-S02-20260117 und fasse seinen sichtbaren Status und die betroffene Ausruestung zusammen.",
    ),
    Case(
        "UC-28",
        "INTERNAL",
        "Zeige die verfuegbaren Details zum Wartungsticket MT-S02-20260117 und fasse seinen sichtbaren Status und die betroffene Ausruestung zusammen.",
    ),
)


def main(output: Path, *, inter_case_delay_seconds: float = 2.0) -> None:
    if inter_case_delay_seconds < 0:
        raise ValueError("inter_case_delay_seconds must not be negative")
    with output.open("w", encoding="ascii") as report:
        for index, case in enumerate(CASES):
            started = time.monotonic()
            request = urllib.request.Request(
                "http://127.0.0.1:8000/api/v1/runs",
                data=json.dumps(
                    {
                        "message": case.prompt,
                        "user_clearance": case.clearance,
                        "response_language": "DE",
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=75) as response:
                    payload = json.loads(response.read())
                    http_status = response.status
            except urllib.error.HTTPError as error:
                payload = json.loads(error.read())
                http_status = error.code
            except (
                TimeoutError,
                json.JSONDecodeError,
                urllib.error.URLError,
            ) as error:
                payload = {"exception_type": type(error).__name__}
                http_status = None
            record = {
                "uc": case.identifier,
                "clearance": case.clearance,
                "http_status": http_status,
                "seconds": round(time.monotonic() - started, 3),
                "run_id": payload.get("run_id"),
                "run_status": payload.get("status"),
                "classification": payload.get("classification"),
                "error_code": (payload.get("error") or payload).get("code"),
                "tool_names": [
                    entry.get("tool") for entry in payload.get("tool_calls", ())
                ],
                "investigation_steps": len(payload.get("investigation_steps", ())),
                "next_steps": len(payload.get("next_steps", ())),
                "exception_type": payload.get("exception_type"),
            }
            record["acceptance_outcome"] = classify_run_outcome(
                status=payload.get("status") or "failed",
                error_code=record["error_code"],
            ).value
            report.write(json.dumps(record, ensure_ascii=True) + "\n")
            report.flush()
            # The free public provider is rate limited. Pacing belongs to this
            # live-only harness, never to Agent orchestration or production retries.
            if index < len(CASES) - 1 and inter_case_delay_seconds:
                time.sleep(inter_case_delay_seconds)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--inter-case-delay-seconds", type=float, default=2.0)
    arguments = parser.parse_args()
    main(
        arguments.output,
        inter_case_delay_seconds=arguments.inter_case_delay_seconds,
    )
