import operator
from .fabric import Fabric
from functools import partial
from pnrdoctor.smt import smt_util as su

from pnrdoctor.smt.region import SYMBOLIC, Scalar, Category
def init_regions(one_hot_type, category_type, scalar_type):
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
                if d.is_one_hot:
                    T = one_hot_type
                else:
                    T = category_type

                if c is SYMBOLIC:
                    var = T(module.name + '_' + d.name, solver, d.size)
                    constraints.append(var.invariants)
                elif c is None:
                    continue
                else:
                    var = T(module.name + '_' + d.name, solver, d.size, c)

                vars[module][d] = var
        return solver.And(constraints)
    return initializer

def neighborhood(delta):
    return partial(_neighborhood, delta)

def _neighborhood(delta, region, fabric, design, state, vars, solver):
        # HACK will break for non-square fabric
        print('neighborhood')
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
                if d is not fabric.luts_dim:
                    dist = src_v[d].abs_delta(dst_v[d])
                    if total is None:
                        total = dist
                    else:
                        constraints.append(solver.BVUle(total, total+dist))
                        total = total + dist

            if total is not None:
                constraints.append(solver.BVUle(total, delta))
        return solver.And(constraints)

def smart_dist(delta, max):
    return partial(_smart_dist, delta, max)

def _smart_dist(delta, max, region, fabric, design, state, vars, solver):
    constraints = []
    total = None
    for tie in design.ties:
        src = tie.src
        dst = tie.dst
        c = []
        src_v = vars[src]
        dst_v = vars[dst]
        s = src_v.keys() & dst_v.keys()
        total_i = None
        for d in s:
            if d is not fabric.luts_dim:
                dist = src_v[d].abs_delta(dst_v[d])

                if total_i is None:
                    total_i = dist
                else:
                    part = su.safe_op(operator.add, solver, total_i, dist)
                    constraints.append(solver.BVUle(total_i, part))
                    total_i = part
        if total_i is not None:
            constraints.append(solver.BVUle(total_i, delta))
            if total is None:
                total = total_i
            else:
                part = su.safe_op(operator.add, solver, total, total_i)
                constraints.append(solver.BVUle(total, part))
                total = part

    if total is not None:
        constraints.append(solver.BVUle(total, max))

    return solver.And(constraints)


def pin_resource(region, fabric, design, state, vars, solver):
    constraints = []
    for module in design.modules:
        v = vars[module]
        loc = tuple(v[d] for d in fabric.dims)
        #print(loc)

        cx = []
        for pos in fabric.locations[module.resource]:
            cc = [l == p for l,p in zip(loc, pos)]
            cx.append(solver.And(cc))
        constraints.append(solver.Or(cx))
    return solver.And(constraints)


def pin_resource_structured(region, fabric, design, state, vars, solver):
    R = Fabric.Resource
    constraints = []

    for module in design.modules:
        v = vars[module]
        r,c,l = v[fabric.rows_dim], v[fabric.cols_dim], v[fabric.luts_dim]

        # no corners
        cc = solver.And([
            solver.Not(solver.And([r == 0,             c ==0])),
            solver.Not(solver.And([r == 0,             c == fabric.cols-1])),
            solver.Not(solver.And([r == fabric.rows-1, c == 0])),
            solver.Not(solver.And([r == fabric.rows-1, c == fabric.cols-1])),
        ])
        constraints.append(cc)

        res = module.resource
        if res in (R.IO, R.Logic):
            #row or column has to be an edge
            c_io = [solver.Or([
                r == 0,
                r == fabric.rows-1,
                c == 0,
                c == fabric.cols-1,
            ])]
            if res == R.IO:
                c_io.append(solver.Or([l == 0, l == 1]))
                c_io = solver.And(c_io)
            else:
                c_io = solver.Not(solver.And(c_io))
            constraints.append(c_io)



        if res in (R.Mem, R.Logic) :
            c_mem = [solver.Or([c == 3, c == 10])]
            if res == R.Mem:
                c_mem.append(l == 0)
                c_mem.append(solver.Extract(r.var, 0, 0) == 0)
                c_mem = solver.And(c_mem)
            else:
                c_mem = solver.Not(solver.And(c_mem))
            constraints.append(c_mem)


    return solver.And(constraints)


