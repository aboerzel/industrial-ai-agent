"""FC01: ticket reads fail closed when RLS hides the mandatory station relation."""

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from threading import get_ident
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, joinedload

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    _append_observation_identifiers,
    _extract_classification,
)
from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.persistence.models import (
    FactoryRecord,
    MaintenanceTicketRecord,
    StationRecord,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlFactoryDiscoveryRepository,
    PostgreSqlMachineStatusRepository,
    PostgreSqlMaintenanceTicketRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

pytestmark = pytest.mark.skipif(
    not os.getenv("FACTORY_DATABASE_URL")
    or not os.getenv("FACTORY_DATABASE_ADMIN_URL"),
    reason="requires isolated PostgreSQL app/admin fixtures",
)
LABELS = DataClassification
UNKNOWN = "MT-FFFFFFFFFFFF"
SUMMARY = "Synthetic FC01 independently classified ticket"
RUN_ID = UUID("c1010000-0000-4000-8000-000000000001")
GENERATION = "c1010000-0000-4000-8000-000000000002"


def context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext("synthetic-fc01-reader", ("reader",), clearance, True)


@dataclass(frozen=True)
class TicketCase:
    ticket: str
    station_code: str
    station_id: UUID
    source: int
    station_label: int
    request: str


@dataclass
class Rows:
    factory: PostgreSqlSessionFactory
    admin: Engine
    cases: tuple[TicketCase, ...]

    def repository(self, clearance):
        return PostgreSqlMaintenanceTicketRepository(self.factory, context(clearance))

    def server(self, clearance):
        security = context(clearance)
        return create_factory_mcp_server(
            product_history=ProductHistoryCapability(
                PostgreSqlProductHistoryRepository(self.factory, security)
            ),
            machine_status=MachineStatusCapability(
                PostgreSqlMachineStatusRepository(self.factory, security)
            ),
            factory_discovery=FactoryDiscoveryCapability(
                PostgreSqlFactoryDiscoveryRepository(self.factory, security)
            ),
            maintenance_ticket=MaintenanceTicketCapability(self.repository(clearance)),
        )


@pytest.fixture(scope="module")
def rows() -> Iterator[Rows]:
    url = make_url(os.environ["FACTORY_DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost"} or not (
        url.database and url.database.startswith("verification_")
    ):
        pytest.skip("FC01 fixtures require an isolated verification database")
    factory = PostgreSqlSessionFactory(os.environ["FACTORY_DATABASE_URL"])
    admin = create_engine(os.environ["FACTORY_DATABASE_ADMIN_URL"])
    factory_id = uuid4()
    cases = tuple(
        TicketCase(ticket, code, uuid4(), source, station, request)
        for ticket, code, source, station, request in (
            ("MT-S86-20261015", "S86", 0, 2, "synthetic-fc01-exact-review"),
            ("MT-C10100000001", "S87", 1, 2, "synthetic-fc01-internal"),
            (
                "MT-C10100000002",
                "S88",
                1,
                3,
                sha256(f"{RUN_ID}:{GENERATION}".encode()).hexdigest(),
            ),
        )
    )
    try:
        with Session(admin) as session, session.begin():
            session.add(
                FactoryRecord(
                    id=factory_id, code="FC01", name="Synthetic FC01", classification=0
                )
            )
            session.flush()
            for case in cases:
                session.add(
                    StationRecord(
                        id=case.station_id,
                        factory_id=factory_id,
                        code=case.station_code,
                        name="FC01 protected station name",
                        classification=case.station_label,
                    )
                )
            session.flush()
            for case in cases:
                session.add(
                    MaintenanceTicketRecord(
                        id=uuid4(),
                        station_id=case.station_id,
                        ticket_code=case.ticket,
                        request_id=case.request,
                        status="FC01-OPEN",
                        summary=SUMMARY,
                        classification=case.source,
                    )
                )
        yield Rows(factory, admin, cases)
    finally:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM maintenance_ticket WHERE station_id IN (SELECT id FROM station WHERE factory_id=:id)"
                ),
                {"id": factory_id},
            )
            connection.execute(
                text("DELETE FROM station WHERE factory_id=:id"), {"id": factory_id}
            )
            connection.execute(
                text("DELETE FROM factory WHERE id=:id"), {"id": factory_id}
            )
        factory.dispose()
        admin.dispose()


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("clearance", tuple(LABELS))
def test_real_rls_fk_and_visibility_optional_relation(rows, index, clearance):
    """FC01-01/06/07/08/13: the FK exists despite an absent joined relation."""
    case = rows.cases[index]
    with rows.admin.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM maintenance_ticket t JOIN station s ON s.id=t.station_id WHERE t.ticket_code=:code"
                ),
                {"code": case.ticket},
            )
            == 1
        )
    with rows.factory.session(context(clearance)) as session:
        assert session.scalar(text("SELECT current_user")) == "factory_app"
        assert not session.scalar(
            text(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
        )
        assert all(
            session.scalars(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname IN ('maintenance_ticket', 'station')"
                )
            )
        )
        record = session.scalar(
            select(MaintenanceTicketRecord)
            .options(joinedload(MaintenanceTicketRecord.station))
            .where(MaintenanceTicketRecord.ticket_code == case.ticket)
        )
        assert (record is not None) == (clearance >= case.source)
        station = session.scalar(
            select(StationRecord).where(StationRecord.id == case.station_id)
        )
        assert (station is not None) == (clearance >= case.station_label)
        if record is not None:
            assert record.station_id == case.station_id
            assert (record.station is not None) == (clearance >= case.station_label)


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("clearance", tuple(LABELS))
def test_ticket_and_request_reads_neutral_or_fc02_visible_projection(
    rows, index, clearance
):
    """FC01-02..05/09..12/15: all three output layers and alternate read agree."""
    case = rows.cases[index]
    repository = rows.repository(clearance)
    by_id = repository.get_maintenance_ticket(MaintenanceTicketId(case.ticket))
    by_request = repository.get_maintenance_ticket_by_request_id(
        MaintenanceTicketRequestId(case.request)
    )
    capability = MaintenanceTicketCapability(repository)
    projected = capability.get_maintenance_ticket(case.ticket)
    wire = asyncio.run(
        rows.server(clearance).call_tool(
            "get_maintenance_ticket", {"ticket_id": case.ticket}
        )
    )
    assert not wire.is_error
    payload = wire.structured_content
    assert payload == projected.model_dump(mode="json")
    references = []
    _append_observation_identifiers(
        references, "get_maintenance_ticket", json.dumps(payload)
    )
    if clearance < case.station_label or clearance < case.source:
        assert by_id is by_request is None
        unknown = capability.get_maintenance_ticket(UNKNOWN).model_dump(mode="json")
        # The fixed neutral label is schema-owned, never the hidden station label.
        assert payload == {**unknown, "ticket_id": case.ticket}
        assert payload == {
            "ticket_id": case.ticket,
            "found": False,
            "status": None,
            "station_id": None,
            "summary": None,
            "classification": 2,
        }
        assert all(reference.value != case.station_code for reference in references)
        assert str(case.station_id) not in json.dumps(payload)
        assert "FC01 protected station name" not in json.dumps(payload)
    else:
        assert by_id == by_request
        assert by_id.station_id.value == case.station_code
        assert by_id.classification == LABELS(max(case.source, case.station_label))
        assert payload == {
            "ticket_id": case.ticket,
            "found": True,
            "status": "FC01-OPEN",
            "station_id": case.station_code,
            "summary": SUMMARY,
            "classification": int(by_id.classification),
        }
        assert _extract_classification(json.dumps(payload)) == by_id.classification
        assert any(reference.value == case.station_code for reference in references)


def test_station_reclassification_changes_read_visibility_without_changing_fk(rows):
    case = rows.cases[1]
    repository = rows.repository(LABELS.CONFIDENTIAL)
    assert (
        repository.get_maintenance_ticket(MaintenanceTicketId(case.ticket)) is not None
    )
    try:
        with rows.admin.begin() as connection:
            connection.execute(
                text("UPDATE station SET classification=3 WHERE id=:id"),
                {"id": case.station_id},
            )
        assert (
            repository.get_maintenance_ticket(MaintenanceTicketId(case.ticket)) is None
        )
        assert (
            repository.get_maintenance_ticket_by_request_id(
                MaintenanceTicketRequestId(case.request)
            )
            is None
        )
    finally:
        with rows.admin.begin() as connection:
            connection.execute(
                text("UPDATE station SET classification=2 WHERE id=:id"),
                {"id": case.station_id},
            )
    assert (
        repository.get_maintenance_ticket(
            MaintenanceTicketId(case.ticket)
        ).classification
        == LABELS.CONFIDENTIAL
    )


@pytest.mark.parametrize("clearance", (LABELS.CONFIDENTIAL, LABELS.RESTRICTED))
def test_consumed_generation_reads_existing_result_without_writes(rows, clearance):
    """A fake consumed claim exercises real RLS replay I/O without creating a ticket."""
    case = rows.cases[2]
    loop_thread = get_ident()
    owner_threads = []

    class ReadOnlyReplayRepository(PostgreSqlMaintenanceTicketRepository):
        def create_maintenance_ticket(self, *args):
            pytest.fail("Consumed generation must not write")

        def get_maintenance_ticket_by_request_id(self, request):
            owner_threads.append(get_ident())
            return super().get_maintenance_ticket_by_request_id(request)

    class ConsumedClaim:
        async def claim_approved_action(self, claim, security):
            assert claim.run_id == RUN_ID
            return False

        async def is_consumed_approved_action(self, claim, security):
            return True

    capability = MaintenanceTicketCapability(
        ReadOnlyReplayRepository(rows.factory, context(clearance)),
        approval_claims=ConsumedClaim(),
    )

    async def replay():
        operation = capability.create_maintenance_ticket(
            GENERATION,
            case.station_code,
            SUMMARY,
            run_id=RUN_ID,
            security_context=context(clearance),
        )
        if clearance < case.station_label:
            with pytest.raises(
                PermissionError, match="^Protected action is not authorized$"
            ):
                await operation
        else:
            result = await operation
            assert result.ticket_id == case.ticket
            assert result.station_id == case.station_code

    asyncio.run(replay())
    assert owner_threads and loop_thread not in owner_threads


@pytest.mark.parametrize("alternate", (False, True))
def test_hidden_relation_needs_only_one_caller_scoped_joined_select(rows, alternate):
    statements = []

    def track(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    # Observe the application pool only; fixture/admin access never participates.
    engine = rows.factory._engine
    event.listen(engine, "before_cursor_execute", track)
    try:
        case = rows.cases[1]
        repository = rows.repository(LABELS.INTERNAL)
        result = (
            repository.get_maintenance_ticket_by_request_id(
                MaintenanceTicketRequestId(case.request)
            )
            if alternate
            else repository.get_maintenance_ticket(MaintenanceTicketId(case.ticket))
        )
        assert result is None
    finally:
        event.remove(engine, "before_cursor_execute", track)
    selects = [
        statement for statement in statements if "FROM maintenance_ticket" in statement
    ]
    assert len(selects) == 1 and "LEFT OUTER JOIN station" in selects[0]
    assert not any("SET ROLE" in statement.upper() for statement in statements)
