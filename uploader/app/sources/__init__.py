"""Registry of available data sources.

Explicit imports (no dynamic discovery) so PyInstaller bundles every source
into the standalone .exe. Add new sources here and in config ``sources``.
"""

from app.sources.milking_robot import MilkingRobotSource

SOURCE_TYPES = {
    source_class.type_name: source_class
    for source_class in (MilkingRobotSource,)
}


def create_source(source_config):
    type_name = source_config.get("type")
    source_class = SOURCE_TYPES.get(type_name)
    if not source_class:
        known = ", ".join(sorted(SOURCE_TYPES))
        raise ValueError(f"Unknown source type '{type_name}' (registered: {known})")
    return source_class(source_config)
