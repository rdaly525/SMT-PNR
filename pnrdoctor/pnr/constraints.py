'''
Constraint generators
'''
from functools import partial
import itertools
import random
import string
from collections import defaultdict

from pnrdoctor.design.module import Resource
from pnrdoctor.fabric.fabricutils import muxindex, trackindex
from pnrdoctor.smt.region import SYMBOLIC, Scalar, Category
from pnrdoctor.util import STAR

from .pnrutils import get_muxindex, get_muxindices


def init_regions(category_type, scalar_type):
    def initializer(region, fabric, design, state, vars, solver):
        constraints = []
        for module in design.modules:
            if module not in vars:
                vars[module] = dict()

            r = state[module]
            for d,p in r.position.items():
                if p is SYMBOLIC:
                    var = scalar_type(module.name + '_' + d.name, solver, d.size)
                    constraints.append(var.invariants)
                elif p is None:
                    continue
                else:
                    var = scalar_type(module.name + '_' + d.name, solver, d.size, p)
                vars[module][d] = var

            for d,c in r.category.items():
                if d == fabric.tracks_dim and module.resource != Resource.Reg:
                    continue
                if c is SYMBOLIC:
                    var = category_type(module.name + '_' + d.name, solver, d.size)
                    constraints.append(var.invariants)
                elif c is None:
                    continue
                else:
                    var = scalar_type(module.name + '_' + d.name, solver, d.size, c)
                vars[module][d] = var
        return solver.And(constraints)
    return initializer


def distinct(region, fabric, design, state, vars, solver):
    constraints = []
    for m1 in design.modules:
        for m2 in design.modules:
            if state[m1].parent == state[m2].parent and m1.resource == m2.resource and m1 != m2:
                v1,v2 = vars[m1],vars[m2]
                s = v1.keys() & v2.keys()
                c = []
                for d in s:
                    c.append(v1[d].distinct(v2[d]))

                constraints.append(solver.Or(c))
    return solver.And(constraints)

def neighborhood(delta):
    return partial(_neighborhood, delta)

def nearest_neighbor(region, fabric, design, state, vars, solver):
    return _neighborhood(1, region, fabric, design, state, vars, solver)

def _neighborhood(delta, region, fabric, design, state, vars, solver):
        # HACK will break for non-square fabric
        constraints = []
        for tie in design.ties:
            src = tie.src
            dst = tie.dst
            c = []
            src_v = vars[src]
            dst_v = vars[dst]
            s = src_v.keys() & dst_v.keys()

            total = None
            for d in s:
                if isinstance(d, Scalar):
                    dist = src_v[d].abs_delta(dst_v[d])

                    if total is None:
                        total = dist
                    else:
                        constraints.append(total <= total+dist)
                        total = total + dist

            if total is not None:
                constraints.append(total <= delta)
        return solver.And(constraints)


def register_colors(region, fabric, design, state, vars, solver):
    constraints = []
    for tie in design.ties:
        src = tie.src
        dst = tie.dst
        if src.resource == dst.resource == Resource.Reg:
            constraints.append(vars[src][fabric.tracks_dim] == vars[dst][fabric.tracks_dim])
    return solver.And(constraints)

def pin_IO(region, fabric, design, state, vars, solver):
    constraints = []
    for module in design.modules_with_attr_val('type_', 'IO'):
        v = vars[module]
        r,c = v[fabric.rows_dim], v[fabric.cols_dim]
        constraints.append(solver.Or([r == 0, c == 0]))
    return solver.And(constraints)


def pin_resource(region, fabric, design, state, vars, solver):
    constraints = []
    for module in design.modules:
        v = vars[module]
        r,c = v[fabric.rows_dim], v[fabric.cols_dim],

        cx = []
        for p in fabric.locations[module.resource]:
            if len(p) > 3 or len(p) < 2:
                raise NotImplementedError("Can't haldle dimension other than 2 / 3")

            cc = [r == p[0], c == p[1]]
            if len(p) == 3:
                cc.append(v[fabric.tracks_dim] == p[2])
            cx.append(solver.And(cc))
        constraints.append(solver.Or(cx))
    return solver.And(constraints)

def pin_resource_structured(fabric, design, state, vars, solver):
    constraints = []
    for module in design.modules:
        pos = vars[module]
        r, c = pos[fabric.rows_dim], pos[fabric.cols_dim]
        if module.resource == Resource.Mem:
            cc = []
            for col in fabric.resdimvals(Resource.Mem, 0):
                cc.append(c == col)
            constraints.append(solver.Or(cc))

            cr = []
            for row in fabric.resdimvals(Resource.Mem, 1):
                cr.append(r == row)
            constraints.append(solver.Or(cr))

        elif module.resource == Resource.Reg:
            c = []
            for col in fabric.resdimvals(Resource.Reg, 0):
                c.append(c == col)
            constraints.append(solver.Or(c))

        else:
            c = []
            # Not placed in a memory column
            for col in fabric.resdimvals(Resource.Mem, 0):
                c.append(c != col)
            constraints.append(solver.And(c))

    return solver.And(constraints)

#def init_random(position_type):
#    def initializer(fabric, design, state, vars, solver):
#        constraints = []
#        # random.shuffle shuffles in place and needs indexable data type
#        modules = list(design.modules)
#        random.shuffle(modules)
#        for module in modules:
#            if module not in vars:
#                randstring = ''
#                for s in random.sample(string.ascii_letters + string.digits, 5):
#                    randstring += s
#                p = position_type(module.name + randstring, fabric)
#                vars[module] = p
#                constraints.append(p.invariants)
#        return solver.And(constraints)
#    return initializer
#
#
#def assert_pinned(fabric, design, state, vars, solver):
#    constraints = []
#    for module in design.modules:
#        if module in state:
#            pos = vars[module]
#            constraints.append(pos == pos.encode(state[module][0]))
#    return solver.And(constraints)
#
#def pin_reg(reg, p):
#    def _pin_reg(fabric, design, state, vars, solver):
#        pos = vars[reg]
#        return solver.And(pos.x == pos.encode_x(p[0]), pos.y == pos.encode_y(p[1]))
#
#    return _pin_reg
#
#
#

################################### Routing Helper Functions ###########################
def _resource_region(loc, dist):
    ''' returns a set of locations in a radius of magnitude, dist, around loc'''
    s = set()
    dxdy_set = set((x, y) for x,y in itertools.product(range(-dist, dist+1), repeat=2) if abs(x) + abs(y) <= dist)
    for dxdy in dxdy_set:
        s.add((loc[0] + dxdy[0], loc[1] + dxdy[1]))

    return s


def _get_nonreg_input(reg):
    assert reg.resource == Resource.Reg, 'Expecting a register'
    assert len(reg.inputs) == 1, 'Register should have exactly one input'
    input_mod = next(iter(reg.inputs.values())).src

    while input_mod.resource == Resource.Reg:
        assert len(input_mod.inputs) == 1, 'Register should have exactly one input'
        input_mod = next(iter(input_mod.inputs.values())).src

    return input_mod

#################################### Routing Constraints ################################


################################ Graph Building/Modifying Functions #############################
def build_msgraph(fabric, design, p_state, r_state, vars, solver, layer=16):
    graph = solver.add_graph()

    node_inedges = defaultdict(list)

    # add nodes for modules
    for mod in design.modules:
        for _type in {'sources', 'sinks'}:
            for port_name in getattr(fabric.port_names[(mod.resource, layer)], _type):
                index = get_muxindex(mod, p_state, layer, port_name)
                p = getattr(fabric[index], _type[:-1])  # source/sink instead of sources/sinks
                vars[p] = graph.addNode(p.name)
                vars[(mod, port_name)] = vars[p]

    tindex = trackindex(src=STAR, snk=STAR, bw=layer)
    for track in fabric[tindex]:
        src = track.src
        dst = track.dst
        # naming scheme is (x, y)Side_direction[track]
        # checking port resources

        if src not in vars:
            vars[src] = graph.addNode(src.name)
        if dst not in vars:
            vars[dst] = graph.addNode(dst.name)

        # create a monosat edge
        e = graph.addEdge(vars[src], vars[dst])

        node_inedges[vars[dst]].append(e)

        vars[e] = track  # we need to recover the track in model_reader

    # save the node in edges for later use
    # it's cleaner to have this constraint in a separate  function
    node_inedges = map(lambda l: tuple(l), node_inedges.values())  # make hashable
    vars['node_inedges'] = frozenset(node_inedges)

    return solver.And([])


def build_spnr(region=0):
    # the region specifies how far from the original placement monosat can choose
    # TODO: support region != 0 in bitstream writer
    def _build_spnr(fabric, design, p_state, r_state, vars, solver, layer=16):
        '''
           Modifies an existing monosat graph to allow monosat to 'replace' components
           within a region around the original placement
        '''
        # For each port of each module, create an external node
        # make undirected edges to each location

        node_dict = dict()
        graph = solver.graphs[0]

        # list for holding edge equality constraints
        edge_constraints = list()

        # add virtual nodes for modules
        for mod in design.modules:
            if mod.resource != Resource.Reg:
                for _type in {'sources', 'sinks'}:
                    for port_name in getattr(fabric.port_names[(mod.resource, layer)], _type):
                        n = graph.addNode('{}_{}'.format(mod.name, port_name))
                        vars[(mod, port_name)] = n
                        node_dict[n] = list()
            else:
                # registers are not split
                # i.e. both port names point to same node
                regnode = graph.addNode(mod.name)
                vars[mod] = regnode  # have one index just for mod
                node_dict[regnode] = list()
                for _type in {'sources', 'sinks'}:
                    for port_name in getattr(fabric.port_names[(mod.resource, layer)], _type):
                        vars[(mod, port_name)] = regnode  # convenient to also index the same as other modules

            # take intersection with possible locations
            # register locations include the track, so remove track using map
            for loc in _resource_region(p_state[mod][0], 0) & set(map(lambda x: x[:2], fabric.locations[mod.resource])):
                if mod.resource != Resource.Reg:
                    eqedges = list()
                    for _type in {'sources', 'sinks'}:
                        for port_name in getattr(fabric.port_names[(mod.resource, layer)], _type):
                            mindex = muxindex(resource=mod.resource, ps=loc, bw=layer, port=port_name)
                            e = graph.addUndirectedEdge(vars[(mod, port_name)],
                                                        vars[getattr(fabric[mindex], _type[:-1])])
                                                        # source/sink instead of sources/sinks
                            eqedges.append(e)
                            node_dict[vars[(mod, port_name)]].append(e)

                    # assert that a placement places all ports of a given module in the same location
                    for e1, e2 in zip(eqedges, eqedges[1:]):
                        edge_constraints.append(solver.Eq(e1, e2))

                else:
                    # this is a register

                    # get all of the switch box muxes at the current location
                    mindices_pattern = muxindex(resource=Resource.SB, ps=loc,
                                                po=STAR, bw=layer, track=STAR)

                    # take only the ones with registers
                    mindices = set(fabric.matching_keys(mindices_pattern)) & fabric.muxindex_locations[Resource.Reg]

                    for mindex in mindices:
                        assert fabric[mindex].source == fabric[mindex].sink, \
                          'Cannot split registers and use build_spnr'
                        e = graph.addUndirectedEdge(vars[mod],
                                                    vars[fabric[mindex].source])
                        node_dict[vars[mod]].append(e)

        # assert that modules are only placed in one location
        for n, edges in node_dict.items():
            solver.AtMostOne(edges)

        return solver.And(edge_constraints)
    return _build_spnr


################################ Reachability Constraints #################################

def reachability(fabric, design, p_state, r_state, vars, solver, layer=16):
    '''
        Enforce reachability for ties in single graph encoding
        Works with build_msgraph, excl_constraints and dist_limit
    '''
    reaches = []
    graph = solver.graphs[0]

    for tie in design.ties:
        # hacky don't handle wrong layer
        if tie.width != layer:
            continue

        reaches.append(graph.reaches(vars[(tie.src, tie.src_port)],
                                     vars[(tie.dst, tie.dst_port)]))

    return solver.And(reaches)


############################## Exclusivity Constraints #########################

def at_most_one_driver(fabric, design, p_state, r_state, vars, solver, layer=16):
    # assert that each node acting as a dst has at most one driver
    for inedges in vars['node_inedges']:  # 'node_inedges' maps to a frozenset of lists of edges
        if len(inedges) > 1:
            solver.AtMostOne(inedges)

    return solver.And([])


def reg_unreachability(fabric, design, p_state, r_state, vars, solver, layer=16):
    '''
        Enforce unreachability constraints when register is a source.
        Intended to be used with at_most_one_driver
    '''

    # TODO: change to layer indexing
    graph = solver.graphs[0]
    constraints = []

    for m in design.modules:
        if m.resource == Resource.Reg:

            # get the first non register in the input path
            input_m = _get_nonreg_input(m)
            # get the outputs of the registers input
            input_m_outputs = {t for t in input_m.outputs.values()}

            for outport in fabric.port_names[(Resource.Reg, layer)].sources:
                for tie in input_m_outputs:
                    if tie.dst == m:
                        # ignore tie to itself
                        continue

                    constraints.append(~graph.reaches(vars[(m, outport)],
                                                      vars[tie.dst, tie.dst_port]))

    return solver.And(constraints)


def unreachability(fabric, design, p_state, r_state, vars, solver, layer=16):
    '''
        Exclusivity constraints for single graph encoding
        Works with build_msgraph, reachability and dist_limit
    '''
    c = []
    graph = solver.graphs[0]

    # for connected modules, make sure it's not connected to wrong inputs
    for tie in design.ties:
        # hacky don't handle wrong layer here
        # and if destination is a register, it only has one port
        # so it doesn't need exclusivity constraints
        if tie.width != layer or tie.dst.resource == Resource.Reg:
            continue

        src = tie.src
        dst = tie.dst

        src_index = get_muxindex(src, p_state, layer, tie.src_port)

        # get all the destination ports that connect these two modules
        s = set([n.dst_port for n in dst.inputs.values()
                 if n.src == src and n.src_port == tie.src_port])

        for port in fabric.port_names[(dst.resource, layer)].sinks - s:
            dst_index = get_muxindex(dst, p_state, layer, port)
            c.append(~graph.reaches(vars[fabric[src_index].source],
                                    vars[fabric[dst_index].sink]))

    # make sure modules that aren't connected are not connected
    for mdst in design.modules:
        inputs = {x.src for x in mdst.inputs.values()}

        for msrc in design.modules:
            if msrc != mdst and msrc not in inputs:
                # iterate through all port combinations for m2-->m1 connections
                for src_port, dst_port \
                    in itertools.product(fabric.port_names[(msrc.resource, layer)].sources,
                                         fabric.port_names[(mdst.resource, layer)].sinks):

                    dst_index = get_muxindex(mdst, p_state, layer, dst_port)
                    src_index = get_muxindex(msrc, p_state, layer, src_port)

                    # assert that these modules' ports do not connect
                    c.append(~graph.reaches(vars[fabric[src_index].source],
                                            vars[fabric[dst_index].sink]))

    return solver.And(c)


################################### Quality Constraints ####################################
def dist_limit(dist_factor, include_reg=False):
    '''
       Enforce a global distance constraint. Works with single or multi graph encoding
       dist_factor is intepreted as manhattan distance on a placement grid
       (i.e. distance between adjacent PEs is 1)
    '''
    if not isinstance(dist_factor, int):
        raise ValueError('Expected integer distance factor. Received {}'.format(type(dist_factor)))

    def dist_constraints(fabric, design, p_state, r_state, vars, solver, layer=16):
        constraints = []
        graph = solver.graphs[0]

        for tie in design.ties:
            # hacky don't handle wrong layer
            if tie.width != layer:
                continue

            src = tie.src
            dst = tie.dst

            src_index = get_muxindex(src, p_state, layer, tie.src_port)
            dst_index = get_muxindex(dst, p_state, layer, tie.dst_port)

            src_pos = p_state[src][0]
            dst_pos = p_state[dst][0]

            manhattan_dist = int(abs(src_pos[0] - dst_pos[0]) + abs(src_pos[1] - dst_pos[1]))

            # sometimes don't include registers -- based on include_reg flag
            # this is because heuristic placement of registers may require weird routes
            if dst.resource != Resource.Reg:
                # This is just a weird heuristic for now. We have to have at least 2*manhattan_dist because
                # for each jump it needs to go through a port. So 1 in manhattan distance is 2 in monosat distance
                # Additionally, because the way ports are connected (i.e. only accessible from horizontal or vertical tracks)
                # It often happens that a routing is UNSAT for just 2*manhattan_dist so instead we use a factor of 3 and add 1
                # You can adjust it with dist_factor
                heuristic_dist = 3*dist_factor*manhattan_dist + 3
                constraints.append(graph.distance_leq(vars[(src, tie.src_port)],
                                                      vars[(dst, tie.dst_port)],
                                                      heuristic_dist))
            elif include_reg:
                reg_heuristic_dist = 3*dist_factor*manhattan_dist + 3
                constraints.append(graph.distance_leq(vars[(src, tie.src_port)],
                                                      vars[(dst, tie.dst_port)],
                                                      reg_heuristic_dist))

        return solver.And(constraints)
    return dist_constraints


################################### Constraint Bundles ##################################

def regional_replace(region, dist_factor):
    simultaneous = True
    split_regs = False
    route_functions = build_msgraph, build_spnr(region), reachability, at_most_one_driver, \
      reg_unreachability, dist_limit(dist_factor, include_reg=True)
    return simultaneous, split_regs, route_functions


def reach_and_notreach(dist_factor):
    simultaneous = False
    split_regs = True
    route_functions = build_msgraph, reachability, unreachability, dist_limit(dist_factor)

    return simultaneous, split_regs, route_functions


def recommended_route_settings(relaxed=False):
    if relaxed:
        return regional_replace(0, 3)
    else:
        return regional_replace(0, 1)
