#!/usr/bin/env python3
"""
ZAN Mininet topology — mirrors the 5-ESP32 physical layout.
"""
import subprocess
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink, Link
from mininet.cli import CLI
from mininet.log import setLogLevel, info, warn


def setup_qos(net):
    """Configure OVS HTB queues on every inter-switch port.

    Creates 4 queues per port matching the AQoSRM traffic classes:
      Queue 0 — VoIP        min-rate 1 Mbps  (guaranteed)
      Queue 1 — Video       min-rate 1 Mbps  (guaranteed)
      Queue 2 — Interactive min-rate 500 kbps (guaranteed)
      Queue 3 — Bulk        max-rate 2 Mbps  (rate-capped; tightened by AQoSRM meters)
    """
    info('*** Setting up QoS queues on inter-switch ports\n')
    for link in net.links:
        n1, n2 = link.intf1.node, link.intf2.node
        if not (isinstance(n1, OVSSwitch) and isinstance(n2, OVSSwitch)):
            continue
        for intf in (link.intf1, link.intf2):
            port = intf.name
            cmd = (
                f'ovs-vsctl set port {port} qos=@newqos '
                f'-- --id=@newqos create QoS type=linux-htb '
                f'queues:0=@q0 queues:1=@q1 queues:2=@q2 queues:3=@q3 '
                f'-- --id=@q0 create Queue other-config:min-rate=1000000 '
                f'-- --id=@q1 create Queue other-config:min-rate=1000000 '
                f'-- --id=@q2 create Queue other-config:min-rate=500000 '
                f'-- --id=@q3 create Queue other-config:max-rate=2000000'
            )
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                warn(f'[QoS] Could not configure {port}: {result.stderr.strip()}\n')
            else:
                info(f'[QoS] 4 queues configured on {port}\n')


def cleanup_qos(net):
    """Remove OVS QoS configuration from all inter-switch ports."""
    info('*** Cleaning up QoS queues\n')
    for link in net.links:
        n1, n2 = link.intf1.node, link.intf2.node
        if not (isinstance(n1, OVSSwitch) and isinstance(n2, OVSSwitch)):
            continue
        for intf in (link.intf1, link.intf2):
            port = intf.name
            subprocess.run(
                f'ovs-vsctl destroy QoS [$(ovs-vsctl get port {port} qos)] 2>/dev/null; '
                f'ovs-vsctl clear port {port} qos',
                shell=True, capture_output=True,
            )
    subprocess.run('ovs-vsctl --all destroy QoS; ovs-vsctl --all destroy Queue',
                   shell=True, capture_output=True)


def build():
    # No global link class — we pick per-link
    net = Mininet(
        controller=None,
        switch=OVSSwitch,
        autoSetMacs=True,
    )

    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip='127.0.0.1',
        port=6653,
    )

    # Switches
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    s3 = net.addSwitch('s3', protocols='OpenFlow13')
    s4 = net.addSwitch('s4', protocols='OpenFlow13')
    s5 = net.addSwitch('s5', protocols='OpenFlow13')

    # Hosts
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    h5 = net.addHost('h5', ip='10.0.0.5/24')

    # Host <-> switch links: plain Link (no TC shaping needed at the edge)
    net.addLink(h1, s1, cls=Link)
    net.addLink(h2, s2, cls=Link)
    net.addLink(h3, s3, cls=Link)
    net.addLink(h4, s4, cls=Link)
    net.addLink(h5, s5, cls=Link)

    # Switch <-> switch links: TCLink for bandwidth/delay shaping
    net.addLink(s1, s2, cls=TCLink, bw=10, delay='5ms')
    net.addLink(s2, s3, cls=TCLink, bw=10, delay='8ms')
    # net.addLink(s1, s3, cls=TCLink, bw=5,  delay='10ms')   # redundant — comment out for now
    net.addLink(s3, s4, cls=TCLink, bw=8,  delay='6ms')
    net.addLink(s4, s5, cls=TCLink, bw=5,  delay='4ms')
    # net.addLink(s1, s5, cls=TCLink, bw=8,  delay='7ms')    # redundant — comment out for now

    net.start()
    setup_qos(net)

    CLI(net)

    cleanup_qos(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    build()