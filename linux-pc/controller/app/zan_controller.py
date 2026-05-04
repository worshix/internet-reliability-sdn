"""
ZAN SDN Controller — Phase 2 baseline.

Starts as an OpenFlow 1.3 learning switch so we can verify the
controller<->Mininet plumbing works end-to-end. AQoSRM logic is
layered on top of this in steps 6-7.
"""
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet

class ZANController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # mac_to_port[dpid][src_mac] = in_port
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Install table-miss flow when a switch connects."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(
            ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
        self.logger.info("Switch connected: dpid=%s", datapath.id)

    def _add_flow(self, datapath, priority, match, actions, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
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

    actions = [parser.OFPActionOutput(out_port)]

    # Install flow only when we have a known destination
    if out_port != ofproto.OFPP_FLOOD:
        match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
        self._add_flow(datapath, priority=1, match=match,
                       actions=actions, idle_timeout=30)

    out = parser.OFPPacketOut(
        datapath=datapath,
        buffer_id=ofproto.OFP_NO_BUFFER,
        in_port=in_port,
        actions=actions,
        data=msg.data,
    )
    datapath.send_msg(out)