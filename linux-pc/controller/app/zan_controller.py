"""
ZAN SDN Controller — Phase 2 with AQoSRM.

L2 learning switch extended with:
  - Per-flow traffic classification (VoIP / Video / Interactive / Bulk)
  - OFPActionSetQueue to steer flows into the OVS HTB queues set up by
    zan_topology.py
  - OpenFlow 1.3 meters for dynamic bulk-rate limiting (adjusted by the
    Jetson AI confidence score in Phase 4 via POST /zan/insight)
"""
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ipv4, tcp, udp
from aqosrm import AQoSRM, classify_flow, QUEUE_INTERACTIVE

class ZANController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # mac_to_port[dpid][src_mac] = in_port
        self.mac_to_port = {}
        # datapaths[dpid] = datapath — kept for AQoSRM meter updates
        self.datapaths = {}
        self.aqosrm = AQoSRM()

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

        # Filter noise
        if eth.ethertype == 0x88cc:  # LLDP
            return
        if eth.dst.startswith('33:33:'):  # IPv6 multicast
            return

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        # Learn — but only update if this is a more recent observation.
        # In a topology with loops, the same src MAC arrives via multiple ports;
        # we trust the first port we see and don't keep flapping.
        if eth.src not in self.mac_to_port[dpid]:
            self.mac_to_port[dpid][eth.src] = in_port

        # Decide output
        if eth.dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][eth.dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        # CRITICAL: never send a packet back out the port it came in on
        if out_port == in_port:
            return  # drop silently — it's a loop

        # ── AQoSRM: classify flow into a priority queue ───────────────────────
        queue_id, meter_id = self._classify_packet(pkt, eth)
        actions = [
            parser.OFPActionSetQueue(queue_id),
            parser.OFPActionOutput(out_port),
        ]

        # Install flow only when we have a known destination
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
            self._add_flow(datapath, priority=1, match=match,
                           actions=actions, idle_timeout=30, meter_id=meter_id)

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