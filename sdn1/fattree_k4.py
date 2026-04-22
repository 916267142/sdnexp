#!/usr/bin/env python3

# sudo python3 fattree_k4.py
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.node import OVSSwitch


ENABLE_STP = True
ENABLE_STANDALONE = True


class FatTreeK4(Topo):
    def build(self):
        # core switches
        c0_0 = self.addSwitch("c0_0", stp=ENABLE_STP)
        c0_1 = self.addSwitch("c0_1", stp=ENABLE_STP)
        c1_0 = self.addSwitch("c1_0", stp=ENABLE_STP)
        c1_1 = self.addSwitch("c1_1", stp=ENABLE_STP)

        host_id = 0
        for pod in range(4):
            # each pod has 2 aggregation + 2 edge switches
            a0 = self.addSwitch(f"a{pod}_0", stp=ENABLE_STP)
            a1 = self.addSwitch(f"a{pod}_1", stp=ENABLE_STP)
            e0 = self.addSwitch(f"e{pod}_0", stp=ENABLE_STP)
            e1 = self.addSwitch(f"e{pod}_1", stp=ENABLE_STP)

            # aggregation to core
            self.addLink(a0, c0_0)
            self.addLink(a0, c1_0)
            self.addLink(a1, c0_1)
            self.addLink(a1, c1_1)

            # edge to aggregation
            self.addLink(e0, a0)
            self.addLink(e0, a1)
            self.addLink(e1, a0)
            self.addLink(e1, a1)

            # each edge switch connects 2 hosts
            h0 = self.addHost(f"h{host_id}")
            host_id += 1
            h1 = self.addHost(f"h{host_id}")
            host_id += 1
            self.addLink(e0, h0)
            self.addLink(e0, h1)

            h2 = self.addHost(f"h{host_id}")
            host_id += 1
            h3 = self.addHost(f"h{host_id}")
            host_id += 1
            self.addLink(e1, h2)
            self.addLink(e1, h3)


def run():
    topo = FatTreeK4()
    fail_mode = "standalone" if ENABLE_STANDALONE else "secure"
    net = Mininet(topo=topo, controller=None, switch=lambda name, **params: OVSSwitch(name, failMode=fail_mode, **params))

    net.start()
    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")  # output, info, debug
    run()