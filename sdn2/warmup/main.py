from frrnet import frrnet_main
from frrnet.topo import FrrTopo

class MyTopo(FrrTopo):
    def build(self):
        
        # Add hosts and switches
        h1 = self.addHost('h1', ip="192.168.1.2/24", defaultRoute="via 192.168.1.1")
        s1 = self.addSwitch('s1', daemons=["bgpd"])
        s3 = self.addSwitch('s3', daemons=["bgpd"])
        s4 = self.addSwitch('s4', daemons=["bgpd"])
        s2 = self.addSwitch('s2', daemons=["bgpd"])
        h2 = self.addHost('h2', ip="192.168.2.2/24", defaultRoute="via 192.168.2.1")

        # Add links
        self.addLink(s1, s3, intf1="Ethernet1-1", intf2="Ethernet1-1", bw=10, delay="10ms")
        self.addLink(s1, s4, intf1="Ethernet1-2", intf2="Ethernet1-1", bw=10, delay="10ms")
        self.addLink(s2, s3, intf1="Ethernet1-1", intf2="Ethernet1-2", bw=10, delay="10ms")
        self.addLink(s2, s4, intf1="Ethernet1-2", intf2="Ethernet1-2", bw=10, delay="10ms")
        self.addLink(h1, s1, intf2="Ethernet1-3")
        self.addLink(h2, s2, intf2="Ethernet1-3")

if __name__ == "__main__":
    frrnet_main(MyTopo)