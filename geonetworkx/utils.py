import math
import numpy as np
import networkx as nx
from shapely.geometry import Point, LineString
from geopy.distance import vincenty
from geonetworkx.geometry_operations import coordinates_almost_equal, insert_point_in_line
from typing import Iterable


def compute_vincenty(p1, p2):
    """Returns the vincenty distance in meters given points with the format (longitude, latitude) in the WGS84
    crs."""
    return vincenty((p1[1], p1[0]), (p2[1], p2[0])).meters

def compute_vincenty_from_points(p1: Point, p2: Point):
    return compute_vincenty([p1.x, p1.y], [p2.x, p2.y])

def approx_map_unit_factor(points, tolerance=1e-7):
    """Compute a linear approximation of the map unit factor for 1 meter."""
    centroid = np.mean(points, 0)
    lower_bound = centroid
    initial_gap = tolerance
    while compute_vincenty(centroid, centroid + initial_gap) < 1.0:
        initial_gap *= 2
    upper_bound = centroid + initial_gap
    unit_point = (lower_bound + upper_bound) / 2
    distance = compute_vincenty(centroid, unit_point)
    while np.abs(distance - 1.0) > tolerance:
        if distance > 1.0:
            upper_bound = unit_point
        else:
            lower_bound = unit_point
        unit_point = (lower_bound + upper_bound) / 2
        distance = compute_vincenty(centroid, unit_point)
    return np.linalg.norm(centroid - unit_point)

def measure_line_distance(line: LineString) -> float:
    """
    Measure the length of a shapely LineString object using the vincenty distance.
    :param line: Linestring to measure. Coordinates have to be (in the WGS-84 ellipsoid model)
    :return: distance in meters of the linestring.
    """
    coords = line.coords
    if len(coords) < 2:
        return 0.0
    u = coords[0]
    total_distance = 0.0
    for i in range(1, len(coords)):
        v = coords[i]
        total_distance += compute_vincenty(u, v)
        u = v
    return total_distance


def get_new_node_unique_name(graph: nx.Graph, name: str):
    """
    Return a new unique node name from an initial node name. A counter suffix is added at the end if the node name is
    already used.
    :param graph: A given graph
    :param name: A initial node name
    :return: A unique name not in `graph.nodes()`.
    """
    if name not in graph.nodes():
        return name
    else:
        ct = 1
        unique_name = name
        while unique_name in graph.nodes():
            ct += 1
            unique_name = "%s_%d" % (str(name), ct)
        return unique_name

def euclidian_distance_coordinates(c1: Iterable, c2: Iterable) -> float:
    """Return the euclidian distance between the two sets of coordinates."""
    return math.sqrt(sum(((i - j) ** 2 for i, j in zip(c1, c2))))

def euclidian_distance(p1: Point, p2: Point) -> float:
    """
    Return the euclidian distance between the two points
    :param p1: The first shapely Point
    :param p2: The second shapely Point
    :return: The euclidian distance
    """
    return euclidian_distance_coordinates((p1.x, p1.y), (p2.x, p2.y))

def fill_edges_missing_geometry_attributes(graph: "GeoGraph"):
    """
    Add a geometry attribute to the edges that don't have any. The created geometry is a straight line between the
    two nodes.
    """
    edges = dict(graph.edges)
    nodes = dict(graph.nodes)
    for s in edges:
        if graph.edges_geometry_key not in edges[s]:
            if graph.x_key in nodes[s[0]] and graph.x_key in nodes[s[1]] and graph.y_key in nodes[s[0]] and graph.y_key in nodes[s[1]]:
                n1_xy, n2_xy = (nodes[s[0]][graph.x_key], nodes[s[0]][graph.y_key]), (nodes[s[1]][graph.x_key], nodes[s[1]][graph.y_key])
                graph.edges[s][graph.edges_geometry_key] = LineString([n1_xy, n2_xy])


def fill_length_attribute(graph: "GeoGraph", attribute_name="length", only_missing=True):
    """
    Fill the 'length' attribute of the given networkX Graph. The length is computed in meters using the vincenty
     formula.
    :param graph: graph to fill
    :param attribute_name: The length attribute name to set
    :param only_missing: Compute the length only if the attribute is missing
    :return: None
    """
    edges_geometry = nx.get_edge_attributes(graph, graph.edges_geometry_key)
    for e in edges_geometry:
        edge_data = graph.edges[e]
        if (not only_missing) or attribute_name not in edge_data:
            edge_data[attribute_name] = measure_line_distance(edges_geometry[e])


def join_lines_extremity_to_nodes_coordinates(graph: "GeoGraph"):
    """
    Modify the edges geometry attribute so that lines extremities match with nodes coordinates.
    :param graph: A geograph to modify
    """
    edges_geometry = nx.get_edge_attributes(graph, graph.edges_geometry_key)
    for e in edges_geometry:
        line = edges_geometry[e]
        to_replace = False
        first_node_coords = graph.get_node_coordinates(e[0])
        if not coordinates_almost_equal(line.coords[0], first_node_coords):
            line = insert_point_in_line(line, first_node_coords, 0)
            to_replace = True
        second_node_coords = graph.get_node_coordinates(e[1])
        if not coordinates_almost_equal(line.coords[-1], second_node_coords):
            line = insert_point_in_line(line, second_node_coords, len(line.coords))
            to_replace = True
        if to_replace:
            graph.edges[e][graph.edges_geometry_key] = line


def order_well_lines(graph: "GeoGraph"):
    """
    Try to order well each geometry attribute of edges so that the first coordinates of the line string are the
    coordinates of the first vertex of the edge. The closest node rule is applied.
    :param graph: Graph on which to apply the ordering step. Modification is inplace.
    :return: None
    """
    line_strings = nx.get_edge_attributes(graph, graph.edges_geometry_key)
    for e in line_strings:
        uxy = graph.get_node_coordinates(e[0])
        vxy = graph.get_node_coordinates(e[1])
        line = line_strings[e]
        first_extremity = line.coords[0]
        last_extremity = line.coords[-1]
        u_e1 = euclidian_distance_coordinates(uxy, first_extremity)
        v_e1 = euclidian_distance_coordinates(vxy, first_extremity)
        u_e2 = euclidian_distance_coordinates(uxy, last_extremity)
        v_e2 = euclidian_distance_coordinates(vxy, last_extremity)
        to_reverse = False
        if u_e1 > v_e1 and u_e2 < v_e2:  # u is closer to e2 and v is closer to e1
            to_reverse = True
        elif u_e1 < v_e1 and u_e2  < v_e2:  # u is closer to e1 and e2 than v
            if u_e1 > u_e2:
                to_reverse = True
        elif u_e1 > v_e1 and u_e2 > v_e2:  # v in closer to e1 and e2 than u
            if v_e1 < v_e2:
                to_reverse = True
        if to_reverse:
            graph.edges[e][graph.edges_geometry_key] = LineString(reversed(line.coords))


def stringify_nodes(graph, copy=True):
    """Modify the graph node names into strings."""
    nx.relabel_nodes(graph, {n: str(n) for n in graph.nodes}, copy)