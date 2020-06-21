#!/usr/bin/python3
#
# detapd, DETermine_Air_Plane_Distance:
#
# Determine the closest distance between a reference point and the passing air
# planes, and count the number of air planes per distance class per unit of
# time.
#
# Written by W.J.M. Nelis, wim.nelis@ziggo.nl, 2019.06
#
# To do:
# - Gracefull shut down when killed.
# - Handle multiple messages per read from the socket.
# - Add descriptive title to each of the entries in dict aps.
#
import datetime
import math				# Goniometric functions
import re				# Regular expressions
import signal
import socket				# Socket API
import subprocess			# Start another process
import sys				# System API
import syslog
import threading
import time


#
# Configuration parameters.
# =========================
#

#
# Define the location of the reference point and the geocentric radius of the
# earth at that location.
#
RefPnt= dict( Latitude="Your", Longitude="Location" )	# Location, degrees
Earth = 6364779				# Geocentric radius, [m]

#
# Define the invocation parameters of the external data collector, dump1090. It
# should publish only the BaseStation (decoded) messages and not generate any
# output. As this data collector will be running on a Raspberry Pi 0W, the
# resource usage should be minimised.
#
ExtCol= [ '/path/to/dump1090/dump1090',
          '--lat', str(RefPnt['Latitude'] ),
          '--lon', str(RefPnt['Longitude']),
          '--net', '--net-http-port', '0',
          '--net-ri-port', '0', '--net-ro-port', '0',
          '--net-bi-port', '0', '--net-bo-port', '0',
          '--quiet' ]

#
# Program dump1090 exports the decoded messages on socket port TCP/30003. (Only
# message type MSG will be available.)
#
ServerHost= 'localhost'
ServerPort= 30003

#
# Define the distance classes to use. In this (ordered) list per distance class
# a tuple, containing the name (key) as well as a part of the expression to
# evaluate, is defined. The check for the correct class will evaluate the
# classes in the order specified until one fits.
#
DistClass= [
  ( 'dist_unknown'  , 'is None' ),
  ( 'dist_00_01_km' , '<  1000' ),
  ( 'dist_01_02_km' , '<  2000' ),
  ( 'dist_02_04_km' , '<  4000' ),
  ( 'dist_04_08_km' , '<  8000' ),
  ( 'dist_08_16_km' , '< 16000' ),
  ( 'dist_16_inf_km', '>=16000' )
]

#
# Global storage allocation.
# ==========================
#
sosts= None				# Start-of-script time stamp
sosrf= None				#  in human readable form

apl= {}					# Air plane list
ams= dict(				# ADS-B message statistics
  total_messages= 0,			# Total number of messages received
  procd_messages= 0,			# Number of processed messages
  zero_id_messages= 0,			# Number of messages with a null ICAO address
  erred_messages= 0,			# Number of erred messages received
)
aps= dict(				# Air plane statistics
  total_airplane= 0,			# Total number of airplanes detected
)
for i in DistClass:  aps[i[0]]= 0	# Add counter per distance class

#
# Utilities.
# ==========
#

#
# Function Cartesian computes from a position on the surface on earth, latitude
# and longitude, together with the height above the surface of the earth the
# Cartesian coordinates, with (0,0,0) being the centre of the earth.
#
def Cartesian( lat, long, alt ):
  la= math.radians( lat )		# Convert angles to radians
  lo= math.radians( long )
  ra= Earth + alt*0.3048		# Convert altitude to [m]
  x= ra*math.cos(la)*math.cos(lo)	# Calculate Cartesian coordinates
  y= ra*math.cos(la)*math.sin(lo)
  z= ra*math.sin(la)
  return (x,y,z)

#
# Function ClassifyDistance maps the distance, expressed in [m], onto a key to
# be used in a dictionary. Per distance class one such a key is defined.
#
def ClassifyDistance( d ):
  for i in DistClass:			# Get next distance class tuple
    expr= 'd {}'.format( i[1] )		# Build expression to evaluate
    if eval( expr):
      key= i[0]
      break
  return key

#
# Function Distance computes the distance between two points, specified in
# cartesian coordinates.
#
def Distance( a, b ):
  d= (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2
  return math.sqrt( d )

#
# Function EncodeDateTime returns a human readable version of the time stamp,
# using ISO8601 format.
#
def EncodeDateTime( uts, sep='T' ):
  return datetime.datetime.fromtimestamp( int(uts) ).isoformat( sep )

#
# Generic class definitions.
# ==========================
#

#
# Class StoppableThread adds Event _stop_event to the thread and methods to set
# and check this event. A thread should stop if this event (flag) is set.
# Moreover, some unrelated methods, such as Wait (an extended version of
# time.sleep) are added, as they are needed by (almost) all subclasses.
#
class StoppableThread(threading.Thread):
  """Thread class with a stop() method. The thread itself has to check regularly
  for the stopped() condition."""

  def __init__( self ):
    super().__init__()
    self._stop_event = threading.Event()
 #
    self.XyServ= '127.0.0.1' 		# Name / IP address of Xymon server
    self.XyPort= 1984			# TCP port number of Xymon server

  def stop( self ):
    self._stop_event.set()

  def stopped( self ):
    return self._stop_event.is_set()

  def wait( self, timeout ):
    return self._stop_event.wait( timeout )

 #
 # Method FormatStr takes a format and a list of parameters. If the formatting
 # of the string fails with exception ValueError, the numeric conversions are
 # removed from the format and the formatting is retried. The resulting string
 # is returned.
 #
  def FormatStr( self, fmtstr, *pars ):
    try:
      result= fmtstr.format( *pars )
    except ValueError:
      fmtstr= re.sub( '{:[\d\.]*[df]}', '{}', fmtstr )
      result= fmtstr.format( *pars )
    return result

 #
 # Method InformXymon sends a status message to the Xymon server.
 #
  def InformXymon( self, Hst, Tst, Clr, Msg ):
    XyTime= int( time.time() )
    XyTime= datetime.datetime.fromtimestamp(XyTime).isoformat( sep=' ' )
    XyPars= { 'host': Hst, 'test': Tst, 'colour': Clr, 'time': XyTime,
              'message': Msg }
    XyMsg = '''status {host}.{test} {colour} {time}
{message}'''.format( **XyPars )
    try:
      s= socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    except socket.error as msg:
      return False
    if not re.search( '^[\d\.]+$', self.XyServ ):
      try:
        self.XyServ= socket.gethostbyname( self.XyServ )
      except socket.gaierror:
        return False
    try:
      s.connect( (self.XyServ, self.XyPort) )
      s.sendall( XyMsg.encode() )
      return True
    except socket.error as msg:
      return False
    finally:
      s.close()

 #
 # Method LogMessage sends a message to the local syslog server.
 #
  def LogMessage( self, Msg ):
    syslog.openlog( 'APD', 0, syslog.LOG_LOCAL6 )
    syslog.syslog ( ' '.join( (self.name,Msg) ) )
    syslog.closelog()

 #
 # Method Wait waits until the (Unix) timestamp reaches the next integer
 # multiple of Period seconds and then another Delay seconds. However, if the
 # thread method stop is invoked before the time has expired, this method will
 # return at that time.
 # Parameters Period and Delay are integer numbers, with Period >= 2 and
 # 0 <= Delay < Period.
 #
  def Wait( self, Period, Delay ):
    Now= time.time()
    ActTim= int( Now )
    ActTim= ( (ActTim+Period-1) // Period ) * Period
    SlpTim= int( ActTim - Now ) + Delay
    if SlpTim < 1.5:  SlpTim+= Period
    self.wait( SlpTim )


#
# Specific class definitions.
# ===========================
#

#
# Class Airplane contains the relevant information received from an air plane,
# augmented with process-related data.
#
class Airplane():
  def __init__( self, Id ):
    self.IcaoAddr= Id			# ICAO address
    self.CallSign= None			# Flight code
    self.FrstSeen= None			# Time stamp of first message received
    self.LastSeen= None			# Time stamp of last message received
    self.LocatMsg=    0			# Count of messages with location
    self.TotalMsg=    0			# Total message count
    self.CurLoc  = None			# Last reported location, [x,y,z]
    self.PrevLoc = None			# Previous location, carthesian coordinates
    self.Distance= None			# Closest distance to reference point
    self.Passed  = False		# Flag: airplane has passed by

 #
 # Method ExtractDistance computes from the latitude, the longitude and the
 # altitude the (closest) distance to the reference point. If the closest
 # distance to the linearly extrapolated flight path is in between the two last
 # reported positions, this distance is used rather than the distance calculated
 # from the reported positions.
 #
  def ExtractDistance( self, lat, long, alt ):
    newloc= Cartesian( lat, long, alt )
    if newloc == self.CurLoc:  return

    self.PrevLoc= self.CurLoc
    self.CurLoc = newloc

#    if self.Passed:
#      return
  #
  # Handle the case that this is the first position received for this air plane.
  # Compute the distance to the reference point and save this distance.
  #
    if self.PrevLoc is None:
      self.Distance= Distance( self.CurLoc, RefPnt['Cartesian'] )
  #
  # Handle the case that an earlier position of this airplane is known. Compute
  # the shortest distance if the point of shortest distance is in between
  # PrevLoc and CurLoc.
  #
    else:
   #
   # The straight line L through the two points PrevLoc and CurLoc is
   # parametrised by variable s, in such a way that L(0) == PrevLoc and L(1) ==
   # CurLoc. Thus the air plane has passed the reference point if 0 <= s <= 1.
   #
      snum= 0 ;  sden= 0
      p= self.PrevLoc
      q= self.CurLoc
      r= RefPnt['Cartesian']
      for i in range(3):
        snum+= (q[i] - p[i])*(r[i] - p[i])
        sden+= (q[i] - p[i])**2
      s= snum / sden
   #
   # If the air plane has passed the reference point, calculate the point in
   # it's path of minimium distance, which p + s*(q-p).
   #
      if 0.0 <= s <= 1.0:
        self.Passed= True
        t= [0,0,0]
        for i in range(3):
          t[i]= p[i] + s*(q[i] - p[i])
        d= Distance( t, r )
      else:
        d= Distance( q, r )
      self.Distance= min( self.Distance, d )

  def SetCallSign( self, cs  ):
    self.CallSign= cs

  def SetLastSeen( self, uts ):
    if self.FrstSeen is None:  self.FrstSeen= uts
    self.LastSeen= uts


#
# Class HandleMessages receives the messages from the ADS-B data collector. It
# creates an Airplane object for each air plane detected and it invokes methods
# of this object to extract the relevant information.
#
class HandleMessages( StoppableThread ):
  def __init__( self ):
    super().__init__()			# Parent initialisation
    self.name= 'HandleMessages'		# Name of thread
    self.sock= None

 #
 # Private method _attempt_connect tries to connect to the port on which the
 # BaseStation messages are published. In case the connection is refused,
 # implying that no program has bound itself to that port, return error code
 # 111.
 #
  def _attempt_connect( self ):
    rc= 0				# Preset return code
    try:
      self.sock.connect( (ServerHost,ServerPort) )
    except ConnectionRefusedError as e:
      rc= e.errno
    return rc

 #
 # Private method _start_collector starts the data collector, dump1090, as an
 # independent process.
 #
  def _start_collector( self ):
    DevNull= subprocess.DEVNULL		# Destination for output
    pid= subprocess.Popen( ExtCol, stdout=DevNull, stderr=DevNull ).pid
    time.sleep( 5 )			# Wait for it to become active
    return pid

  def run(self):
    self.LogMessage( 'Starting thread' )

 #
 # Open a TCP-connection to the data collector to retrieve the decoded messages.
 # If the attempt to connect fails with error number 111 (connection refused),
 # try to start the data collector and try once more to build a connection to
 # this program.
 #
    self.sock= socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    if self._attempt_connect() == 111:
      self._start_collector()
      if self._attempt_connect() == 111:
        self.LogMessage( 'Error: connect failed' )
        exit( 1 )

    while not self.stopped():
      data = self.sock.recv( 2048 )
      lines= data.decode().split( '\r\n' )
      for line in lines:
        if line == '':  continue

        ams['total_messages']+= 1
 #
 # Split up the line into fields. It should result in 22 fields.
 #
        flds= line.split( ',' )
        if len(flds) != 22:
          self.LogMessage( 'Unexpected number of fields in "{}"'.format(line) )
          ams['erred_messages']+= 1
          continue
 #
 # The data collector will send only messages with type MSG. Any other type can
 # be ignored. For completeness however, the occurrence of another message type
 # is logged.
 #
        if flds[0] != 'MSG':
          self.LogMessage( 'Unexpected message type received: "{}"'.format(flds[0]) )
          ams['erred_messages']+= 1
          continue
 #
 # Each MSG-message contains a 24-bit ICAO airplane address. Make sure that this
 # identifier exists in the airplane list. However, address 000000(16) is
 # ignored, as the decoding of the address is probably incomplete and as those
 # messages do not give any additional information, relevant to this script.
 # Note that the total number of air planes is not incremented at this time:
 # only when a plane is passed by all the plane related statistics are updated.
 #
        id= flds[4]			# ICAO airplane address
        if id == '000000':
          ams['zero_id_messages']+= 1
          continue

        if id not in apl:
          apl[id]= Airplane( id )	# Enter airplane in list
        apl[id].SetLastSeen( time.time() )	# Save time of last MSG received
        apl[id].TotalMsg+= 1		# Increment total message count
 #
 # Do the transmission-type-dependent handling. Extract the flight name and of
 # course the reported positions from the message stream.
 #
        tt= int(flds[1])		# Transmission type
        if   tt == 1:
          apl[id].SetCallSign( flds[10] )	# Save call sign
          ams['procd_messages']+= 1	# Update processed message count
        elif tt == 3:
          apl[id].ExtractDistance( float(flds[14]), float(flds[15]), int(flds[11]) )
          apl[id].LocatMsg+= 1		# Update number of position messages
          ams['procd_messages']+= 1	# Update processed message count
        elif tt in [2,4,5,6,7,8]:
          pass				# No relevant info in message
        else:
          self.LogMessage( 'Unexpected MSG transmission type received: {}'.format(tt) )
          ams['erred_messages']+= 1
          continue

    self.sock.close()
    self.LogMessage( 'Stopping thread' )

#
# Thread CleanAirplaneList periodically scans the list of air planes, and it
# will remove those planes which have not been seen since at least 60 [s]. The
# statistics are then updated and a line is written to the logfile.
#
class CleanAirplaneList( StoppableThread ):
  def __init__( self ):
    super().__init__()			# Parent initialisation
    self.name= 'CleanAirplaneList'	# Name of thread
    self.outfil= None

  def run( self ):
    self.LogMessage( 'Starting thread' )
    self.outfil= open( '/home/pi/air/plane.log', 'a' )
    tf= EncodeDateTime( sosts )
    self.outfil.write( '{} Start data acquisition\n'.format(tf) )

    while not self.stopped():
      now= time.time()
      for id in list(apl):		# Do NOT use an iterator
        if now - apl[id].LastSeen < 120:  continue
        aps['total_airplane']+= 1
        sd= apl[id].Distance		# Shortest distance
        dc= ClassifyDistance( sd )	# Distance class
        aps[dc]+= 1

        if apl[id].Distance is not None:
          tf= EncodeDateTime( apl[id].FrstSeen )
          tl= EncodeDateTime( apl[id].LastSeen )
          cs= apl[id].CallSign	if apl[id].CallSign is not None else '??'
          mc= apl[id].LocatMsg
          di= '{:6d}'.format(int(apl[id].Distance))
          self.outfil.write( '{} {} {} {:8} {:3d} {}\n'.format(tf,tl,apl[id].IcaoAddr,cs,mc,di) )

        del apl[id]			# Finally, delete the entry

      time.sleep( 1 )

    self.outfil.close()
    self.LogMessage( 'Stopping thread' )


#
# Class MonitorAirspace retrieves periodically the statistics collected by
# classes / threads HandleMessages and CleanAirplaneList, formats them into
# status messages for the xymon server, and sends them to the server.
#
class MonitorAirspace( StoppableThread ):
  """Class MonitorAirspace reports some statistics about the air planes in the
     neighbourhood to the Xymon server."""

  def __init__( self ):
    super().__init__()
    self.name= 'MonitorAirspace'
    self.oldstats= None

  def _message_stats( self ):
    msg = "<p style='text-align:center'><b>ADS-B statistics</b></p>\n\n"
    msg+= "<table cellpadding=5>\n"
    msg+= "  <tr> <th>Key</th> <th>Count []</th> </tr>\n"
    for key in ('total_messages','procd_messages', 'zero_id_messages','erred_messages' ):
      msg+= "  <tr> <td>{}</td> <td>{:8d}</td> </tr>\n".format(key,ams[key])
    msg+= "</table>\n\n"
    msg+= "Statistics collection\n"
    msg+= "  started at  {}\n".format( sosrf )
    scd = (time.time() - sosts)/ 86400	# Duration expressed in days
    msg+= "  duration is {:10.2f} [d]\n".format( scd )

    msg+= "<!-- linecount=1 -->\n"
    msg+= "<!--DEVMON RRD: air 0 0\n"
    msg+= "DS:total:DERIVE:600:0:U DS:erred:DERIVE:600:0:U DS:procd:DERIVE:600:0:U DS:zeroi:DERIVE:600:0:U\n"
    msg+= "msg {}:{}:{}:{}\n".format(ams['total_messages'],
           ams['erred_messages'],ams['procd_messages'],ams['zero_id_messages'])
    msg+= "-->\n"
    return msg

  def _airplane_stats( self ):
    caps= dict( total_airplane= 0 )	# Current air plane statistics
    for i in DistClass:  caps[i[0]]= 0	# Add counter per distance class
    for i in list(apl):			# Do NOT use an iterator
      if i not in apl:  continue	# Another thread may have discarded it
      dc= ClassifyDistance( apl[i].Distance )
      caps['total_airplane']+= 1
      caps[dc]+= 1

    msg = "<p style='text-align:center'><b>Air plane statistics</b></p>\n\n"
    msg+= "<table cellpadding=5>\n"
    msg+= "  <tr> <th>Key</th> <th>Total []</th> <th>Current []</th> </tr>\n"
    for key in ('total_airplane','dist_00_01_km','dist_01_02_km' ,'dist_02_04_km',
                'dist_04_08_km' ,'dist_08_16_km','dist_16_inf_km','dist_unknown' ):
      msg+= "  <tr> <td>{}</td> <td>{:8d}</td> <td>{:8d}</td> </tr>\n".format(key,aps[key],caps[key])
    msg+= "</table>\n\n"
    msg+= "Statistics collection\n"
    msg+= "  started at  {}\n".format( sosrf )
    scd = (time.time() - sosts)/ 86400	# Duration expressed in days
    msg+= "  duration is {:10.2f} [d]\n".format( scd )

    msg+= "<!-- linecount=1 -->\n"
    msg+= "<!--DEVMON RRD: air 0 0\n"
    msg+= "DS:d0001:DERIVE:600:0:U DS:d0102:DERIVE:600:0:U DS:d0204:DERIVE:600:0:U "
    msg+= "DS:d0408:DERIVE:600:0:U DS:d0816:DERIVE:600:0:U DS:d1600:DERIVE:600:0:U "
    msg+= "DS:dunkn:DERIVE:600:0:U DS:dtotl:DERIVE:600:0:U\n"
    msg+= "plane {}:{}:{}:{}:{}:{}:{}:{}\n".format(    aps['dist_00_01_km'],
            aps['dist_01_02_km'],aps['dist_02_04_km'] ,aps['dist_04_08_km'],
            aps['dist_08_16_km'],aps['dist_16_inf_km'],aps['dist_unknown'] ,
            aps['total_airplane'] )
    msg+= "-->\n"
    return msg

  def run( self ):
    self.LogMessage( 'Starting thread' )
    XyHost= 'Airspace'			# 'Source' of this test
    XyClr = 'green'			# Status (colour) of test
    while not self.stopped():		# Repeat for a long time
      Msg= self._message_stats()	# Build status message
      if not self.InformXymon( XyHost, 'ADS-B', XyClr, Msg ):	# Send it to Xymon
        self.LogMessage( 'Sending Xymon message failed')

      Msg= self._airplane_stats()	# Build status message
      if not self.InformXymon( XyHost, 'airplane', XyClr, Msg ):	# Send it to Xymon
        self.LogMessage( 'Sending Xymon message failed')

      self.Wait( 300, 2 )		# Run once every five minutes

    self.LogMessage( 'Stopping thread' )


#
# MAIN PROGRAM.
# =============
#
MainThread= threading.Event()		# Set to stop this script

def HandleSignal( signum, frame ):
  syslog.openlog( 'APD', 0, syslog.LOG_LOCAL6 )
  syslog.syslog ( 'Termination signal #{} received'.format(signum) )
  syslog.closelog()
  MainThread.set()			# Set flag to stop script

#
# Set up handling of termination signals. They are converted into an exception.
#
signal.signal( signal.SIGINT , HandleSignal )
signal.signal( signal.SIGTERM, HandleSignal )
#
# Save time stamp at start of this script. It is used to show the length of the
# period in which the statistics shown in tables are collected.
#
sosts= time.time()			# Start-of-script time stamp
sosrf= EncodeDateTime( sosts, ' ' )	#  in human readable form
#
# Calculate and save the cartesian coordinates of the reference point.
#
RefPnt['Cartesian']= Cartesian( RefPnt['Latitude'], RefPnt['Longitude'], 0 )
#
# Start the threads making up this program.
#
threads= []
th0= HandleMessages()    ;  threads.append(th0) ;  th0.start()
th1= CleanAirplaneList() ;  threads.append(th1) ;  th1.start()
time.sleep( 10 )			# Wait for some data to arrive
th2= MonitorAirspace()   ;  threads.append(th2) ;  th2.start()
#
# Monitor the state of the threads of this script. If one thread dies or if an
# external signal is received, all (other) threads, including this main thread,
# should stop (too) in a graceful way.
#
while len(threads) > 0:
  try:
    all_alive= True			# See if all threads are currently alive
    for t in threads:
      all_alive= all_alive and t.is_alive()
    if all_alive:
      MainThread.wait( 10 )		# If so, wait some time

    if not all_alive  or  MainThread.is_set():
      for t in reversed( threads ):	# Note the order of this loop
        if t.is_alive():
          t.stop()
        t.join()
        threads.remove( t )		# Thread has stopped

  except KeyboardInterrupt:
    MainThread.set()			# Set flag to stop this script
