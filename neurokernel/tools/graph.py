#!/usr/bin/env python

"""
Graph/connectivity manipulation and visualization tools
"""

import itertools
import os
import re
import tempfile

import matplotlib.pyplot as plt
import networkx as nx

from .. import base
from .. import core

def imdisp(f):
    """
    Display the specified image file using matplotlib.
    """
    
    im = plt.imread(f)
    plt.imshow(im)
    plt.axis('off')
    plt.draw()
    return im

def show_pydot(g):
    """
    Display a networkx graph using pydot.
    """
    
    fd = tempfile.NamedTemporaryFile()
    fd.close()
    p = nx.to_pydot(g)
    p.write_jpg(fd.name)
    imdisp(fd.name)
    os.remove(fd.name)

def show_pygraphviz(g, prog='dot', graph_attr={}, node_attr={}, edge_attr={}):
    """
    Display a networkx graph using pygraphviz.

    Parameters
    ----------
    prog : str
        Executable for generating the image.
    graph_attr : dict
        Global graph display attributes.
    node_attr : dict
        Global node display attributes.
    edge_attr : dict
        Global edge display attributes.
    
    """
    
    fd = tempfile.NamedTemporaryFile(suffix='.jpg')
    fd.close()
    p = nx.to_agraph(g)
    p.graph_attr.update(graph_attr)
    p.node_attr.update(node_attr)
    p.edge_attr.update(edge_attr)
    p.draw(fd.name, prog=prog)
    imdisp(fd.name)
    os.remove(fd.name)

def conn_to_graph(c):
    """
    Convert a connectivity object into a bipartite NetworkX directed multigraph.

    Parameters
    ----------
    c : base.BaseConnectivity
        Connectivity object.
    
    """

    if not isinstance(c, base.BaseConnectivity):
        raise ValueError('invalid connectivity object')
    
    g = nx.MultiDiGraph()
    A_nodes = [c.A_id+':'+str(i) for i in xrange(c.N_A)]
    B_nodes = [c.B_id+':'+str(i) for i in xrange(c.N_B)]
    g.add_nodes_from(A_nodes)
    g.add_nodes_from(B_nodes)

    # Set the neuron_type attribute of the nodes if
    # the specified object is a Connectivity instance:
    if isinstance(c, core.Connectivity):
        for i in xrange(c.N_A_gpot):
            g.node[c.A_id+':'+\
                str(c.idx_translate[c.A_id]['gpot', i])]['neuron_type'] = 'gpot'
        for i in xrange(c.N_B_gpot):
            g.node[c.B_id+':'+\
                str(c.idx_translate[c.B_id]['gpot', i])]['neuron_type'] = 'gpot'
        for i in xrange(c.N_A_spike):
            g.node[c.A_id+':'+\
                str(c.idx_translate[c.A_id]['spike', i])]['neuron_type'] = 'spike'
        for i in xrange(c.N_B_spike):
            g.node[c.B_id+':'+\
                str(c.idx_translate[c.B_id]['spike', i])]['neuron_type'] = 'spike'
            
    # Create the edges of the graph:
    for key in [k for k in c._data.keys() if re.match('.*\/conn$', k)]:
        A_id, B_id, conn, name = key.split('/')
        conn = int(conn)
        for i, j in itertools.product(xrange(c.N(A_id)), xrange(c.N(B_id))):
            if isinstance(c, core.Connectivity):
                if c[A_id, 'all', i, B_id, 'all', j, conn, name] == 1:
                    g.add_edge(A_id+':'+str(i), B_id+':'+str(j))                
            else:
                if c[A_id, i, B_id, j, conn, name] == 1:
                    g.add_edge(A_id+':'+str(i), B_id+':'+str(j))


    # Next, set the attributes on each edge: 
    for key in [k for k in c._data.keys() if not re.match('.*\/conn$', k)]:
        A_id, B_id, conn, name = key.split('/')
        conn = int(conn)
        for i, j in itertools.product(xrange(c.N(A_id)), xrange(c.N(B_id))):
            
            # Parameters are only defined for node pairs for which there exists
            # a connection:
            if isinstance(c, core.Connectivity):
                if c[A_id, 'all', i, B_id, 'all', j, conn, name]:                
                    g[A_id+':'+str(i)][B_id+':'+str(j)][conn][name] = \
                        c[A_id, 'all', i, B_id, 'all', j, conn, name]  
            else:
                if c[A_id, i, B_id, j, conn, name]:                
                    g[A_id+':'+str(i)][B_id+':'+str(j)][conn][name] = \
                        c[A_id, i, B_id, j, conn, name]            
    return g

def graph_to_conn(g, conn_type=core.Connectivity):
    """
    Convert a bipartite NetworkX directed multigraph to a connectivity object.

    Parameters
    ----------
    g : networkx.MultiDiGraph
        Directed multigraph instance.
    conn_type : {base.BaseConnectivity, core.Connectivity}
        Type of output to generate.
    
    Notes
    -----
    Assumes that `g` is bipartite and all of its nodes are labeled 'A:X' or
    'B:X', where 'A' and 'B' are the names of the connected modules.

    When loading a graph from a GEXF file via networkx.read_gexf(),
    the relabel parameter should be set to True to prevent the actual labels in
    the file from being ignored.
    """

    if not isinstance(g, nx.MultiDiGraph):
        raise ValueError('invalid graph object')
    if not nx.is_bipartite(g):
        raise ValueError('graph must be bipartite')
    if conn_type not in [base.BaseConnectivity, core.Connectivity]:
        raise ValueError('invalid connectivity type')
    
    # Categorize nodes and determine number of nodes to support:
    A_nodes = []
    B_nodes = []

    node_dict = {}
    for label in g.nodes():
        try:
            id, n = re.search('(.+):(.+)', label).groups()
        except:
            raise ValueError('incorrectly formatted node label: %s' % label)
        if not node_dict.has_key(id):
            node_dict[id] = set()
        node_dict[id].add(int(n))
    
    # Graph must be bipartite:
    if len(node_dict.keys()) != 2:
        raise ValueError('incorrectly formatted graph')
    A_id, B_id = node_dict.keys()
    N_A = len(node_dict[A_id])
    N_B = len(node_dict[B_id])

    # Nodes must be consecutively numbered from 0 to N:
    if set(range(max(node_dict[A_id])+1)) != node_dict[A_id] or \
        set(range(max(node_dict[B_id])+1)) != node_dict[B_id]:
        raise ValueError('nodes must be numbered consecutively from 0..N')

    # If a Connectivity object must be created, count how many graded potential
    # and spiking neurons are comprised by the graph:
    if conn_type == core.Connectivity:
        N_A_gpot = 0
        N_A_spike = 0
        N_B_gpot = 0
        N_B_spike = 0
        for n in node_dict[A_id]:
            if g.node[A_id+':'+str(n)]['neuron_type'] == 'gpot':
                N_A_gpot += 1
            elif g.node[A_id+':'+str(n)]['neuron_type'] == 'spike':
                N_A_spike += 1
            else:
                raise ValueError('invalid neuron type')
        for n in node_dict[B_id]:
            if g.node[B_id+':'+str(n)]['neuron_type'] == 'gpot':
                N_B_gpot += 1
            elif g.node[B_id+':'+str(n)]['neuron_type'] == 'spike':
                N_B_spike += 1
            else:
                raise ValueError('invalid neuron type')
        
    # Find maximum number of edges between any two nodes:
    N_mult = max([len(g[u][v]) for u,v in set(g.edges())])

    # Create empty connectivity structure:
    if conn_type == base.BaseConnectivity:
        c = base.BaseConnectivity(N_A, N_B, N_mult, A_id, B_id)
    else:
        c = core.Connectivity(N_A_gpot, N_A_spike, N_B_gpot, N_B_spike,
                              N_mult, A_id, B_id)
    
    # Set the parameters in the connectivity object:
    for edge in g.edges():
        A_id, i = edge[0].split(':')
        i = int(i)
        B_id, j = edge[1].split(':')
        j = int(j)
        edge_dict = g[edge[0]][edge[1]]
        for conn, k in enumerate(edge_dict.keys()):
            if conn_type == base.BaseConnectivity:
                c[A_id, i, B_id, j, conn] = 1
                
                for param in edge_dict[k].keys():

                    # The ID loaded by networkx.read_gexf() is always a string, but
                    # should be interpreted as an integer:
                    if param == 'id':
                        c[A_id, i, B_id, j, conn, param] = int(edge_dict[k][param])
                    else:
                        c[A_id, i, B_id, j, conn, param] = float(edge_dict[k][param])                        
            else:
                c[A_id, 'all', i, B_id, 'all', j, conn] = 1
                
                for param in edge_dict[k].keys():                    

                    # The ID loaded by networkx.read_gexf() is always a string, but
                    # should be interpreted as an integer:
                    if param == 'id':
                        c[A_id, 'all', i, B_id, 'all', j, conn, param] = int(edge_dict[k][param])
                    else:
                        c[A_id, 'all', i, B_id, 'all', j, conn, param] = float(edge_dict[k][param])                        
                
                    
    return c                        
        
