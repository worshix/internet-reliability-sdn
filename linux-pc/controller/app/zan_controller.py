"""
ZAN SDN Controller — Phase 4 with AQoSRM + AI-insight REST endpoint.

Extensions over Phase 2:
  - WSGI REST server on port 8080
      POST /zan/insight        — receives AI anomaly from Jetson; triggers reroute
      GET  /zan/network-status — returns current topology state
      POST /zan/clear-degraded — manually clear degraded link set
  - BFS path rerouting: avoids degraded inter-switch links
  - Degraded-port-aware flooding (selective explicit-port flood)
"""
import json
from collections import defaultdict, deque

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ipv4, tcp, udp
from os_ken.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response

from aqosrm import AQoSRM, classify_flow, QUEUE_INTERACTIVE
from topology_map import LINK_MAP

# ── Mininet inter-switch port map ─────────────────────────────────────────────
# Derived from zan_topology.py link-addition order (with s1-s3 active):
#   host links first: h1-s1, h2-s2, h3-s3, h4-s4, h5-s5  (each gets port 1)
#   then inter-switch: s1-s2, s2-s3, s1-s3, s3-s4, s4-s5
# Key: (low_dpid, high_dpid)  →  (port_on_low, port_on_high)
INTER_SWITCH_PORTS = {
    (1, 2): (2, 2),
    (2, 3): (3, 2),
    (1, 3): (3, 3),
    (3, 4): (4, 2),
    (4, 5): (3, 2),
}

# Adjacency graph: dpid → {neighbor_dpid: out_port}
_TOPO = defaultdict(dict)
for (_da, _db), (_pa, _pb) in INTER_SWITCH_PORTS.items():
    _TOPO[_da][_db] = _pa
    _TOPO[_db][_da] = _pb


def _bfs_path(src, dst, blocked):
    """BFS shortest path from src to dst dpid, avoiding blocked frozenset links."""
    if src == dst:
        return [src]
    visited = {src}
    queue = deque([[src]])
    while queue:
        path = queue.popleft()
        for nbr in _TOPO.get(path[-1], {}):
            if nbr not in visited and frozenset({path[-1], nbr}) not in blocked:
                new_path = path + [nbr]
                if nbr == dst:
                    return new_path
                visited.add(nbr)
                queue.append(new_path)
    return None


# ── REST API ──────────────────────────────────────────────────────────────────

class ZANRestAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self._app = data['zan_app']

    @route('insight', '/zan/insight', methods=['POST'])
    def post_insight(self, req, **kwargs):
        try:
            body = json.loads(req.body)
        except Exception:
            return Response(status=400, content_type='application/json',
                            body=json.dumps({'error': 'invalid JSON'}))
        self._app.handle_insight(body)
        return Response(content_type='application/json',
                        body=json.dumps({'status': 'ok'}))

    @route('status', '/zan/network-status', methods=['GET'])
    def get_status(self, req, **kwargs):
        return Response(content_type='application/json',
                        body=json.dumps(self._app.get_network_status()))

    @route('clear', '/zan/clear-degraded', methods=['POST'])
    def clear_degraded(self, req, **kwargs):
        self._app.degraded_links.clear()
        self._app.logger.info("Degraded links cleared via REST")
        return Response(content_type='application/json',
                        body=json.dumps({'status': 'cleared'}))


# ── Controller ────────────────────────────────────────────────────────────────

class ZANController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.aqosrm = AQoSRM()
        self.degraded_links = set()   # set of frozenset({dpid_a, dpid_b})
        self.insight_log = []         # last 50 insights

        kwargs['wsgi'].register(ZANRestAPI, {'zan_app': self})

    # ── helpers ───────────────────────────────────────────────────────────────

    def _degraded_ports(self, dpid):
        """Return the set of inter-switch ports at dpid that are on degraded links."""
        ports = set()
        for link in self.degraded_links:
            lst = sorted(link)
            da, db = lst[0], lst[1]
            key = (da, db)
            if key not in INTER_SWITCH_PORTS:
                continue
            pa, pb = INTER_SWITCH_PORTS[key]
            if dpid == da:
                ports.add(pa)
            elif dpid == db:
                ports.add(pb)
        return ports

    def _alternate_port(self, dpid, blocked_port):
        """Return an alternate output port around the blocked inter-switch port."""
        blocked_nbr = None
        for (da, db), (pa, pb) in INTER_SWITCH_PORTS.items():
            if dpid == da and pa == blocked_port:
                blocked_nbr = db
                break
            if dpid == db and pb == blocked_port:
                blocked_nbr = da
                break
        if blocked_nbr is None:
            return None
        path = _bfs_path(dpid, blocked_nbr, self.degraded_links)
        if path and len(path) >= 2:
            nxt = path[1]
            for (da, db), (pa, pb) in INTER_SWITCH_PORTS.items():
                if dpid == da and nxt == db:
                    return pa
                if dpid == db and nxt == da:
                    return pb
        return None

    def _clear_switch(self, datapath):
        """Delete all flows and reset mac learning for this datapath."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=parser.OFPMatch(),
        ))
        # Reinstall table-miss so traffic still punts to controller
        self._add_flow(datapath, priority=0,
                       match=parser.OFPMatch(),
                       actions=[parser.OFPActionOutput(
                           ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)])
        self.mac_to_port.pop(datapath.id, None)

    # ── REST handlers ─────────────────────────────────────────────────────────

    def handle_insight(self, body):
        """Called by ZANRestAPI when POST /zan/insight is received."""
        nodes = body.get('nodes', [])
        insight_type = body.get('type', 'UNKNOWN')
        confidence = body.get('confidence', 0.0)

        self.logger.warning(
            "AI INSIGHT [%s] nodes=%s conf=%.3f", insight_type, nodes, confidence
        )

        # Keep a rolling log
        self.insight_log = (self.insight_log + [body])[-50:]

        if len(nodes) == 2:
            link_key = frozenset(nodes)
            if link_key in LINK_MAP:
                dpid_a, dpid_b = LINK_MAP[link_key]
                self.degraded_links.add(frozenset({dpid_a, dpid_b}))
                self._reroute(dpid_a, dpid_b)
            else:
                self.logger.warning("Insight nodes %s not in LINK_MAP", nodes)

    def _reroute(self, dpid_a, dpid_b):
        """Clear flows on the two endpoints so traffic re-learns around the bad link."""
        for dpid in (dpid_a, dpid_b):
            dp = self.datapaths.get(dpid)
            if dp:
                self._clear_switch(dp)
                self.logger.info("Cleared flows on dpid=%d for reroute", dpid)
            else:
                self.logger.warning("dpid=%d not connected, cannot reroute", dpid)

    def get_network_status(self):
        return {
            'connected_switches': list(self.datapaths.keys()),
            'degraded_links': [list(lnk) for lnk in self.degraded_links],
            'recent_insights': self.insight_log[-10:],
        }

    # ── OpenFlow handlers ─────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Clear stale state, then install table-miss flow and AQoSRM meters."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.datapaths[datapath.id] = datapath

        # Delete all flows left from a previous controller session
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=parser.OFPMatch(),
        ))

        # Delete all meters left from a previous controller session
        datapath.send_msg(parser.OFPMeterMod(
            datapath=datapath,
            command=ofproto.OFPMC_DELETE,
            flags=0,
            meter_id=ofproto.OFPM_ALL,
            bands=[],
        ))

        # Reinstall table-miss flow
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(
            ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)

        self.aqosrm.install_meters(datapath)
        self.logger.info("Switch connected: dpid=%s", datapath.id)

    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, meter_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = []
        if meter_id is not None:
            inst.append(parser.OFPInstructionMeter(meter_id))
        inst.append(parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions))
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
        )
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == 0x88cc:  # LLDP
            return
        if eth.dst.startswith('33:33:'):  # IPv6 multicast
            return

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        if eth.src not in self.mac_to_port[dpid]:
            self.mac_to_port[dpid][eth.src] = in_port

        bad_ports = self._degraded_ports(dpid)

        # Resolve output port
        if eth.dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][eth.dst]
            # Redirect if learned port is now on a degraded link
            if out_port in bad_ports:
                alt = self._alternate_port(dpid, out_port)
                if alt:
                    self.logger.info(
                        "dpid=%d: rerouting %s via port %d (was %d, degraded)",
                        dpid, eth.dst, alt, out_port,
                    )
                    out_port = alt
                    self.mac_to_port[dpid][eth.dst] = alt
                else:
                    return  # no alternate path — drop
        else:
            out_port = ofproto.OFPP_FLOOD

        if out_port == in_port:
            return

        queue_id, meter_id = self._classify_packet(pkt, eth)

        # Build action list
        if out_port == ofproto.OFPP_FLOOD and bad_ports:
            # Selective flood: skip degraded ports
            actions = [parser.OFPActionSetQueue(queue_id)]
            for port_no, _ in datapath.ports.items():
                if port_no != in_port and port_no not in bad_ports \
                        and port_no < 0xFFF0:
                    actions.append(parser.OFPActionOutput(port_no))
            if not actions[1:]:
                return  # no ports left
        else:
            actions = [
                parser.OFPActionSetQueue(queue_id),
                parser.OFPActionOutput(out_port),
            ]
            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(
                    in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
                self._add_flow(datapath, priority=1, match=match,
                               actions=actions, idle_timeout=30,
                               meter_id=meter_id)

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data,
        )
        datapath.send_msg(out)

    def _classify_packet(self, pkt, eth):
        """Return (queue_id, meter_id) for the packet using L3/L4 info."""
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            return QUEUE_INTERACTIVE, None

        tcp_pkt = pkt.get_protocol(tcp.tcp)
        if tcp_pkt:
            return classify_flow(6, tcp_pkt.src_port, tcp_pkt.dst_port)

        udp_pkt = pkt.get_protocol(udp.udp)
        if udp_pkt:
            return classify_flow(17, udp_pkt.src_port, udp_pkt.dst_port)

        return QUEUE_INTERACTIVE, None