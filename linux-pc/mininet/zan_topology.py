#!/usr/bin/env python3
"""
ZAN Mininet topology — mirrors the 5-ESP32 physical layout.

Mapping:
  s1 <-> ESP32 #1 (Gateway)            represents Harare core
  s2 <-> ESP32 #2                      represents Bulawayo
  s3 <-> ESP32 #3                      represents Mutare
  s4 <-> ESP32 #4                      represents Masvingo
  s5 <-> ESP32 #5                      represents Gweru

Each switch has one host attached (a "client" at that city).
Links carry bandwidth caps so we can demonstrate congestion + QoS.
"""
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel


def build():
    net = Mininet(
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
    )

    # Remote controller = the os-ken container running with --network host
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

    # One host per switch (city client)
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    h5 = net.addHost('h5', ip='10.0.0.5/24')

    net.addLink(h1, s1)
    net.addLink(h2, s2)
    net.addLink(h3, s3)
    net.addLink(h4, s4)
    net.addLink(h5, s5)

    # Inter-switch links — bandwidth caps create realistic congestion
    # bw is in Mbps; delay simulates geographic distance
    net.addLink(s1, s2, bw=10, delay='5ms')   # Harare-Bulawayo backbone
    net.addLink(s2, s3, bw=10, delay='8ms')   # Bulawayo-Mutare backbone
    net.addLink(s1, s3, bw=5,  delay='10ms')  # Harare-Mutare redundant
    net.addLink(s3, s4, bw=8,  delay='6ms')   # Mutare-Masvingo
    net.addLink(s4, s5, bw=5,  delay='4ms')   # Masvingo-Gweru spur
    net.addLink(s1, s5, bw=8,  delay='7ms')   # Harare-Gweru direct

    net.start()

    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    build()