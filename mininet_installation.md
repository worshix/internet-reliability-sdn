sudo apt update
sudo apt install -y mininet openvswitch-switch openvswitch-common

sudo systemctl enable --now openvswitch-switch
sudo ovs-vsctl --version
sudo mn --test pingall