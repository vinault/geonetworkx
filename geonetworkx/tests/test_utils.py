# -*- coding: utf-8 -*-
"""
    File name: test_utils
    Author: Artelys
    Creation date: 06/05/2019
    Python Version: 3.6
"""

import networkx as nx
import geonetworkx as gnx
import unittest
from nose.tools import assert_true
from nose.plugins.attrib import attr
import geonetworkx.testing.utils as gnx_tu
from geonetworkx.utils.voronoi_utils import *
import os


gnx_tu.SEED = 70595
NB_POINTS = 50
data_directory = os.path.join(os.path.dirname(os.path.realpath(__file__)), "datasets")


@attr('tools')
class TestUtils(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_voronoi_edges(self):
        mdg = nx.read_gpickle(os.path.join(data_directory, "grenoble200_mdg.gpickle"))
        mg = mdg.to_undirected()
        gmg = gnx.read_geograph_with_coordinates_attributes(mg)
        gnx.fill_edges_missing_geometry_attributes(gmg)
        edge_as_lines = gmg.get_edges_as_line_series()
        lines = list(edge_as_lines)
        tolerance = 1e-7
        res = compute_voronoi_cells_from_lines(lines, scaling_factor=1/tolerance)
        for e, line in edge_as_lines.items():
            cell_found = False
            for p in res["geometry"]:
                if p.buffer(10 * tolerance).contains(line):
                    cell_found = True
                    break
            if not cell_found:
                assert_true(False, "A edge geometry '%s' is not in any voronoi cells" % str(e))


