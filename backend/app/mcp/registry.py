from dataclasses import dataclass

from app.config import get_settings
from app.errors import LiveAdapterNotConfigured


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    manufacturer: str
    mode: str
    models: tuple[str, ...]
    description: str
    endpoint: str | None = None


DEMO_ADAPTERS = (
    AdapterSpec(
        adapter_id="rainer-demo",
        manufacturer="Rainer",
        mode="mock",
        models=("R200", "R500"),
        description=(
            "Hypothetical demo adapter. Rainer is not contacted. "
            "Responses are labeled mock fixtures until a real credentialed schema is supplied."
        ),
    ),
    AdapterSpec(
        adapter_id="acme-demo",
        manufacturer="Acme Industrial",
        mode="mock",
        models=("P300",),
        description="Fictional Acme Industrial demo adapter. No live pump controller is contacted.",
    ),
)


class ManufacturerRegistry:
    def list_adapters(self) -> list[dict]:
        settings = get_settings()
        adapters = [
            {
                "id": item.adapter_id,
                "manufacturer": item.manufacturer,
                "mode": item.mode,
                "models": list(item.models),
                "description": item.description,
                "endpoint": item.endpoint,
                "live": False,
            }
            for item in DEMO_ADAPTERS
        ]
        live_status = "not_configured"
        live_detail = "No OEM base URL is configured."
        if settings.oem_api_base_url or settings.oem_api_schema_version or settings.oem_api_token:
            live_status = "refusing"
            live_detail = (
                "A live OEM URL or token was provided, but this build does not ship a vetted "
                "operation schema. It will not invent a real OEM endpoint."
            )
        adapters.append(
            {
                "id": "live-oem-reserved",
                "manufacturer": "unspecified",
                "mode": "live",
                "models": [],
                "description": live_detail,
                "endpoint": None,
                "live": False,
                "status": live_status,
            }
        )
        return adapters

    def resolve(self, manufacturer: str | None) -> AdapterSpec | None:
        if not manufacturer:
            return None
        key = manufacturer.strip().lower()
        for adapter in DEMO_ADAPTERS:
            if adapter.manufacturer.lower() == key or key.startswith(adapter.manufacturer.lower().split()[0]):
                if key in {"acme", "acme industrial"} and adapter.manufacturer.startswith("Acme"):
                    return adapter
                if key.startswith("rainer") and adapter.manufacturer == "Rainer":
                    return adapter
                if adapter.manufacturer.lower() == key:
                    return adapter
        return None

    def assert_live_not_guessed(self) -> None:
        settings = get_settings()
        if settings.oem_api_base_url or settings.oem_api_token:
            raise LiveAdapterNotConfigured(
                "Refusing to call an invented OEM endpoint. Register a vetted schema driver first."
            )


registry = ManufacturerRegistry()
