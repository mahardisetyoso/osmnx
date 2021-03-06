################################################################################
# Module: utils_graph.py
# Description: Network utility functions
# License: MIT, see full license in LICENSE.txt
# Web: https://github.com/gboeing/osmnx
################################################################################

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from collections import Counter
from itertools import chain
from shapely.geometry import LineString
from shapely.geometry import Point
from . import settings
from . import utils



def induce_subgraph(G, node_subset):
    """
    Induce a subgraph of G.

    Parameters
    ----------
    G : networkx.MultiDiGraph
    node_subset : list-like
        the subset of nodes to induce a subgraph of G

    Returns
    -------
    H : networkx.MultiDiGraph
        the subgraph of G induced by node_subset
    """

    node_subset = set(node_subset)

    # copy nodes into new graph
    H = G.__class__()
    H.add_nodes_from((n, G.nodes[n]) for n in node_subset)

    # copy edges to new graph, including parallel edges
    if H.is_multigraph:
        H.add_edges_from((n, nbr, key, d)
            for n, nbrs in G.adj.items() if n in node_subset
            for nbr, keydict in nbrs.items() if nbr in node_subset
            for key, d in keydict.items())
    else:
        H.add_edges_from((n, nbr, d)
            for n, nbrs in G.adj.items() if n in node_subset
            for nbr, d in nbrs.items() if nbr in node_subset)

    # update graph attribute dict, and return graph
    H.graph.update(G.graph)
    return H



def get_largest_component(G, strongly=False):
    """
    Return a subgraph of the largest weakly or strongly connected component
    from a directed graph.

    Parameters
    ----------
    G : networkx.MultiDiGraph
    strongly : bool
        if True, return the largest strongly instead of weakly connected
        component

    Returns
    -------
    G : networkx.MultiDiGraph
        the largest connected component subgraph from the original graph
    """

    original_len = len(list(G.nodes()))

    if strongly:
        # if the graph is not connected retain only the largest strongly connected component
        if not nx.is_strongly_connected(G):

            # get all the strongly connected components in graph then identify the largest
            sccs = nx.strongly_connected_components(G)
            largest_scc = max(sccs, key=len)
            G = induce_subgraph(G, largest_scc)

            msg = (f'Graph was not connected, retained only the largest strongly '
                   f'connected component ({len(G)} of {original_len} total nodes)')
            utils.log(msg)
    else:
        # if the graph is not connected retain only the largest weakly connected component
        if not nx.is_weakly_connected(G):

            # get all the weakly connected components in graph then identify the largest
            wccs = nx.weakly_connected_components(G)
            largest_wcc = max(wccs, key=len)
            G = induce_subgraph(G, largest_wcc)

            msg = (f'Graph was not connected, retained only the largest weakly '
                   f'connected component ({len(G)} of {original_len} total nodes)')
            utils.log(msg)

    return G



def get_route_edge_attributes(G, route, attribute=None, minimize_key='length',
                              retrieve_default=None):
    """
    Get a list of attribute values for each edge in a path.

    Parameters
    ----------
    G : networkx multidigraph
    route : list
        list of nodes in the path
    attribute : string
        the name of the attribute to get the value of for each edge.
        If not specified, the complete data dict is returned for each edge.
    minimize_key : string
        if there are parallel edges between two nodes, select the one with the
        lowest value of minimize_key
    retrieve_default : Callable[Tuple[Any, Any], Any]
        Function called with the edge nodes as parameters to retrieve a
        default value, if the edge does not contain the given attribute. Per
        default, a `KeyError` is raised
    Returns
    -------
    attribute_values : list
        list of edge attribute values
    """

    attribute_values = []
    for u, v in zip(route[:-1], route[1:]):
        # if there are parallel edges between two nodes, select the one with the
        # lowest value of minimize_key
        data = min(G.get_edge_data(u, v).values(), key=lambda x: x[minimize_key])
        if attribute is None:
            attribute_value = data
        elif retrieve_default is not None:
            attribute_value = data.get(attribute, retrieve_default(u, v))
        else:
            attribute_value = data[attribute]
        attribute_values.append(attribute_value)
    return attribute_values



def count_streets_per_node(G, nodes=None):
    """
    Count how many street segments emanate from each node (i.e.,
    intersections and dead-ends) in this graph. If nodes is passed,
    then only count the nodes in the graph with those IDs.

    Parameters
    ----------
    G : networkx.MultiDiGraph
    nodes : iterable
        the set of node IDs to get counts for

    Returns
    ----------
    streets_per_node : dict
        counts of how many streets emanate from each node with
        keys=node id and values=count
    """

    # to calculate the counts, get undirected representation of the graph. for
    # each node, get the list of the set of unique u,v,key edges, including
    # parallel edges but excluding self-loop parallel edges (this is necessary
    # because bi-directional self-loops will appear twice in the undirected
    # graph as you have u,v,key0 and u,v,key1 where u==v when you convert from
    # MultiDiGraph to MultiGraph - BUT, one-way self-loops will appear only
    # once. to get consistent accurate counts of physical streets, ignoring
    # directionality, we need the list of the set of unique edges...). then,
    # count how many times the node appears in the u,v tuples in the list. this
    # is the count of how many street segments emanate from this node. finally,
    # create a dict of node id:count
    G_undir = G.to_undirected(reciprocal=False)
    all_edges = G_undir.edges(keys=False)
    if nodes is None:
        nodes = G_undir.nodes()

    # get all unique edges - this throws away any parallel edges (including
    # those in self-loops)
    all_unique_edges = set(all_edges)

    # get all edges (including parallel edges) that are not self-loops
    non_self_loop_edges = [e for e in all_edges if not e[0]==e[1]]

    # get a single copy of each self-loop edge (ie, if it's bi-directional, we
    # ignore the parallel edge going the reverse direction and keep only one
    # copy)
    set_non_self_loop_edges = set(non_self_loop_edges)
    self_loop_edges = [e for e in all_unique_edges if e not in set_non_self_loop_edges]

    # final list contains all unique edges, including each parallel edge, unless
    # the parallel edge is a self-loop, in which case it doesn't double-count
    # the self-loop
    edges = non_self_loop_edges + self_loop_edges

    # flatten the list of (u,v) tuples
    edges_flat = list(chain.from_iterable(edges))

    # count how often each node appears in the list of flattened edge endpoints
    counts = Counter(edges_flat)
    streets_per_node = {node:counts[node] for node in nodes}
    msg = ('Got the counts of undirected street segments incident to each node '
           '(before removing peripheral edges)')
    utils.log(msg)
    return streets_per_node



def graph_to_gdfs(G, nodes=True, edges=True, node_geometry=True, fill_edge_geometry=True):
    """
    Convert a graph into node and/or edge GeoDataFrames

    Parameters
    ----------
    G : networkx.MultiDiGraph
    nodes : bool
        if True, convert graph nodes to a GeoDataFrame and return it
    edges : bool
        if True, convert graph edges to a GeoDataFrame and return it
    node_geometry : bool
        if True, create a geometry column from node x and y data
    fill_edge_geometry : bool
        if True, fill in missing edge geometry fields using origin and
        destination nodes

    Returns
    -------
    GeoDataFrame or tuple
        gdf_nodes or gdf_edges or both as a tuple
    """

    if not (nodes or edges):
        raise ValueError('You must request nodes or edges, or both.')

    to_return = []

    if nodes:

        nodes, data = zip(*G.nodes(data=True))
        gdf_nodes = gpd.GeoDataFrame(list(data), index=nodes)
        if node_geometry:
            gdf_nodes['geometry'] = gdf_nodes.apply(lambda row: Point(row['x'], row['y']), axis=1)
            gdf_nodes.set_geometry('geometry', inplace=True)
        gdf_nodes.crs = G.graph['crs']

        to_return.append(gdf_nodes)
        utils.log('Created nodes GeoDataFrame from graph')

    if edges:

        # create a list to hold our edges, then loop through each edge in the
        # graph
        edges = []
        for u, v, key, data in G.edges(keys=True, data=True):

            # for each edge, add key and all attributes in data dict to the
            # edge_details
            edge_details = {'u':u, 'v':v, 'key':key}
            for attr_key in data:
                edge_details[attr_key] = data[attr_key]

            # if edge doesn't already have a geometry attribute, create one now
            # if fill_edge_geometry==True
            if 'geometry' not in data:
                if fill_edge_geometry:
                    point_u = Point((G.nodes[u]['x'], G.nodes[u]['y']))
                    point_v = Point((G.nodes[v]['x'], G.nodes[v]['y']))
                    edge_details['geometry'] = LineString([point_u, point_v])
                else:
                    edge_details['geometry'] = np.nan

            edges.append(edge_details)

        # create a GeoDataFrame from the list of edges and set the CRS
        gdf_edges = gpd.GeoDataFrame(edges)
        gdf_edges.crs = G.graph['crs']

        to_return.append(gdf_edges)
        utils.log('Created edges GeoDataFrame from graph')

    if len(to_return) > 1:
        return tuple(to_return)
    else:
        return to_return[0]



def gdfs_to_graph(gdf_nodes, gdf_edges):
    """
    Convert node and edge GeoDataFrames into a MultiDiGraph

    Parameters
    ----------
    gdf_nodes : GeoDataFrame
    gdf_edges : GeoDataFrame

    Returns
    -------
    networkx.MultiDiGraph
    """

    G = nx.MultiDiGraph()
    G.graph['crs'] = gdf_nodes.crs

    # add the nodes and their attributes to the graph
    G.add_nodes_from(gdf_nodes.index)
    attributes = gdf_nodes.to_dict()
    for attribute_name in gdf_nodes.columns:
        # only add this attribute to nodes which have a non-null value for it
        attribute_values = {k:v for k, v in attributes[attribute_name].items() if pd.notnull(v)}
        nx.set_node_attributes(G, name=attribute_name, values=attribute_values)

    # add the edges and attributes that are not u, v, key (as they're added
    # separately) or null
    for _, row in gdf_edges.iterrows():
        attrs = {}
        for label, value in row.iteritems():
            if (label not in ['u', 'v', 'key']) and (isinstance(value, list) or pd.notnull(value)):
                attrs[label] = value
        G.add_edge(row['u'], row['v'], key=row['key'], **attrs)

    return G



def remove_isolated_nodes(G):
    """
    Remove from a graph all the nodes that have no incident edges (ie, node
    degree = 0).

    Parameters
    ----------
    G : networkx.MultiDiGraph
        the graph from which to remove nodes

    Returns
    -------
    networkx.MultiDiGraph
    """

    isolated_nodes = [node for node, degree in dict(G.degree()).items() if degree < 1]
    G.remove_nodes_from(isolated_nodes)
    utils.log(f'Removed {len(isolated_nodes)} isolated nodes')
    return G



def _is_duplicate_edge(data, data_other):
    """
    Check if two edge data dictionaries are the same based on OSM ID and
    geometry.

    Parameters
    ----------
    data : dict
        the first edge's data
    data_other : dict
        the second edge's data

    Returns
    -------
    is_dupe : bool
    """

    is_dupe = False

    # if either edge's OSM ID contains multiple values (due to simplification), we want
    # to compare as sets so they are order-invariant, otherwise uv does not match vu
    osmid = set(data['osmid']) if isinstance(data['osmid'], list) else data['osmid']
    osmid_other = set(data_other['osmid']) if isinstance(data_other['osmid'], list) else data_other['osmid']

    if osmid == osmid_other:
        # if they contain the same OSM ID or set of OSM IDs (due to simplification)
        if ('geometry' in data) and ('geometry' in data_other):
            # if both edges have a geometry attribute
            if _is_same_geometry(data['geometry'], data_other['geometry']):
                # if their edge geometries have the same coordinates
                is_dupe = True
        elif ('geometry' in data) and ('geometry' in data_other):
            # if neither edge has a geometry attribute
            is_dupe = True
        else:
            # if one edge has geometry attribute but the other doesn't, keep it
            pass

    return is_dupe



def _is_same_geometry(ls1, ls2):
    """
    Check if LineString geometries in two edges are the same, in
    normal or reversed order of points.

    Parameters
    ----------
    ls1 : LineString
        the first edge's geometry
    ls2 : LineString
        the second edge's geometry

    Returns
    -------
    bool
    """

    # extract geometries from each edge data dict
    geom1 = [list(coords) for coords in ls1.xy]
    geom2 = [list(coords) for coords in ls2.xy]

    # reverse the first edge's list of x's and y's to look for a match in
    # either order
    geom1_r = [list(reversed(list(coords))) for coords in ls1.xy]

    # if the edge's geometry matches its reverse's geometry in either order,
    # return True
    return (geom1 == geom2 or geom1_r == geom2)



def _update_edge_keys(G):
    """
    Update the keys of edges that share a u, v with another edge but differ in
    geometry. For example, two one-way streets from u to v that bow away from
    each other as separate streets, rather than opposite direction edges of a
    single street.

    Parameters
    ----------
    G : networkx.MultiDiGraph

    Returns
    -------
    networkx.MultiDiGraph
    """

    # identify all the edges that are duplicates based on a sorted combination
    # of their origin, destination, and key. that is, edge uv will match edge vu
    # as a duplicate, but only if they have the same key
    edges = graph_to_gdfs(G, nodes=False, fill_edge_geometry=False)
    edges['uvk'] = edges.apply(lambda row: '_'.join(sorted([str(row['u']), str(row['v'])]) + [str(row['key'])]), axis=1)
    edges['dupe'] = edges['uvk'].duplicated(keep=False)
    dupes = edges[edges['dupe']==True].dropna(subset=['geometry'])

    different_streets = []
    groups = dupes[['geometry', 'uvk', 'u', 'v', 'key', 'dupe']].groupby('uvk')

    # for each set of duplicate edges
    for label, group in groups:

        # if there are more than 2 edges here, make sure to compare all
        if len(group['geometry']) > 2:
            l = group['geometry'].tolist()
            l.append(l[0])
            geom_pairs = list(zip(l[:-1], l[1:]))
        # otherwise, just compare the first edge to the second edge
        else:
            geom_pairs = [(group['geometry'].iloc[0], group['geometry'].iloc[1])]

        # for each pair of edges to compare
        for geom1, geom2 in geom_pairs:
            # if they don't have the same geometry, flag them as different streets
            if not _is_same_geometry(geom1, geom2):
                # add edge uvk, but not edge vuk, otherwise we'll iterate both their keys
                # and they'll still duplicate each other at the end of this process
                different_streets.append((group['u'].iloc[0], group['v'].iloc[0], group['key'].iloc[0]))

    # for each unique different street, iterate its key + 1 so it's unique
    for u, v, k in set(different_streets):
        # filter out key if it appears in data dict as we'll pass it explicitly
        attributes = {k:v for k, v in G[u][v][k].items() if k != 'key'}
        G.add_edge(u, v, key=k+1, **attributes)
        G.remove_edge(u, v, key=k)

    return G



def get_undirected(G):
    """
    Convert a directed graph to an undirected graph that maintains parallel
    edges if geometries differ.

    Parameters
    ----------
    G : networkx.MultiDiGraph

    Returns
    -------
    networkx.MultiGraph
    """

    # set from/to nodes before making graph undirected
    G = G.copy()
    for u, v, k, data in G.edges(keys=True, data=True):
        G.edges[u, v, k]['from'] = u
        G.edges[u, v, k]['to'] = v

        # add geometry if it doesn't already exist, to retain parallel
        # edges' distinct geometries
        if 'geometry' not in data:
            point_u = Point((G.nodes[u]['x'], G.nodes[u]['y']))
            point_v = Point((G.nodes[v]['x'], G.nodes[v]['y']))
            data['geometry'] = LineString([point_u, point_v])

    # update edge keys so we don't retain only one edge of sets of parallel edges
    # when we convert from a multidigraph to a multigraph
    G = _update_edge_keys(G)

    # now convert multidigraph to a multigraph, retaining all edges in both
    # directions for now, as well as all graph attributes
    H = nx.MultiGraph()
    H.add_nodes_from(G.nodes(data=True))
    H.add_edges_from(G.edges(keys=True, data=True))
    H.graph = G.graph
    H.name = G.name

    # the previous operation added all directed edges from G as undirected
    # edges in H. this means we have duplicate edges for every bi-directional
    # street. so, look through the edges and remove any duplicates
    duplicate_edges = []
    for u, v, key, data in H.edges(keys=True, data=True):

        # if we haven't already flagged this edge as a duplicate
        if not (u, v, key) in duplicate_edges:

            # look at every other edge between u and v, one at a time
            for key_other in H[u][v]:

                # don't compare this edge to itself
                if not key_other == key:

                    # compare the first edge's data to the second's to see if
                    # they are duplicates
                    data_other = H.edges[u, v, key_other]
                    if _is_duplicate_edge(data, data_other):

                        # if they match up, flag the duplicate for removal
                        duplicate_edges.append((u, v, key_other))

    H.remove_edges_from(duplicate_edges)
    utils.log('Made undirected graph')

    return H
