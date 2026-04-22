from frrnet import frrnet_main
from frrnet.topo import FrrTopo

class MyTopo(FrrTopo):
    def build(self):
        
        # Add hosts and switches
        leftHost = self.addHost('h1', ip="192.168.1.2/24", defaultRoute="via 192.168.1.1")
        leftSwitch = self.addSwitch('s1', daemons=["bgpd"])
        rightSwitch = self.addSwitch('s2', daemons=["bgpd"])
        rightHost = self.addHost('h2', ip="192.168.2.2/24", defaultRoute="via 192.168.2.1")

        # Add links
        self.addLink(leftSwitch, rightSwitch, intf1="Ethernet1-1", intf2="Ethernet1-1", bw=10, delay="10ms")
        self.addLink(leftHost, leftSwitch, intf2="Ethernet1-2")
        self.addLink(rightHost, rightSwitch, intf2="Ethernet1-2")

if __name__ == "__main__":
    frrnet_main(MyTopo)