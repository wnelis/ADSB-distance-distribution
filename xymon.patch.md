# Xymon

This article describes patches for Xymon to have it store and display up 11
years of collected data.


## A very brief introduction

Xymon is a network monitoring tool, which I use to handle the status and status
changes and to store the collected data. The data (time series) is stored in
multiple 'round robin databases' (RRDs, see URL https://oss.oetiker.ch/rrdtool/).
An RRD exists of a set of data-sets (DSes) and a set of 'round robin archives'
(RRAs), which contain a fixed number of data points. Those data points in turn
are derived from the original measurements (primary data points, PDPs) using a
consolidation function. In the consolidation function, the type (minimum,
maximum or average) is specified as well as the number of PDPs making up one
data point. If the frequency of the measurements is once per 5 minutes, the
default in Xymon, and the number of PDPs per data-point is set to 288, one
data-point in the resulting RRA is the minimum, maximum or average of 24 hours
of measurements.


## Default xymon configuration w.r.t. RRD

The (default) configuration of an RRD in Xymon is defined in file
rrddefinitions.cfg. The relevant part of this file is:

```
  # This one is the default setup. You can change it, if you like.
  []
        # 576 datapoints w/ 5 minute interval = 48 hours @ 5 min avg.
        RRA:AVERAGE:0.5:1:576
        # 576 datapoints w/ 6*5 minute averaged = 12 days @ 30 min avg.
        RRA:AVERAGE:0.5:6:576
        # 576 datapoints w/ 24*5 minute averaged = 48 days @ 2 hour avg.
        RRA:AVERAGE:0.5:24:576
        # 576 datapoints w/ 288*5 minute averaged = 576 days @ 1 day avg.
        RRA:AVERAGE:0.5:288:576
```

With an increased number of PDPs per data point, the level of detail becomes
less but the period covered increases. Saving the data takes a fixed and
relatively small amount of storage. The size of one RRD is typically between 40
[kiB] and 500 [kiB].


## Extending the period saved in the RRDs

Using the default definitions of the RRAs, up to 576 days, which is about
1.58 years, worth of data can be stored. I want to increase this period to
multiple years. Thus an additional RRA is needed.

If the number of data points in the additional RRA is also 576, the graphs
generated from each RRA will have the same size on the screen, which looks nice.

The choice of the integration period, that is the number of PDPs per data point,
is bounded to be in the range of about 4 to 12 times 288. I have chosen for 7
times 288 = 2016, as this covers one complete week. Many processes have a weekly
rhythm, for instance a higher value on Monday through Friday and a lower value
on Saturday and Sunday. An integration period of one week will remove this
variation in first order from the results.

Thus the additional RRA will contain 576 data points, each containing the
aggregated value of one week worth of measurements. This RRA thus covers a
period of 4032 days, which is 11.04 years.


## Patches

The default section of file rrddefinitions.cfg becomes:

```
  # This one is the default setup. You can change it, if you like.
  []
        # 576 datapoints w/ 5 minute interval = 48 hours @ 5 min avg.
        RRA:AVERAGE:0.5:1:576
        # 576 datapoints w/ 6*5 minute averaged = 12 days @ 30 min avg.
        RRA:AVERAGE:0.5:6:576
        # 576 datapoints w/ 24*5 minute averaged = 48 days @ 2 hour avg.
        RRA:AVERAGE:0.5:24:576
        # 576 datapoints w/ 288*5 minute averaged = 576 days @ 1 day avg.
        RRA:AVERAGE:0.5:288:576
        # 576 datapoints 2/ 2016*5 minute averaged = 11 years @ 1 week avg.
        RRA:AVERAGE:0.5:2016:576
```

Existing RRDs can be extended using `rrdtool`:

```
rrdtool tune <rrd_file_name> RRA:<consolidation_type>:0.5:2016:576
```

Only program showgraph.c needs to be patched, to show the additional RRA too.
The patches for this program are:

```
wim@TIC-IV ~/ADSB $ diff -u showgraph.c showgraph.new.c 
--- showgraph.c	2019-07-31 09:48:31.071982709 +0200
+++ showgraph.new.c	2019-07-30 13:00:44.848289379 +0200
@@ -36,6 +36,9 @@
 #define DAY_GRAPH   "e-12d"
 #define WEEK_GRAPH  "e-48d"
 #define MONTH_GRAPH "e-576d"
+#define YEAR_GRAPH  "e-4032d"
+
+#define DATE_FORMAT "%Y-%m-%d"
 
 /* RRDtool 1.0.x handles graphs with no DS definitions just fine. 1.2.x does not. */
 #ifdef RRDTOOL12
@@ -262,6 +265,12 @@
 				gtype = strdup(cwalk->value);
 				glegend = "Last 576 Days";
 			}
+			else if (strcmp(cwalk->value, "yearly") == 0) {
+				period = YEAR_GRAPH;
+				persecs = 4032*24*60*60;
+				gtype = strdup(cwalk->value);
+				glegend = "Last 11 Years";
+			}
 			else if (strcmp(cwalk->value, "custom") == 0) {
 				period = NULL;
 				persecs = 0;
@@ -326,8 +335,8 @@
 
 		persecs = (graphend - graphstart);
 
-		strftime(t1, sizeof(t1), "%d/%b/%Y", localtime(&graphstart));
-		strftime(t2, sizeof(t2), "%d/%b/%Y", localtime(&graphend));
+		strftime(t1, sizeof(t1), DATE_FORMAT, localtime(&graphstart));
+		strftime(t2, sizeof(t2), DATE_FORMAT, localtime(&graphend));
 		glegend = (char *)malloc(40);
 		snprintf(glegend, 40, "%s - %s", t1, t2);
 	}
@@ -783,6 +792,7 @@
 	graph_link(stdout, selfURI, "daily",    12*24*60*60);
 	graph_link(stdout, selfURI, "weekly",   48*24*60*60);
 	graph_link(stdout, selfURI, "monthly", 576*24*60*60);
+	graph_link(stdout, selfURI, "yearly", 4032*24*60*60);
 
 	fprintf(stdout, "</table>\n");
 
@@ -1179,9 +1189,9 @@
 	}
 
 #ifdef RRDTOOL12
-	strftime(timestamp, sizeof(timestamp), "COMMENT:Updated\\: %d-%b-%Y %H\\:%M\\:%S", localtime(&now));
+	strftime(timestamp, sizeof(timestamp), "COMMENT:Updated\\: " DATE_FORMAT " %H\\:%M\\:%S", localtime(&now));
 #else
-	strftime(timestamp, sizeof(timestamp), "COMMENT:Updated: %d-%b-%Y %H:%M:%S", localtime(&now));
+	strftime(timestamp, sizeof(timestamp), "COMMENT:Updated: " DATE_FORMAT " %H:%M:%S", localtime(&now));
 #endif
 	rrdargs[argi++] = strdup(timestamp);
 ```
 
Then this program must be compiled and the resulting file showgraph.cgi moved to
it's expected location, which is in my case /usr/lib/xymon/server/bin/showgraph.cgi.
 
Actually, the differences shown above contain an additional patch. The constant
DATE_FORMAT is introduced, which specifies the format of a date both in the
title of a graph and in the comment line at the bottom, containing the time of
generation of the graph. The date format is set to an ISO8601-compatible format.
This modification is included, as all the other dates in the page generated by
xymon are already using ISO8601, by defining xymon installation constant
XYMONDATEFORMAT. In my case it is defined in the following way:
 
```
XYMONDATEFORMAT="%a %Y-%m-%d %H:%M:%S"
```
