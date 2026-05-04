"""
ZAN AQoSRM — Adaptive QoS Routing Mechanism.

Provides:
  - classify_flow()      : maps an IP flow to a (queue_id, meter_id) pair
  - AQoSRM               : installs OpenFlow meters on switches and dynamically
                           adjusts the bulk-traffic rate limit based on the
                           AI anomaly confidence score from the Jetson.

Queue IDs must match the OVS HTB queues configured in zan_topology.py.
Meter IDs are OpenFlow 1.3 meter table entries managed by this module.
"""
import logging

logger = logging.getLogger(__name__)

# ── Queue IDs (match OVS setup in zan_topology.py) ──────────────────────────
QUEUE_VOIP        = 0   # SIP / RTP — guaranteed minimum, highest priority
QUEUE_VIDEO       = 1   # RTSP / high-rate UDP streams
QUEUE_INTERACTIVE = 2   # HTTP/S, DNS, general traffic
QUEUE_BULK        = 3   # TCP bulk — rate-capped, lowest priority

# ── OpenFlow meter IDs (1-indexed per spec) ──────────────────────────────────
METER_BULK = 1          # single meter throttles all bulk TCP flows

# ── Rate constants (kbps) ────────────────────────────────────────────────────
_BULK_RATE_BASE  = 2000   # 2 Mbps  — applied when AI confidence = 0.0
_BULK_RATE_FLOOR =  400   # 400 kbps — floor applied when AI confidence = 1.0

# ── Port sets used by classify_flow ──────────────────────────────────────────
_SIP_PORTS  = {5060, 5061}
_RTP_PORTS  = {5004, 5005}
_RTP_DYN_LO = 16384
_RTP_DYN_HI = 32767
_RTSP_PORTS = {554, 8554}
_WEB_PORTS  = {80, 443, 8080, 8443}
_DNS_PORT   = 53


def classify_flow(ip_proto, src_port, dst_port):
    """Return (queue_id, meter_id) for the given IP flow.

    meter_id is None for flows that do not need rate-limiting by the
    controller meter table (i.e. everything except bulk TCP).

    ip_proto : int  — 6 = TCP, 17 = UDP
    src_port : int
    dst_port : int
    """
    both = {src_port, dst_port}

    if ip_proto == 17:  # UDP
        if both & _SIP_PORTS or both & _RTP_PORTS:
            return QUEUE_VOIP, None
        if (_RTP_DYN_LO <= src_port <= _RTP_DYN_HI or
                _RTP_DYN_LO <= dst_port <= _RTP_DYN_HI):
            return QUEUE_VOIP, None
        if both & _RTSP_PORTS:
            return QUEUE_VIDEO, None
        if _DNS_PORT in both:
            return QUEUE_INTERACTIVE, None

    elif ip_proto == 6:  # TCP
        if both & _WEB_PORTS:
            return QUEUE_INTERACTIVE, None
        if both & _RTSP_PORTS:
            return QUEUE_VIDEO, None
        return QUEUE_BULK, METER_BULK

    return QUEUE_INTERACTIVE, None


class AQoSRM:
    """Manages OpenFlow meters for adaptive bulk-traffic rate control.

    Usage inside ZANController:
        self.aqosrm = AQoSRM()

        # When a switch connects:
        self.aqosrm.install_meters(datapath)

        # When the Jetson POST /zan/insight arrives (Phase 4):
        self.aqosrm.update_severity(self.datapaths, confidence)
    """

    def __init__(self):
        self._bulk_rate_kbps = _BULK_RATE_BASE

    # ── Public API ────────────────────────────────────────────────────────────

    def install_meters(self, datapath):
        """Install the initial bulk-rate meter on a newly connected switch."""
        self._send_meter_mod(
            datapath,
            command=datapath.ofproto.OFPMC_ADD,
            rate=self._bulk_rate_kbps,
        )
        logger.info(
            "AQoSRM: METER_BULK installed  dpid=%-2s  rate=%d kbps",
            datapath.id, self._bulk_rate_kbps,
        )

    def update_severity(self, datapaths, confidence):
        """Adjust the bulk meter rate across all switches.

        confidence : float 0.0–1.0  (from Jetson inference-api)
          0.0 → no degradation   → rate = _BULK_RATE_BASE
          1.0 → severe anomaly   → rate = _BULK_RATE_FLOOR
        """
        new_rate = int(
            _BULK_RATE_BASE
            - (_BULK_RATE_BASE - _BULK_RATE_FLOOR) * min(max(confidence, 0.0), 1.0)
        )
        new_rate = max(new_rate, _BULK_RATE_FLOOR)

        if new_rate == self._bulk_rate_kbps:
            return

        self._bulk_rate_kbps = new_rate
        logger.info(
            "AQoSRM: severity update  confidence=%.2f  bulk_rate=%d kbps",
            confidence, new_rate,
        )
        for dp in datapaths.values():
            self._send_meter_mod(dp, command=dp.ofproto.OFPMC_MODIFY, rate=new_rate)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _send_meter_mod(self, datapath, command, rate):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        # burst_size in kbits — must cover at least one full TCP CWND (~2300 kbits)
        # so TCP bursts pass into the OVS HTB queue for smooth shaping rather than
        # being hard-dropped by the meter (which causes RTO stall-restart cycles).
        burst_size = max(rate * 2, 4000)
        bands   = [parser.OFPMeterBandDrop(rate=rate, burst_size=burst_size)]
        mod = parser.OFPMeterMod(
            datapath=datapath,
            command=command,
            flags=ofproto.OFPMF_KBPS,
            meter_id=METER_BULK,
            bands=bands,
        )
        datapath.send_msg(mod)
