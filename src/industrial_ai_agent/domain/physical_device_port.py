"""Inner port for bounded physical-device capabilities."""

from typing import Protocol

from industrial_ai_agent.domain.physical_device import (
    DeviceCapability,
    DeviceId,
    DeviceOperation,
    DeviceOperationResult,
    DeviceState,
)


class PhysicalDevicePort(Protocol):
    """Adapter boundary invoked only after the owning use case applies its policy."""

    def inspect_capabilities(self, device_id: DeviceId) -> tuple[DeviceCapability, ...]:
        """Return the bounded capabilities advertised by one physical device."""

    def read_state(self, device_id: DeviceId) -> DeviceState:
        """Read the current bounded device state."""

    def execute_operation(self, operation: DeviceOperation) -> DeviceOperationResult:
        """Execute one bounded, already-authorized device operation."""

    def read_resulting_state(self, device_id: DeviceId) -> DeviceState:
        """Read state after an operation for independent recovery verification."""
