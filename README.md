# ADSB-distance-distribution
The aim of this project is to have a stand-alone system which determines at
which distances the air planes are flying by. The hardware consists of a
Raspberry Pi 0W, a USB attached SDR and an antenna. Program dump1090 is used to
read the ADS-B messages transmitted by air planes in the neighbourhood. Those
messages are passed on to python script detapd.py, which determines the minimal
distance between the air plane and a reference point while the plane is flying
by. Once the message stream of an air plane has ceased, the parameters are
logged.

A simple distribution of the distances is build. For this distribution, seven
classes are defined:
 - The air plane does not emit it's position, thus the distance is unknown;
 - The minimal distance is up to 1 [km];
 - The minimal distance is between 1 and 2 [km];
 - The minimal distance is between 2 and 4 [km];
 - The minimal distance is between 4 and 8 [km];
 - The minimal distance is between 8 and 16 [km]; and
 - The minimal distance is more than 16 [km].

The reference point should be nearby the receiver, for obvious reasons.

The results are reported to a Xymon server, which takes care of saving the
distribution data and generating the graphs.

