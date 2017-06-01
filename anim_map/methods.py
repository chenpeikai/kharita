from collections import defaultdict
from scipy.spatial import cKDTree
import numpy as np
import datetime
import operator
import geopy
import geopy.distance
import math
import networkx as nx
from matplotlib import pyplot as plt
from matplotlib import collections as mc
import os
import copy


class GpsPoint:
	def __init__(self, vehicule_id=None, lon=None, lat=None, speed=None, timestamp=None, angle=None, traj_id=None):
			self.vehicule_id = int(vehicule_id) if vehicule_id != None else 0
			self.speed = float(speed) if speed != None else 0.0
			if timestamp != None:
				self.timestamp = datetime.datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S+03')
			self.lon = float(lon)
			self.lat = float(lat)
			self.angle = float(angle)
			if traj_id != None:
				self.traj_id = traj_id

	def get_coordinates(self):
		"""
		return the lon,lat of a gps point
		:return: tuple (lon, lat)
		"""
		return (self.lat, self.lon)

	def get_lonlat(self):
		return (self.lon, self.lat)

	def set_traj_id(self, traj_id):
		self.traj_id = traj_id

	def __str__(self):
		return "bt_id:%s, speed:%s, timestamp:%s, lon:%s, lat:%s, angle:%s" % \
			   (self.vehicule_id, self.speed, self.timestamp, self.lon, self.lat, self.angle)

	def __repr__(self):
		return "bt_id:%s, speed:%s, timestamp:%s, lon:%s, lat:%s, angle:%s" % \
			   (self.vehicule_id, self.speed, self.timestamp, self.lon, self.lat, self.angle)


class Cluster:
	def __init__(self, cid=None, nb_points=None, last_seen=None, lat=None, lon=None, angle=None):
		self.cid = cid
		self.lon = lon
		self.lat = lat
		self.angle = angle
		self.last_seen = last_seen
		self.nb_points = nb_points
		self.points = []

	def get_coordinates(self):
		return (self.lat, self.lon)

	def get_lonlat(self):
		return (self.lon, self.lat)

	def add(self, point):
		self.points.append(point)
		self.nb_points += 1
		self.last_seen = point.timestamp
		#self._recompute_center()

	def _recompute_center(self):
		self.lon = sum([p.lon for p in self.points]) / len(self.points)
		self.lat = sum([p.lat for p in self.points]) / len(self.points)
		self.angle = self._meanangle([p.angle for p in self.points])

	def _meanangle(self, anglelist):
		"""
		Author: Rade Stanojevic.
		Computes the average value of a list of angles expressed in 0-360 interval.
		:param anglelist: list of angles
		:return: average
		"""
		return(np.arctan2(sum([np.sin(alpha/360*2*np.pi) for alpha in anglelist]),sum([np.cos(alpha/360*2*np.pi) for alpha in anglelist]))*180/np.pi)


def satisfy_path_condition_distance(s, t, g, clusters, alpha):
	"""
	return False if there's a path of length max length, True otherwise
	:param s:
	:param t:
	:param k_reach:
	:return:
	"""
	if s == -1 or t == -1 or s == t:
		return False

	edge_distance = geopy.distance.distance(geopy.Point(clusters[s].get_coordinates()), \
	                                        geopy.Point(clusters[t].get_coordinates())).meters
	if not nx.has_path(g, s, t):
		return True
	path = nx.shortest_path(g, source=s, target=t)
	path_length_meters = 0
	for i in range(1, len(path)):
		path_length_meters += geopy.distance.distance(geopy.Point(clusters[path[i - 1]].get_coordinates()),\
	                                        geopy.Point(clusters[path[i]].get_coordinates())).meters
	if path_length_meters >= alpha * edge_distance:
		return True
	return False


def load_data(fname='data/gps_data/gps_points.csv'):
	"""
	Given a file that contains gps points, this method creates different data structures
	:param fname: the name of the input file, as generated by QMIC
	:return: data_points (list of gps positions with their metadata), raw_points (coordinates only),
	points_tree is the KDTree structure to enable searching the points space
	"""
	data_points = list()
	raw_points = list()

	with open(fname, 'r') as f:
		f.readline()
		for line in f:
			if len(line) < 10:
				continue
			vehicule_id, timestamp, lat, lon, speed, angle = line.split(',')
			pt = GpsPoint(vehicule_id=vehicule_id, timestamp=timestamp, lat=lat, lon=lon, speed=speed,angle=angle)
			data_points.append(pt)
			raw_points.append(pt.get_coordinates())
	points_tree = cKDTree(raw_points)
	return np.array(data_points), np.array(raw_points), points_tree


def create_trajectories(INPUT_FILE_NAME='data/gps_data/gps_points_07-11.csv', waiting_threshold=5):
	"""
	return all trajectories.
	The heuristic is simple. Consider each users sorted traces not broken by more than 1 hour as trajectories.
	:param waiting_threshold: threshold for trajectory split expressed in seconds.
	:return: list of lists of trajectories
	"""

	data_points, raw_points, points_tree = load_data(fname=INPUT_FILE_NAME)
	detections = defaultdict(list)
	for p in data_points:
		detections[p.vehicule_id].append(p)

	# compute trajectories: split detections by waiting_threshold
	print 'Computing trajectories'
	trajectories = []
	for btd, ldetections in detections.iteritems():
		points = sorted(ldetections, key=operator.attrgetter('timestamp'))
		source = 0
		prev_point = 0
		i = 1
		while i < len(points):
			delta = points[i].timestamp - points[prev_point].timestamp
			if delta.days * 24 * 3600 + delta.seconds > waiting_threshold:
				trajectories.append(points[source: i])
				source = i
			prev_point = i
			i += 1
		if source < len(points):
			trajectories.append(points[source: -1])
	return trajectories


def diffangles(a1, a2):
	"""
	Difference between two angles in 0-360 degrees.
	:param a1: angle 1
	:param a2: angle 2
	:return: difference
	"""
	return 180 - abs(abs(a1 - a2) - 180)


def partition_edge(edge, distance_interval):
	"""
	given an edge, creates holes every x meters (distance_interval)
	:param edge: a given edge
	:param distance_interval: in meters
	:return: list of holes
	"""

	# We always return the source node of the edge, hopefully the target will be added as the source of another edge.
	holes = []
	d = geopy.distance.VincentyDistance(meters=distance_interval)
	# make sure we are using lat,lon not lon,lat as a reference.
	startpoint = geopy.Point(edge[0].get_coordinates())
	endpoint = geopy.Point(edge[1].get_coordinates())
	initial_dist = geopy.distance.distance(startpoint, endpoint).meters
	if initial_dist < distance_interval:
		# return [], distance_interval - initial_dist
		return holes
	# compute the angle=bearing at which we need to be moving.
	bearing = calculate_bearing(startpoint[0], startpoint[1], endpoint[0], endpoint[1])
	last_point = startpoint
	diff_time = edge[1].last_seen - edge[0].last_seen
	delta_time = diff_time.days*24*3600 + diff_time.seconds
	time_increment = delta_time / (int(initial_dist) / distance_interval)
	for i in range(int(initial_dist) / distance_interval):
		new_point = geopy.Point(d.destination(point=last_point, bearing=bearing))
		str_timestamp = datetime.datetime.strftime(edge[0].last_seen + datetime.timedelta(seconds=time_increment), "%Y-%m-%d %H:%M:%S+03")
		holes.append(GpsPoint(lat=new_point.latitude, lon=new_point.longitude, angle=bearing,
		                      timestamp=str_timestamp))
		last_point = new_point
	# return holes, initial_dist - (initial_dist / distance_interval) * distance_interval
	return holes


def calculate_bearing(latitude_1, longitude_1, latitude_2, longitude_2):
	"""
	Got it from this link: http://pastebin.com/JbhWKJ5m
   Calculation of direction between two geographical points
   """
	rlat1 = math.radians(latitude_1)
	rlat2 = math.radians(latitude_2)
	rlon1 = math.radians(longitude_1)
	rlon2 = math.radians(longitude_2)
	drlon = rlon2 - rlon1

	b = math.atan2(math.sin(drlon) * math.cos(rlat2), math.cos(rlat1) * math.sin(rlat2) -
	               math.sin(rlat1) * math.cos(rlat2) * math.cos(drlon))
	return (math.degrees(b) + 360) % 360


def vector_direction_re_north(s, d):
	"""
	Make the source as the reference of the plan. Then compute atan2 of the resulting destination point
	:param s: source point
	:param d: destination point
	:return: angle!
	"""

	# find the new coordinates of the destination point in a plan originated at source.
	new_d_lon = d.lon - s.lon
	new_d_lat = d.lat - s.lat
	angle = -math.degrees(math.atan2(new_d_lat, new_d_lon)) + 90

	# the following is required to move the degrees from -180, 180 to 0, 360
	if angle < 0:
		angle = angle + 360
	return angle


def draw_roadnet(rn):
	lines = [[s, t] for s, t in rn.edges()]

	print len(lines), lines[ :10]
	lc = mc.LineCollection(lines, colors='black', linewidths=2)
	fig, ax = plt.subplots(facecolor='black', figsize=(14, 10))
	ax.add_collection(lc)
	ax.autoscale()
	plt.show()


def draw_roadnet_id_colored(rn, clusters, matched_nodes, new_nodes, dead_nodes):
	print 'Plotting the map'
	lines = [[clusters[s].get_lonlat(), clusters[t].get_lonlat()] for s, t in rn.edges()]
	lc = mc.LineCollection(lines, colors='black', linewidths=1)
	fig, ax = plt.subplots(figsize=(14, 10))
	ax.add_collection(lc)
	ax.autoscale()
	X, Y = [], []
	for pt in new_nodes:
		X.append(pt[0])
		Y.append(pt[1])
	plt.scatter(X, Y, c='green', s=40)

	X, Y = [], []
	for pt in matched_nodes:
		X.append(pt[0])
		Y.append(pt[1])
	plt.scatter(X, Y, c='0.8', s=40)

	X, Y = [], []
	for pt in dead_nodes:
		X.append(pt[0])
		Y.append(pt[1])
	plt.scatter(X, Y, c='red', s=40)
	plt.show()


def create_proxy(label, marker='s'):
	line = plt.Line2D((0, 1), (0, 0), color=label, marker=marker, linestyle='')
	return line


def road_color(weight):
	if weight == 0:
		return '0.3'
	if weight == 1:
		return 'green'
	return 'white'


def road_color_regarding_ground(edge, weight, ground_map_edges):
	"""
	If the edge is new (not part of the ground map) paint it in green.
	else, for grounp map edges use two colors: gray for un-used segments, white for used ones.
	:param edge:
	:param weight:
	:param ground_map_edges:
	:return:
	"""

	if edge not in ground_map_edges:
		return 'green'
	if weight == 0:
		return '0.3'
	return 'white'


def generate_image(list_of_edges, edge_weight, nbr, roardnet, clusters, nb_traj, osm, fig, ax, timestamp, lonlat_to_cid,
                   ground_map_edges):

	if os.path.exists('/home/sofiane/projects/2017/kharita/animation_bbx_osm'):
		path_animation = '/home/sofiane/projects/2017/kharita/animation_bbx_osm'
	else:
		path_animation = '/home/sabbar/projects/2017/kharita/animation_bbx_osm'
	print 'generating image:', nbr
	lines = [[s, t] for s, t in list_of_edges]
	# colors based on weight
	# colors = [road_color(edge_weight[i]) for i in range(len(lines))]

	# colors based on whether the edge exists in the ground map or not.
	colors = [road_color_regarding_ground(edge, edge_weight[i], ground_map_edges) for i, edge in enumerate(list_of_edges)]
	for i, edge in enumerate(list_of_edges):
		s_delta = timestamp - clusters[lonlat_to_cid[edge[0]]].last_seen
		t_delta = timestamp - clusters[lonlat_to_cid[edge[1]]].last_seen
		if (s_delta.days*24*3600 + s_delta.seconds) > 3600 and (t_delta.days*24*3600 + t_delta.seconds) > 3600:
			colors[i] = 'red'

	lc = mc.LineCollection(lines, colors=colors, linewidths=2)
	fig, ax = plt.subplots(facecolor='black', figsize=(14, 10))
	# add OSM every 100 frames
	# if nbr % 100 == 0:
	# 	ax.add_collection(copy.copy(osm))
	ax.add_collection(lc)
	#plt.plot(t[0], t[1], marker=(3, 0, 90), markersize=10, linestyle='None')
	plt.plot(t[0], t[1], marker="*", markersize=10, color='red', linestyle='None')



	# # Intersections in different colors?
	# outdegree = roadnet.out_degree()
	# indegree = roadnet.out_degree()
	# intersections = set([n for n in outdegree if outdegree[n] > 1] + [n for n in indegree if indegree[n] > 1])
	# X, Y = [], []
	# for n in intersections:
	# 	X.append(clusters[n].lon)
	# 	Y.append(clusters[n].lat)
	# plt.scatter(X, Y, color='yellow')

	ax.text(0.05, 0.01, 'Time: %s' % (timestamp),
	        verticalalignment='bottom',
	        horizontalalignment='left',
	        transform=ax.transAxes,
	        color='white', fontsize=10)

	ax.text(0.70, 0.01, '# Edges: %s' % len(list_of_edges),
	        verticalalignment='bottom',
	        horizontalalignment='right',
	        transform=ax.transAxes,
	        color='white', fontsize=10)

	ax.text(0.95, 0.01, 'Animation: S. Abbar',
	        verticalalignment='bottom',
	        horizontalalignment='right',
	        transform=ax.transAxes,
	        color='white', fontsize=6)

	ax.autoscale()
	# ax.margins(0.1)
	plt.axis('off')

	# legends
	descriptions = ['Vehicles', 'New Road Seg.', 'Confirmed Road Seg.', 'Unused Road Seg.']
	# descriptions = ['Vehicles', 'New Road Seg.', 'Confirmed Road Seg.']
	labels = ['red', 'green', 'white', 'red']
	pers_markers = ['*', 's', 's', 's']
	proxies = [create_proxy(item, mark) for item, mark in zip(labels, pers_markers)]
	ax.legend(proxies, descriptions, fontsize=6, numpoints=1, markerscale=1, ncol=4, bbox_to_anchor=(0.8, -0.05))

	plt.savefig('%s/frame_%s.png' % (path_animation, nbr), format='PNG',
	            facecolor=fig.get_facecolor(), transparent=True, bbox_inches='tight')

	# ax.clear()
	# fig.clf()
	plt.close()


def crop_osm_graph(fname):
	max_lat = 25.302769999999999
	min_lat = 25.283760000000001
	max_lon = 51.479749499999997
	min_lon = 51.458219999999997
	# use this awk command: awk 'BEGIN {FS=" ";} {if ($1 < 51.479749499999997 && $1 > 51.458219999999997 && $2 < 25.302769999999999 && $2 > 25.283760000000001 && $4 < 51.479749499999997 && $4 > 51.458219999999997 && $5 < 25.302769999999999 && $5 > 25.283760000000001 ) print}' osmmapclusterangle.txt > osm_bbx.csv


def build_initial_graph_from_osm(fname):
	"""
	Build the OSM graph for a list of edges: source, target.
	:param fname:
	:return:
	"""
	clusters = []
	clusters_latlon = []
	list_of_edges = []
	edge_weight = []
	osm_roadnet = nx.DiGraph()
	now_ts = datetime.datetime.now()
	with open(fname) as f:
		for line in f:
			slon, slat, sang, tlon, tlat, tang = map(float, line.strip().split(' '))
			if (slat, slon) not in clusters_latlon:
				new_cluster = Cluster(cid=len(clusters), nb_points=1, last_seen=now_ts, lat=slat, lon=slon, angle=sang)
				clusters.append(new_cluster)
				clusters_latlon.append((slat, slon))
			if (tlat, tlon) not in clusters_latlon:
				new_cluster = Cluster(cid=len(clusters), nb_points=1, last_seen=now_ts, lat=tlat, lon=tlon, angle=tang)
				clusters.append(new_cluster)
				clusters_latlon.append((tlat, tlon))
			osm_roadnet.add_edge(clusters_latlon.index((slat, slon)), clusters_latlon.index((tlat, tlon)))
			list_of_edges.append([(slon, slat), (tlon, tlat)])
			edge_weight.append(0)
	clusters_latlon = None
	return clusters, osm_roadnet, list_of_edges, edge_weight


def kharitaStar(parameters):
	"""
	return a road network from trajectories
	:param trajectories:
	:return:
	"""

	outf = open('distances.txt', 'w')
	# Algorithm parameters
	FILE_CODE = parameters['file_code']
	DATA_PATH = parameters['data_path']
	RADIUS_METER = parameters['radius_meter']
	RADIUS_DEGREE = parameters['radius_degree']
	SAMPLING_DISTANCE = parameters['sampling_distance']
	HEADING_ANGLE_TOLERANCE = parameters['heading_angle']
	total_points = 0
	p_X = []
	p_Y = []

	# Generate Trajectories
	trajectories = create_trajectories(INPUT_FILE_NAME='%s/%s.csv' % (DATA_PATH, FILE_CODE), waiting_threshold=21)

	# Sort trajectories into a stream of points
	print 'Computing points stream'
	building_trajectories = dict()
	gps_point_stream = []
	for i, trajectory in enumerate(trajectories):
		for point in trajectory:
			point.set_traj_id(i)
			gps_point_stream.append(point)
	gps_point_stream = sorted(gps_point_stream, key=operator.attrgetter('timestamp'))

	trajectories = None
	update_kd_tree = False
	prev_cluster = -1
	current_cluster = -1
	first_edge = True

	matched_osm_clusters = []
	dead_osm_clusters = []
	new_osm_clusters = []

	# ##################### Incrementality starts here! #################################
	# Read and prepare the existing map, assume it is coming from OSM.
	clusters, roadnet, list_of_edges, edge_weight = build_initial_graph_from_osm(fname='data/osm_bbx.csv')
	original_osm_clusters_lonlats = [c.get_lonlat() for c in clusters]

	# X, Y =[], []
	# for clu in clusters:
	# 	X.append(clu.lon)
	# 	Y.append(clu.lat)
	# plt.scatter(X, Y, c='black')
	# plt.show()

	cluster_kdtree = cKDTree([c.get_lonlat() for c in clusters])
	#lonlat_to_clusterid = {c.get_lonlat():c.cid for c in clusters}

	print 'Matching trajectories to OSM'
	for point in gps_point_stream:
		if point.timestamp < datetime.datetime.strptime('2015-11-05 22:00:00', '%Y-%m-%d %H:%M:%S'):
			continue


		traj_id = point.traj_id
		prev_cluster = building_trajectories.get(traj_id, -1)
		p_X.append(point.lon)
		p_Y.append(point.lat)

		# if there's a cluster within x meters and y angle: add to. Else: create new cluster
		nearest_cluster_indices = [clu_index for clu_index in cluster_kdtree.query_ball_point(x=point.get_lonlat(), r=RADIUS_DEGREE, p=2)
		                           if math.fabs(diffangles(point.angle, clusters[clu_index].angle)) <= HEADING_ANGLE_TOLERANCE]


		if prev_cluster != -1:
			temp_dist = geopy.distance.distance(geopy.Point(clusters[prev_cluster].get_coordinates()), geopy.Point(point.get_coordinates())).meters
			if temp_dist > 200:
				continue
			outf.write('%s\n' % temp_dist)

		# *****************
		# Cluster creation
		# *****************
		# TODO: be more conservative in creating clusters! Add something like a threshold, min number of cars, etc.
		if len(nearest_cluster_indices) == 0:
			# create a new cluster
			new_cluster = Cluster(cid=len(clusters), nb_points=1, last_seen=point.timestamp, lat=point.lat, lon=point.lon, angle=point.angle)
			clusters.append(new_cluster)
			#lonlat_to_clusterid[new_cluster.get_lonlat()] = new_cluster.cid
			roadnet.add_node(new_cluster.cid)
			current_cluster = new_cluster.cid
			# recompute the cluster index
			update_kd_tree = True
			new_osm_clusters.append(new_cluster.get_lonlat())

			# TODO: Check if we need to create an edge here
			# *****************
			# Edge creation
			# *****************
			# case of very first point in the trajectory (has no previous cluster.)
			if prev_cluster == -1:
				building_trajectories[traj_id] = current_cluster
				continue

			edge = [clusters[prev_cluster], clusters[current_cluster]]
			# TODO: I can add a condition on when to create fictional clusters. E.g., condition on angle diff (prev,curr)
			intermediate_fictional_points = partition_edge(edge, distance_interval=SAMPLING_DISTANCE)

			# Check if the newly created points belong to any existing cluster:
			intermediate_fictional_cluster_ids = []
			for pt in intermediate_fictional_points:
				nearest_cluster_indices = [clu_index for clu_index in
				                           cluster_kdtree.query_ball_point(x=pt.get_lonlat(), r=RADIUS_DEGREE, p=2)
				                           if math.fabs(
						diffangles(pt.angle, clusters[clu_index].angle)) <= HEADING_ANGLE_TOLERANCE]
				if len(nearest_cluster_indices) == 0:
					intermediate_fictional_cluster_ids.append(-1)
				else:
					# identify the cluster to which the intermediate cluster belongs
					PT = geopy.Point(pt.get_coordinates())
					close_clusters_distances = [
						geopy.distance.distance(PT, geopy.Point(clusters[clu_index].get_coordinates())).meters for
						clu_index
						in nearest_cluster_indices]
					closest_cluster_indx = nearest_cluster_indices[
						close_clusters_distances.index(min(close_clusters_distances))]
					intermediate_fictional_cluster_ids.append(closest_cluster_indx)

			# For each fictional point in segment: if ==-1 create new cluster and link to it, else link to the corresponding cluster
			prev_path_point = prev_cluster
			for idx, inter_clus_id in enumerate(intermediate_fictional_cluster_ids):
				if inter_clus_id == -1:
					n_cluster_point = intermediate_fictional_points[idx]
					# create a new cluster
					new_cluster = Cluster(cid=len(clusters), nb_points=1, last_seen=point.timestamp,
					                      lat=n_cluster_point.lat,
					                      lon=n_cluster_point.lon, angle=n_cluster_point.angle)
					clusters.append(new_cluster)
					# lonlat_to_clusterid[new_cluster.get_lonlat()] = new_cluster.cid
					roadnet.add_node(new_cluster.cid)
					new_osm_clusters.append(new_cluster.get_lonlat())

					# recompute the clusters kd-tree index
					update_kd_tree = True
					# create the actual edge: condition on angle differences only.
					if math.fabs(
							diffangles(clusters[prev_path_point].angle, new_cluster.angle)) > HEADING_ANGLE_TOLERANCE \
							or math.fabs(diffangles(vector_direction_re_north(clusters[prev_path_point], new_cluster),
							                        clusters[prev_path_point].angle)) > HEADING_ANGLE_TOLERANCE:
						prev_path_point = new_cluster.cid
						continue
					# if satisfy_path_condition_distance(prev_path_point, new_cluster.cid, roadnet, clusters, alpha=1.2):
					if (prev_path_point, new_cluster.cid) not in list_of_edges:
						list_of_edges.append([clusters[prev_path_point].get_lonlat(), clusters[new_cluster.cid].get_lonlat()])
						roadnet.add_edge(prev_path_point, new_cluster.cid)
						edge_weight.append(1)
					else:
						edge_weight[list_of_edges.index(
							[clusters[prev_path_point].get_lonlat(), clusters[new_cluster.cid].get_lonlat()])] += 1
					prev_path_point = new_cluster.cid
				else:
					# if (prev_path_point, inter_clus_id) not in roadnet.edges():
					# 	list_of_edges.append(
					# 		[clusters[prev_path_point].get_lonlat(), clusters[inter_clus_id].get_lonlat()])
					# 	edge_weight.append(1)
					# 	roadnet.add_edge(prev_path_point, inter_clus_id)
					# else:
					# 	edge_weight[list_of_edges.index(
					# 		[clusters[prev_path_point].get_lonlat(), clusters[inter_clus_id].get_lonlat()])] += 1
					prev_path_point = inter_clus_id
					clusters[inter_clus_id].add(intermediate_fictional_points[idx])
			if (len(intermediate_fictional_cluster_ids) == 0 or intermediate_fictional_cluster_ids[
				-1] != current_cluster) and \
					((prev_path_point, current_cluster) not in roadnet.edges()):
				list_of_edges.append([clusters[prev_path_point].get_lonlat(), clusters[current_cluster].get_lonlat()])
				edge_weight.append(1)
				roadnet.add_edge(prev_path_point, current_cluster)
			elif (prev_path_point, current_cluster) in roadnet.edges():
				edge_weight[list_of_edges.index(
					[clusters[prev_path_point].get_lonlat(), clusters[current_cluster].get_lonlat()])] += 1
			building_trajectories[traj_id] = current_cluster

		else:
			# add the point to the cluster
			pt = geopy.Point(point.get_coordinates())
			close_clusters_distances = [geopy.distance.distance(pt, geopy.Point(clusters[clu_index].get_coordinates())).meters
			                            for clu_index in nearest_cluster_indices]
			closest_cluster_indx = nearest_cluster_indices[close_clusters_distances.index(min(close_clusters_distances))]
			clusters[closest_cluster_indx].add(point)
			current_cluster = closest_cluster_indx
			if clusters[closest_cluster_indx].get_lonlat() in original_osm_clusters_lonlats:
				matched_osm_clusters.append(clusters[closest_cluster_indx].get_lonlat())
		if update_kd_tree:
			cluster_kdtree = cKDTree([c.get_lonlat() for c in clusters])
			update_kd_tree = False
	dead_osm_clusters = [c for c in original_osm_clusters_lonlats if c not in matched_osm_clusters]
	print '# new osm clusters:', len(new_osm_clusters)
	print '# matched osm clusters:', len(matched_osm_clusters)
	print '# dead osm clusters:', len(dead_osm_clusters)
	return roadnet, clusters, matched_osm_clusters, new_osm_clusters, dead_osm_clusters


def removePathsOSM(osm_rn, nb_paths):
	"""
	Remove nb_paths from OSM Road Network. A path is a sequence of edges between two intersections.
	:param osm_rn: initial OSM_RN
	:param nb_paths: number of paths to remove
	:return: a new OSM_RN, list of removed segments.
	"""

	# get all nodes of degree higher than 2 (intersections)
