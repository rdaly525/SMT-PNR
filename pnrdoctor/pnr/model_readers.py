from pnrdoctor.design.module import Resource
from pnrdoctor.fabric.fabricutils import trackindex
from .pnrutils import get_muxindices

def place_model_reader(fabric, design, state, vars, solver):
    for module, var in vars.items():
        if module.resource == Resource.Reg:
            state[module] = var.get_coordinates() + (var.get_color(),)
        else:
            state[module] = var.get_coordinates()


def route_model_reader(simultaneous=False):
    def _route_model_reader(fabric, design, p_state, r_state, vars, solver):

        # make sure there are never two drivers of the same port
        invariant_check = dict()

        # TODO: set up design views so can iterate by layer
        for tie in design.ties:
            graph = solver.graphs[tie.width]

            src_node = vars[(tie.src, tie.src_port)]
            dst_node = vars[(tie.dst, tie.dst_port)]
            reaches = graph.reaches(src_node, dst_node)
            l = graph.getPath(reaches)
            assert l is not None, tie
            path = tuple(graph.names[node] for node in l)
            # record for debug printing
            r_state[(tie, 'debug')] = path

            # when simultaneous, the edges on the end are virtual
            if simultaneous:
                l = l[1:-1]

            for n1, n2 in zip(l, l[1:]):
                edge = graph.getEdge(n1, n2)
                track = vars[edge]

                if track in invariant_check:
                    assert tie.src == invariant_check[track.dst], '{} driven by {} and {}'.format(track.dst, invariant_check[track.dst], tie.src)

                invariant_check[track.dst] = tie.src

                dst = track.dst

                r_state[tie] = trackindex(snk=dst.index, src=track.src.index, bw=tie.width)

    return _route_model_reader
