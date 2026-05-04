"""
ZAN physical-to-virtual topology mapping.

Maps ESP32 physical nodes ↔ Mininet switch datapath IDs, and
ESP32 link pairs ↔ Mininet switch pairs, as documented in Section 4
of overview.md (Physical-to-Virtual Topology Mapping).
"""

# ESP32 sensor node ID → Mininet switch datapath ID (dpid)
# The gateway (esp32 #5 in hardware) relays telemetry only — it is NOT a sensor
# node and does not appear in the mesh topology.
ESP32_TO_DPID = {
    'esp32_01': 1,
    'esp32_02': 2,
    'esp32_03': 3,
    'esp32_04': 4,
}

DPID_TO_ESP32 = {v: k for k, v in ESP32_TO_DPID.items()}

# ESP32 link pair → (dpid_a, dpid_b)
# Full mesh: every node pair has a logical link (all 4 nodes ping each other)
LINK_MAP = {
    frozenset({'esp32_01', 'esp32_02'}): (1, 2),
    frozenset({'esp32_01', 'esp32_03'}): (1, 3),
    frozenset({'esp32_01', 'esp32_04'}): (1, 4),
    frozenset({'esp32_02', 'esp32_03'}): (2, 3),
    frozenset({'esp32_02', 'esp32_04'}): (2, 4),
    frozenset({'esp32_03', 'esp32_04'}): (3, 4),
}


def esp32_link_to_dpid_pair(node_a, node_b):
    """Return (dpid_a, dpid_b) for a given ESP32 link, or None if unmapped."""
    return LINK_MAP.get(frozenset({node_a, node_b}))


def dpid_pair_to_esp32_link(dpid_a, dpid_b):
    """Return (esp32_a, esp32_b) names for a switch pair, or None if unmapped."""
    target = frozenset({dpid_a, dpid_b})
    for esp32_pair, dpid_pair in LINK_MAP.items():
        if frozenset(dpid_pair) == target:
            return tuple(esp32_pair)
    return None
