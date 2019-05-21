"""
    File name: VoronoiParser
    Author: Artelys - Hugo Chareyre
    Date last modified: 21/11/2018
    Python Version: 3.6
"""
import numpy as np
from shapely.geometry import MultiLineString, LineString, box, Polygon, MultiPolygon
from shapely.ops import linemerge, polygonize
import geopandas as gpd
from typing import Union
from collections import defaultdict
import pyvoronoi


GenericLine = Union[LineString, MultiLineString]


class PyVoronoiHelper:
    """Add-on for the pyvoronoi (boost voronoi) tool. It computes the voronoi cells within a bounding box."""

    def __init__(self, points: list, segments: list, bounding_box_coords: list, scaling_factor=100000.0):
        self.pv = pyvoronoi.Pyvoronoi(scaling_factor)
        for p in points:
            self.pv.AddPoint(p)
        for s in segments:
            self.pv.AddSegment(s)
        self.pv.Construct()
        self.discretization_tolerance = 10000 / scaling_factor
        self.bounding_box_coords = bounding_box_coords

    def get_cells_as_gdf(self) -> gpd.GeoDataFrame:
        """Returns the voronoi cells in `geodataframe` with a column named `id` referencing the index of the associated
         input geometry."""
        gdf = gpd.GeoDataFrame(columns=["id", "geometry"])
        cells_geometries = self.get_cells_as_polygons()
        gdf["geometry"] = list(cells_geometries.values())
        gdf["id"] = list(cells_geometries.keys())
        return gdf

    def get_cells_as_polygons(self) -> dict:
        """Return the voronoi cells as polygons trimmed with the bounding box."""
        diagonal_length = np.linalg.norm(np.array(self.bounding_box_coords[0]) - np.array(self.bounding_box_coords[1]))
        cells_coordinates = self.get_cells_coordiates(eta=diagonal_length,
                                                      discretization_tolerance=self.discretization_tolerance)
        bounding_box = box(self.bounding_box_coords[0][0], self.bounding_box_coords[0][1],
                           self.bounding_box_coords[1][0], self.bounding_box_coords[1][1])
        cells_as_polygons = dict()
        for i, coords in cells_coordinates.items():
            if len(coords) > 2:
                polygon = Polygon(coords)
                if not polygon.is_valid:
                    polygon = self.repair_polygon(polygon)
                trimmed_polygon = polygon.intersection(bounding_box)
                cells_as_polygons[i] = trimmed_polygon
        return cells_as_polygons

    @staticmethod
    def repair_polygon(polygon: Union[Polygon, MultiPolygon]) -> Union[Polygon, MultiPolygon]:
        """Repair an invalid polygon. It works in most cases but it has no guarantee of success."""
        bowtie_repaired_polygon = PyVoronoiHelper.repair_bowtie_polygon(polygon)
        if not bowtie_repaired_polygon.is_valid:
            return polygon.buffer(0.0)
        else:
            return bowtie_repaired_polygon

    @staticmethod
    def repair_bowtie_polygon(polygon: Union[Polygon, MultiPolygon]) -> MultiPolygon:
        """Repair an invalid polygon for the 'bowtie' case."""
        p_ext = polygon.exterior
        self_intersection = p_ext.intersection(p_ext)
        mp = MultiPolygon(polygonize(self_intersection))
        return mp

    def get_cells_coordiates(self, eta=1.0, discretization_tolerance=0.05) -> dict:
        """"Parse the results of ``pyvoronoi`` to compute the voronoi cells coordinates. The infinite ridges are
        projected at a ``eta`` distance in the ridge direction.

        :param eta: Distance for infinite ridges projection.
        :param discretization_tolerance: Discretization distance for curved edges.
        :return: A dictionary mapping the cells ids and their coordinates.
        """
        vertices = self.pv.GetVertices()
        cells = self.pv.GetCells()
        edges = self.pv.GetEdges()
        cells_coordinates = dict()
        for c in cells:
            cell_coords = []
            for e in c.edges:
                edge = edges[e]
                start_vertex = vertices[edge.start] if edge.start != -1 else None
                end_vertex = vertices[edge.end] if edge.end != -1 else None
                if edge.start == -1 or edge.end == -1:
                    self.clip_infinite_edge(cell_coords, edge, eta)
                else:
                    if edge.is_linear:
                        self.add_polygon_coordinates(cell_coords, [start_vertex.X, start_vertex.Y])
                        self.add_polygon_coordinates(cell_coords, [end_vertex.X, end_vertex.Y])
                    else:
                        try:
                            coords_to_add = []
                            for p in self.pv.DiscretizeCurvedEdge(e, discretization_tolerance):
                                coords_to_add.append(p)
                            cell_coords.extend(coords_to_add)
                        except pyvoronoi.UnsolvableParabolaEquation:
                            self.add_polygon_coordinates(cell_coords, [start_vertex.X, start_vertex.Y])
                            self.add_polygon_coordinates(cell_coords, [end_vertex.X, end_vertex.Y])
            cells_coordinates[c.cell_identifier] = cell_coords
        return cells_coordinates


    def clip_infinite_edge(self, cell_coords: list, edge: pyvoronoi.Edge, eta: float):
        """Fill infinite edge coordinate by placing the infinite vertex to a ``eta`` distance of the known vertex."""
        cell = self.pv.GetCell(edge.cell)
        twin_edge = self.pv.GetEdge(edge.twin)
        twin_cell = self.pv.GetCell(twin_edge.cell)
        # Infinite edges could not be created by two segment sites.
        if cell.contains_point and twin_cell.contains_point:
            first_point = self.pv.RetrieveScaledPoint(cell)
            second_point = self.pv.RetrieveScaledPoint(twin_cell)
            origin = np.array([(first_point[0] + second_point[0]) / 2.0,
                                 (first_point[1] + second_point[1]) / 2.0])
            ridge_direction = np.array([first_point[1] - second_point[1],
                                        second_point[0] - first_point[0]])
        else:
            if cell.contains_segment:
                origin = np.array(self.pv.RetrieveScaledPoint(twin_cell))
                segment = np.array(self.pv.RetriveScaledSegment(cell))
            else:
                origin = np.array(self.pv.RetrieveScaledPoint(cell))
                segment = np.array(self.pv.RetriveScaledSegment(twin_cell))
            dx = segment[1][0] - segment[0][0]
            dy = segment[1][1] - segment[0][1]
            if (np.linalg.norm(segment[0] - origin) == 0.0) != cell.contains_point:
                ridge_direction = np.array([dy, -dx])
            else:
                ridge_direction = np.array([-dy, dx])
        ridge_direction /= np.linalg.norm(ridge_direction)
        if edge.start == -1:
            ridge_point_projected = origin - ridge_direction * eta
            self.add_polygon_coordinates(cell_coords, ridge_point_projected)
        else:
            start_vertex = self.pv.GetVertex(edge.start)
            self.add_polygon_coordinates(cell_coords, [start_vertex.X, start_vertex.Y])
        if edge.end == -1:
            ridge_point_projected = origin + ridge_direction * eta
            self.add_polygon_coordinates(cell_coords, ridge_point_projected)
        else:
            end_vertex = self.pv.GetVertex(edge.end)
            self.add_polygon_coordinates(cell_coords, [end_vertex.X, end_vertex.Y])


    @staticmethod
    def add_polygon_coordinates(coordinates: list, point: list):
        """Add given point to given coordinates list if is not the equal to the last coordinates."""
        if coordinates:
            last_point = coordinates[-1]
            if last_point[0] == point[0] and last_point[1] == point[1]:
                return
        coordinates.append(point)


def split_linestring_as_simple_linestrings(line: GenericLine) -> list:
    """Split a linestring if it is not simple (i.e. it crosses itself)."""
    if not line.is_simple:
        mls = line.intersection(line)
        if line.geom_type == 'LineString' and mls.geom_type == 'MultiLineString':
            mls = linemerge(mls)
        return list(mls)
    else:
        return [line]

def split_as_simple_segments(lines: list, tol=1e-7) -> defaultdict:
    """Split a list of lines to simple segments (linestring composed by two points). All returned segments do not
    cross themselves except at extremities.

    :param lines: List of lines to split
    :param tol: Tolerance to test if a line is a sub line of another one.
    :return: A dictionary mapping for each input line index, the list of simple segments.
    """
    split_lines_mapping = defaultdict(list)
    all_split_lines = split_linestring_as_simple_linestrings(MultiLineString(lines))
    j = 0
    sub_line = all_split_lines[j]
    nb_simple_segments = len(all_split_lines)
    end_mapping = False
    for i, line in enumerate(lines):
        while line.buffer(tol, 1).contains(sub_line):
            split_lines_mapping[i].append(sub_line)
            j += 1
            if j >= nb_simple_segments:
                end_mapping = True
                break
            sub_line = all_split_lines[j]
        if end_mapping:
            break
    return split_lines_mapping


def compute_voronoi_cells_from_lines(lines: list, scaling_factor=1e7) -> gpd.GeoDataFrame:
    """Compute the voronoi cells of given generic lines. Input linestrings can be not simple.

    :param lines: List of ``LineString``
    :param scaling_factor: Resolution for the voronoi cells computation (Two points will be considered equal if their
        coordinates are equal when rounded at ``1/scaling_factor``).
    :return: A `GeoDataFrame` with cells geometries. A column named `id` referencing the index of the associated
        input geometry.
    """
    simple_segments_mapping = split_as_simple_segments(lines, 1 / scaling_factor)
    all_segments = [list(s.coords) for i in range(len(lines)) for s in simple_segments_mapping[i]]
    bounds = MultiLineString(lines).bounds
    bb = [[bounds[0], bounds[1]], [bounds[2], bounds[3]]]
    pvh = PyVoronoiHelper([], segments=all_segments, bounding_box_coords=bb, scaling_factor=scaling_factor)
    gdf = pvh.get_cells_as_gdf()
    gdf = gdf[list(map(lambda i: isinstance(i, Polygon), gdf["geometry"]))].copy()
    gdf["site"] = [pvh.pv.GetCell(c).site for c in gdf["id"]]
    gdf_lines = gpd.GeoDataFrame(columns=["id", "geometry"])
    from shapely.ops import cascaded_union
    from shapely.geometry import GeometryCollection
    ct = 0
    for i, line in enumerate(lines):
        line_polygons = []
        for s in simple_segments_mapping[i]:
            for p in gdf[gdf["site"] == ct]["geometry"]:
                line_polygons.append(p)
            ct += 1
        merged_polygon = cascaded_union(line_polygons)
        if isinstance(merged_polygon, GeometryCollection):
            if len(merged_polygon) == 0:
                continue
            merged_polygon = MultiPolygon(merged_polygon)
        gdf_lines.loc[len(gdf_lines)] = [i, merged_polygon]
    return gdf_lines


def get_segment_boundary_buffer_polygon(segment_coords: list, radius: float, residual_radius: float) -> Polygon:
    segment_direction = [segment_coords[1][0] - segment_coords[0][0], segment_coords[1][1] - segment_coords[0][1]]
    orthogonal_dir = np.array([- segment_direction[1], segment_direction[0]])
    orthogonal_dir /= np.linalg.norm(orthogonal_dir)
    top_points = [segment_coords[0] + orthogonal_dir * radius, segment_coords[1] + orthogonal_dir * residual_radius]
    bottom_points = [segment_coords[0] - orthogonal_dir * radius, segment_coords[1] - orthogonal_dir * residual_radius]
    return Polygon(top_points + list(reversed(bottom_points)))



import geonetworkx as gnx
from shapely.geometry import Point
from shapely.ops import cascaded_union
import math

def get_point_boundary_buffer_polygon(point_coords: list, radius: float, segment_direction: list, resolution=16) -> Polygon:
    """Returns a half-disk centered on the given point, with the given radius and having the boundary edge orthogonal to
    the given segment direction. See ``boundary_edge_buffer``."""
    # Segment angle with system coordinates
    phi = math.acos(segment_direction[0] / np.linalg.norm(segment_direction))
    if segment_direction[1] < 0:
        phi *= -1.0
    # Discretization angle
    theta = math.pi / float(resolution)
    # Start angle
    angle = phi - math.pi / 2.0
    coords = []
    for i in range(resolution + 1):
        coords.append(point_coords + radius * np.array([math.cos(angle), math.sin(angle)]))
        angle -= theta
    return Polygon(coords)


def boundary_edge_buffer(line: LineString) -> Union[Polygon, MultiPolygon]:
    """ Return the edge buffer polygon on the oriented line. This represented the area where all points are reachable
    starting from the line first extremity and using the closest edge projection rule."""
    radius = line.length
    residual_radius = radius
    boundary_polygons = []
    for i in range(len(line.coords) - 1):
        segment_coords = np.array([line.coords[i], line.coords[i + 1]])
        residual_radius -= gnx.euclidian_distance_coordinates(segment_coords[0], segment_coords[1])
        boundary_polygon = get_segment_boundary_buffer_polygon(segment_coords, radius, residual_radius)
        boundary_polygons.append(boundary_polygon)
        segment_direction = segment_coords[1] - segment_coords[0]
        boundary_polygons.append(get_point_boundary_buffer_polygon(segment_coords[0], radius, segment_direction))
        radius = residual_radius
    return cascaded_union(boundary_polygons)




def get_alpha_shape_polygon(points: list, quantile: int) -> Union[Polygon, MultiPolygon]:
    from scipy.spatial import Delaunay
    tri = Delaunay(np.array(points))
    polygons = []
    # loop over triangles:
    # ia, ib, ic = indices of corner points of the triangle
    circum_radius = []
    for ia, ib, ic in tri.vertices:
        pa = points[ia]
        pb = points[ib]
        pc = points[ic]
        # Lengths of sides of triangle
        a = math.sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2)
        b = math.sqrt((pb[0] - pc[0]) ** 2 + (pb[1] - pc[1]) ** 2)
        c = math.sqrt((pc[0] - pa[0]) ** 2 + (pc[1] - pa[1]) ** 2)
        # Semiperimeter of triangle
        s = (a + b + c) / 2.0
        # Area of triangle by Heron's formula
        area = math.sqrt(s * (s - a) * (s - b) * (s - c))
        circum_r = a * b * c / (4.0 * area)
        circum_radius.append(circum_r)
        polygons.append(Polygon([pa, pb, pc]))
    alpha = np.percentile(circum_radius, quantile)
    filtered_polygons = [p for i, p in enumerate(polygons) if circum_radius[i] <= alpha]
    return cascaded_union(filtered_polygons)
