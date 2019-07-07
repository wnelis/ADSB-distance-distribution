# ADSB-distance-distribution

## Project description
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

## Installation
Download script detapd.py and save it at a convenient location on your Raspberry
Pi. It is advised to use a separate map, as a log of planes having passed is
created in the directory in which the script is located. (Note: 'detapd' is
short for 'DETermine_Air_Plane_Distance'.)

At the beginning of script detapd.py there is a section entitled "Configuration
parameters". In this section two items need to be set.

The first one is the (location of) the reference point. This location is
normally the location of the receiver. As the messages of air planes up to tens
of kilometres away can be received even with the simplest of antennas, a
reasonable accurate result can be obtained if the distance between the reference
point and the location of the receiver is less than a few kilometres.

The second item to set is the invocation of program dump1090. If socket
TCP/30003 is not available, script detapd.py uses this definition to start
program dump1090. The path to this program needs to be set.

After setting these configation parameters, the script is ready to go.

## Example
The graphs below show the results as collected and presented by Xymon. The
graphs show averages over an half hour. Thus a measurement showing a message
rate of 50 messages per second implies the reception of 50 * 1800 = 90000
messages.

<img src="https://raw.githubusercontent.com/wnelis/ADSB-distance-distribution/docs/Message.rate.png">

