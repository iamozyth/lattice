"""Connectors pull hosts from other systems into Lattice."""
from app.connectors.unifi import UniFiConnector

CONNECTOR_TYPES = {UniFiConnector.type: UniFiConnector}
