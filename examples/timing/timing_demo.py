#!/usr/bin/env python

"""
Create and run multiple empty LPUs to time data reception throughput.
"""

import argparse
import itertools
import numpy as np
import pycuda.driver as drv

from neurokernel.base import setup_logger
from neurokernel.core import Manager, Module, PORT_DATA, PORT_CTRL, PORT_TIME
from neurokernel.pattern import Pattern
from neurokernel.plsel import PathLikeSelector
from neurokernel.tools.comm import get_random_port

class MyModule(Module):
    """
    Empty module class.

    This module class doesn't do anything in its execution step apart from
    transmit/receive dummy data. All spike ports are assumed to
    produce/consume data at every step.        
    """

    def __init__(self, sel, 
                 sel_in_gpot, sel_in_spike,
                 sel_out_gpot, sel_out_spike,
                 data_gpot=None, data_spike=None,
                 columns=['interface', 'io', 'type'],
                 port_data=PORT_DATA, port_ctrl=PORT_CTRL, port_time=PORT_TIME,
                 id=None, device=None, debug=False):
        sel_gpot = ','.join([sel_in_gpot, sel_out_gpot])
        sel_spike = ','.join([sel_in_spike, sel_out_spike])
        if data_gpot is None:    
            data_gpot = np.zeros(PathLikeSelector.count_ports(sel_gpot), float)
        if data_spike is None:    
            data_spike = np.zeros(PathLikeSelector.count_ports(sel_gpot), int)
                
        super(MyModule, self).__init__(sel, sel_gpot, sel_spike,
                                       data_gpot, data_spike,
                                       columns, port_data, port_ctrl, port_time,
                                       id, device, debug, True)

        assert PathLikeSelector.is_in(sel_in_gpot, sel)
        assert PathLikeSelector.is_in(sel_out_gpot, sel)
        assert PathLikeSelector.are_disjoint(sel_in_gpot, sel_out_gpot)
        assert PathLikeSelector.is_in(sel_in_spike, sel)
        assert PathLikeSelector.is_in(sel_out_spike, sel)
        assert PathLikeSelector.are_disjoint(sel_in_spike, sel_out_spike)

        self.interface[sel_in_gpot, 'io', 'type'] = ['in', 'gpot']
        self.interface[sel_out_gpot, 'io', 'type'] = ['out', 'gpot']
        self.interface[sel_in_spike, 'io', 'type'] = ['in', 'spike']
        self.interface[sel_out_spike, 'io', 'type'] = ['out', 'spike']

        self.pm['gpot'][self.interface.out_ports().gpot_ports().to_tuples()] = 1.0
        self.pm['spike'][self.interface.out_ports().spike_ports().to_tuples()] = 1

def gen_sels(n_lpu, n_spike, n_gpot):
    """
    Generate port selectors for LPUs in benchmark test.

    Parameters
    ----------
    n_lpu : int
        Number of LPUs. Must be at least 2.
    n_spike : int
        Total number of input and output spiking ports any 
        single LPU exposes to any other LPU. Each LPU will therefore
        have 2*n_spike*(n_lpu-1) total spiking ports.
    n_gpot : int
        Total number of input and output graded potential ports any 
        single LPU exposes to any other LPU. Each LPU will therefore
        have 2*n_gpot*(n_lpu-1) total graded potential ports.

    Returns
    -------
    results : dict of tuples
        The keys of the result are the module IDs; the values are tuples
        containing the respective selectors for input graded potential, 
        input spike, output graded potential, and output spike ports.
    """

    assert n_lpu >= 2
    assert n_spike >= 0
    assert n_gpot >= 0

    results = {}

    for i in xrange(n_lpu):
        lpu_id = 'lpu%s' % i            
        other_lpu_ids = '['+','.join(['lpu%s' % j for j in xrange(n_lpu) if j != i])+']'

        # Structure ports as 
        # /lpu_id/in_or_out/spike_or_gpot/[other_lpu_ids,..]/[0:n_spike]
        sel_in_gpot = '/%s/in/gpot/%s/[0:%i]' % (lpu_id,
                                                 other_lpu_ids, 
                                                 n_gpot)
        sel_in_spike = '/%s/in/spike/%s/[0:%i]' % (lpu_id,
                                                   other_lpu_ids, 
                                                   n_spike)
        sel_out_gpot = '/%s/out/gpot/%s/[0:%i]' % (lpu_id, 
                                                   other_lpu_ids,
                                                   n_gpot)
        sel_out_spike = '/%s/out/spike/%s/[0:%i]' % (lpu_id, 
                                                     other_lpu_ids,
                                                     n_spike)
        results[lpu_id] = (sel_in_gpot, sel_in_spike,
                           sel_out_gpot, sel_out_spike)                        
                           
    return results

def emulate(n_lpu, n_spike, n_gpot, steps):
    """
    Benchmark inter-LPU communication throughput.

    Each LPU is configured to use a different local GPU.

    Parameters
    ----------
    n_lpu : int
        Number of LPUs. Must be at least 2 and no greater than the number of
        local GPUs.
    n_spike : int
        Total number of input and output spiking ports any 
        single LPU exposes to any other LPU. Each LPU will therefore
        have 2*n_spike*(n_lpu-1) total spiking ports.
    n_gpot : int
        Total number of input and output graded potential ports any 
        single LPU exposes to any other LPU. Each LPU will therefore
        have 2*n_gpot*(n_lpu-1) total graded potential ports.
    steps : int
        Number of steps to execute.
    """

    # Check whether a sufficient number of GPUs are available:
    drv.init()
    if n_lpu > drv.Device.count():
        raise RuntimeError('insufficient number of available GPUs.')

    man = Manager(get_random_port(), get_random_port(), get_random_port())
    man.add_brok()

    # Set up modules:
    sel_dict = gen_sels(n_lpu, n_spike, n_gpot)
    for i in xrange(n_lpu):
        lpu_i = 'lpu%s' % i
        sel = ','.join(sel_dict[lpu_i])
        sel_in_gpot, sel_in_spike, sel_out_gpot, sel_out_spike = sel_dict[lpu_i]
        m = MyModule(sel, 
                     sel_in_gpot, sel_in_spike, sel_out_gpot, sel_out_spike,
                     port_data=man.port_data, port_ctrl=man.port_ctrl,
                     port_time=man.port_time,
                     id=lpu_i, device=i, debug=args.debug)
        man.add_mod(m)
    
    # Set up connections between module pairs:
    for i, j in itertools.combinations(xrange(n_lpu), 2):
        lpu_i = 'lpu%s' % i
        lpu_j = 'lpu%s' % j
        sel_in_gpot_i, sel_in_spike_i, sel_out_gpot_i, sel_out_spike_i = \
            sel_dict[lpu_i]
        sel_in_gpot_j, sel_in_spike_j, sel_out_gpot_j, sel_out_spike_j = \
            sel_dict[lpu_j]
        sel_from = sel_out_gpot_i+','+sel_out_spike_i+','+sel_out_gpot_j+','+sel_out_spike_j
        sel_to = sel_in_gpot_j+','+sel_in_spike_j+','+sel_in_gpot_i+','+sel_in_spike_i
        pat = Pattern.from_concat(sel_from, sel_to,
                                  from_sel=sel_from, to_sel=sel_to, data=1)
        pat.interface[sel_in_gpot_i] = [0, 'out', 'gpot']
        pat.interface[sel_out_gpot_i] = [0, 'in', 'gpot']
        pat.interface[sel_in_spike_i] = [0, 'out', 'spike']
        pat.interface[sel_out_spike_i] = [0, 'in', 'spike']
        pat.interface[sel_in_gpot_j] = [1, 'out', 'gpot']
        pat.interface[sel_out_gpot_j] = [1, 'in', 'gpot']
        pat.interface[sel_in_spike_j] = [1, 'out', 'spike']
        pat.interface[sel_out_spike_j] = [1, 'in', 'spike']
        man.connect(man.modules[lpu_i], man.modules[lpu_j], pat, 0, 1)
        
    man.start(steps=steps)
    man.stop()

if __name__ == '__main__':
    num_lpus = 2
    num_gpot = 100
    num_spike = 100
    max_steps = 100

    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', default=False,
                        dest='debug', action='store_true',
                        help='Enable debug mode.')
    parser.add_argument('-l', '--log', default='none', type=str,
                        help='Log output to screen [file, screen, both, or none; default:none]')
    parser.add_argument('-u', '--num_lpus', default=num_lpus, type=int,
                        help='Number of LPUs [default: %s]' % num_lpus)
    parser.add_argument('-s', '--num_spike', default=num_spike, type=int,
                        help='Number of spiking ports [default: %s]' % num_spike)
    parser.add_argument('-g', '--num_gpot', default=num_gpot, type=int,
                        help='Number of graded potential ports [default: %s]' % num_gpot)
    parser.add_argument('-m', '--max_steps', default=max_steps, type=int,
                        help='Maximum number of steps [default: %s]' % max_steps)
    args = parser.parse_args()

    file_name = None
    screen = False
    if args.log.lower() in ['file', 'both']:
        file_name = 'neurokernel.log'
    if args.log.lower() in ['screen', 'both']:
        screen = True
    logger = setup_logger(file_name, screen)

    emulate(args.num_lpus, args.num_spike, args.num_gpot, args.max_steps)

        
