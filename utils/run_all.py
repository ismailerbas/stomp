#!/usr/bin/env python3
#
# Copyright 2018 IBM
#
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
#

# DESCRIPTION:
#  This script is used to kick off a run of a large number of tests.
#  It is derived from run_all.py but adds another search dimension --
#  the scaling of the mean task arrival time (ARRIVE_SCALE).
#  This script also supports the output of the results in a "CSV"
#   format, automatically converting the outputs to be comma-separated
#   and to be written into files ending in .csv
#
from __future__ import print_function
import os
import subprocess
import json
import time
import sys
import shutil
import getopt
import numpy as np
from sys import stdout
from subprocess import check_output
from collections import defaultdict
from builtins import str

JOBS_LIM = 96

PWR_MGMT     = [False]
PTOKS        = [100000] # [6500, 7000, 7500, 8000, 8500, 9000, 9500, 10000] # , 10500, 11000, 11500, 12000, 12500, 13000, 13500, 14000, 14500, 15000, 100000]
# SLACK_PERC   = [0.0, 98.4]
SLACK_PERC   = np.linspace(0, 100, 50, endpoint=True).tolist()
folder = ""

CONF_FILE        = None #Automatically set based on app
PROMOTE          = False
CONTENTION       = [False] #, False]

APP              = ['fli']
FLAVOR           = ['original', 'seq2seqlite']
TYPE             = ['enc', 'dec', 'pp']
# TYPE             = ['pp']
POLICY_SOTA      = [] #'ads', 'edf_eft', 'rheft', 'heft']
POLICY_NEW       = ['simple_policy_ver2'] #,'ms1_hom','ms1_hetero','ms1_hyb', 'ms1_hyb_update', 'ms2_hom','ms2_hetero','ms2_hyb', 'ms2_hyb_update']
POLICY           = POLICY_SOTA + POLICY_NEW
#NEW
ARRIVE_SCALE     = [1.0] #[1.0, 1.0, 1.0, 1.0, 1.0, 1.0] # synthetic, ad
PLLEL_PIXEL      = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024] #[1, 2, 4, 8, 12, 16]
# PLLEL_PIXEL      = [256, 512, 1024, 2048, 4096, 8192, 2**14, 2**15, 2**16] #[1, 2, 4, 8, 12, 16]
DROP             = [False]

TIMESTEPS        = [1] #, 5] #1, 5, 10, 70]

RUNS = 1#32#50
DELTA = 0#5#1.0

total_count = len(APP) * len(POLICY) * len(ARRIVE_SCALE) * len(PLLEL_PIXEL) * len(DROP)
print("Total jobs launched: {}".format(total_count))

def usage_and_exit(exit_code):
    stdout.write('\nusage: run_all.py [--help] [--verbose] [--csv-out] [--save-stdout] [--user-input-trace] [--user-input-trace-debug] [--run_hetero]\n\n')
    sys.exit(exit_code)

def main(argv):
    try:
        opts, args = getopt.getopt(argv,"hvcsudr",["help", "verbose", "csv-out", "save-stdout", "user-input-trace", "user-input-trace-debug","run_hetero"])
    except getopt.GetoptError:
        usage_and_exit(2)

    verbose               = False
    save_stdout           = False
    use_user_input_trace  = False
    trace_debug           = False
    do_csv_output         = False
    out_sep               = '\t'
    run                   = ''
    ACCEL_COUNT           = 1

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage_and_exit(0)
        elif opt in ("-v", "--verbose"):
            verbose = True
        elif opt in ("-c", "--csv-out"):
            do_csv_output = True
            out_sep = ','
        elif opt in ("-s", "--save-stdout"):
            save_stdout = True
        elif opt in ("-u", "--user-input-trace"):
            use_user_input_trace = True
        elif opt in ("-d", "--user-input-trace-debug"):
            trace_debug = True
        elif opt in ("-r", "--run_hetero"):
            run = 'hetero'
            ACCEL_COUNT = 6
        else:
            stdout.write('\nERROR: Unrecognized input parameter %s\n' % opt)
            usage_and_exit(3)

    process = []
    run_count = 0
    # Simulation directory
    for app in APP:
        for flavor in FLAVOR:
            for dag_type in TYPE:
                if flavor == 'seq2seqlite':
                    app_name = str(app) + '_seq2seqlite'
                else:
                    app_name = str(app)
                sim_dir = "output/" + str(app_name) + "_" + str(dag_type) + "/" + time.strftime("sim_%d%m%Y_%H%M%S")
                if os.path.exists(sim_dir):
                    shutil.rmtree(sim_dir)
                os.makedirs(sim_dir)

                # This dict is used to temporarily hold the output from the
                # different runs. Everything is dumped to files later on.
                sim_output = {}

                start_time = time.time()
                num_executions = 0
                first_time = True

                # We open the JSON config file and update the corresponding
                # parameters directly in the stomp_params dicttionary
                if app == "synthetic":
                    CONF_FILE = './inputs/stomp.json'
                elif app == "fli":
                    CONF_FILE = './inputs/stomp_fli.json'
                else:
                    CONF_FILE = './inputs/stomp_real.json'

                with open(CONF_FILE) as conf_file:
                    stomp_params = json.load(conf_file)

                stomp_params['general']['working_dir'] = os.getcwd() + '/' + sim_dir


                ###############################################################################################
                # MAIN LOOP
                for pwr_mgmt in PWR_MGMT:
                    if pwr_mgmt == False:
                        SLACK_PERC_ = [0]
                        PTOKS_ = [1000000]
                    else:
                        SLACK_PERC_ = SLACK_PERC
                        PTOKS_ = PTOKS
                    for slack_perc in SLACK_PERC_:
                        for drop in DROP:
                            for cont in CONTENTION:
                                for x in range(0,len(PLLEL_PIXEL)):
                                    print(x)
                                    pllel_pixel = PLLEL_PIXEL[x]

                                    for timestep in TIMESTEPS:

                                        #for arr_scale in ARRIVE_SCALE:
                                        for y in range(0,RUNS):
                                            for policy in POLICY:
                                                arr_scale = ARRIVE_SCALE[0] + DELTA*y
                                                print("Pllel Pixel: " + str(pllel_pixel) + "arr_scale: " + str(arr_scale))
                                                # print(ARRIVE_SCALE0+ARRIVE_SCALE2)
                                                # if (policy in POLICY_NEW and (drop == False)):
                                                #     print("Only dropping for NEW/Not arr_scale", policy, drop, arr_scale)
                                                #     continue

                                                print("Running", policy, drop, arr_scale, run_count)

                                                for ptoks in PTOKS_:
                                                    sim_output[arr_scale] = {}
                                                    stomp_params['simulation']['pwr_mgmt'] = pwr_mgmt
                                                    stomp_params['simulation']['total_ptoks'] = ptoks
                                                    stomp_params['simulation']['slack_perc'] = slack_perc
                                                    stomp_params['simulation']['arrival_time_scale'] = arr_scale

                                                    first_flag = False
                                                    for dsp_count in [128, 256, 512]: #range(0,10,2):
                                                        for sharedmem_count in [128]: #range(2,10,2):
                                                            for constmem_count in [128]: #range(0,10,2):
                                                                for datamem_count in [256]: #range(0,10,2):
                                                                    stomp_params['simulation']['servers']['DSP']['count'] = dsp_count
                                                                    stomp_params['simulation']['servers']['Shared mem']['count'] = sharedmem_count
                                                                    stomp_params['simulation']['servers']['Const mem']['count'] = constmem_count
                                                                    stomp_params['simulation']['servers']['data mem']['count'] = datamem_count
                                                                    print("Running for D: %d SMem:%d CMem:%d DMem:%d" %(dsp_count, sharedmem_count, constmem_count, datamem_count))

                                                                    run_count += 1
                                                                    sim_output[arr_scale][policy] = {}

                                                                    stomp_params['simulation']['drop']         = drop
                                                                    stomp_params['simulation']['contention']   = cont
                                                                    stomp_params['simulation']['promote']      = PROMOTE

                                                                    sim_output[arr_scale][policy] = {}
                                                                    sim_output[arr_scale][policy]['avg_resp_time'] = {}
                                                                    sim_output[arr_scale][policy]['met_deadline'] = {}

                                                                    ###########################################################################################
                                                                    # Update the simulation configuration by updating
                                                                    # the specific parameters in the input JSON data
                                                                    stomp_params['simulation']['application'] = app_name
                                                                    stomp_params['simulation']['policy'] = policy
                                                                    print(stomp_params['simulation']["policies"][policy])
                                                                    stomp_params['simulation']['sched_policy_module'] = 'task_policies.' + stomp_params['simulation']["policies"][policy]["task_policy"]
                                                                    stomp_params['simulation']['meta_policy_module'] = 'meta_policies.' + stomp_params['simulation']["policies"][policy]["meta_policy"]

                                                                    stomp_params['general']['basename'] = policy + \
                                                                        "_pwr_mgmt_" + str(pwr_mgmt) + \
                                                                        "_slack_perc_" + str(slack_perc) + \
                                                                        "_cont_" + str(cont) + \
                                                                        "_drop_" + str(drop) + \
                                                                        '_ptoks_' + str(ptoks) + \
                                                                        "_arr_" + str(arr_scale) + \
                                                                        '_llpixel_' + str(pllel_pixel) + \
                                                                        '_timestep_' + str(timestep) + \
                                                                        '_dsp_' + str(dsp_count) + \
                                                                        '_smem_' + str(sharedmem_count) + \
                                                                        '_cmem_' + str(constmem_count) + \
                                                                        '_dmem_' + str(datamem_count)
                                                                    stdout_fname=sim_dir + "/out_" + stomp_params['general']['basename']
                                                                    
                                                                    conf_str = json.dumps(stomp_params)

                                                                    ###########################################################################################
                                                                    # Create command and execute the simulation

                                                                    command = ['python ./simulator/stomp_main.py'
                                                                            + ' -c ' + CONF_FILE
                                                                            + ' -j \'' + conf_str + '\''
                                                                            ]
                                                                    command_str = ' '.join(command)
                                                                    command_str = command_str + ' -i ../../../inputs/' + str(app_name) + '/trace_files/' + str(app) + '_' + str(dag_type) + '_' + str(pllel_pixel) + '_' + str(timestep)+ '.trc'
                                                                    #To run on CCC lsf cluster
                                                                    command_str = 'jbsub -cores 8+1 -mem 24G -o ' + stdout_fname + ' ' + command_str
                                                                    
                                                                    if (verbose):
                                                                        print('Running', command_str)
                                                                        # exit()
                                                                    sys.stdout.flush()

                                                                    with open(stdout_fname, 'wb') as out:
                                                                        print("Running command")
                                                                        p = subprocess.Popen(command_str, stdout=out, stderr=subprocess.STDOUT, shell=True)
                                                                        process.append(p)
                                                                        print("Process count now: {} (lim {})".format(len(process), JOBS_LIM))
                                                                        if len(process) >= JOBS_LIM:
                                                                            print(str(run_count) + "/" + str(total_count))
                                                                            for p in process:
                                                                                p.wait()
                                                                            del process[:]

    for p in process:
        p.wait()

if __name__ == "__main__":
   main(sys.argv[1:])
