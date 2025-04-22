Testbed Resources
----------------------

FEDGEN testbed cloud resources include servers which are being increased on an annual basis. 
The FEDGEN cloud testbed has very similar hardware with specific processors in variety of configuration in memory capacity or number of CPUs. 
All the servers share resources over networks for data storage and inter communication.

Software Manager
=====================

FEDGEN Cloud Testbed employs the use of Proxmox virtualisation software to manage
the provisioning of Virtual Machines (VMs) for experimental purposes.

Operating Software
==========================

VMs spawned on FEDGEN cloud testbeds currently use Ubuntu 22.04.* .


Servers Specicication
============================

+--------------+------------+---------------------------+-------+---------+-----------+------------------------------------------+----------------+------------+
| Region       | Node Count | Processors (Architecture) | Cores | Memory  | Disk Size | GPUs (Number)                            | Node Name      | Model      |
+==============+============+===========================+=======+=========+===========+==========================================+================+============+
| 1,2,3        | 24         | Intel (R) Xeon Silver     | 384   | 384 GB  | 72 TB     |                                          |                | R740       |
|              |            | Hyperthreading Enabled    |       |         |           |                                          |                |            |
|              |            | 4110 2.10GHz              |       |         |           |                                          |                |            |
+--------------+------------+---------------------------+-------+---------+-----------+------------------------------------------+----------------+------------+
|  4           | 6          | Intel(R) Xeon Silver      | 16    |  16 GB  | 3 TB      |                                          |                | R750       |
|              |            | 4110 2.10GHz              |       |         |           |                                          |                |            |
+--------------+------------+---------------------------+-------+---------+-----------+------------------------------------------+----------------+------------+



Networks (Interconnect)
=============================

All servers are connected to a 1Gb Ethernet network for communications 


Storage
===============

Each server has 3T storage, totally 18TB on each region
