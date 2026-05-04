#!/usr/bin/env python3
"""
ZAN Mininet topology — mirrors the 5-ESP32 physical layout.
"""
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink, Link
from mininet.cli import CLI
from mininet.log import setLogLevel


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

    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    build()