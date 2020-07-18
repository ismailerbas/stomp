#!/usr/bin/env python
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
import getopt
import numpy as np
from sys import stdout
from subprocess import check_output
from collections import defaultdict
from __builtin__ import str


JOBS_LIM = 32
PWR_MGMT     = [False]
PTOKS        = [100000] # [6500, 7000, 7500, 8000, 8500, 100000]
SLACK_PERC   = [100] # np.arange(50, 101, 50).tolist()

CONF_FILE        = None #Automatically set based on app
PROMOTE          = True

APP              = ['synthetic', 'ad', 'mapping', 'package']
POLICY_SOTA      = ['heft', 'rheft', 'edf', 'edf_ver5', 'simple_policy_ver2', 'simple_policy_ver5']
POLICY_NEW       = ['ms1', 'ms1_update', 'ms2', 'ms2_update', 'ms3', 'ms3_update']
POLICY           = POLICY_SOTA + POLICY_NEW
STDEV_FACTOR     = [0.01] # percentages
ARRIVE_SCALE     = [0.1, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0] # percentages
# ARRIVE_SCALE     = [6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0] # percentages
PROB             = [0.1, 0.2, 0.3] 
DROP             = [False, True]
dl_scale         = 1

total_count = len(APP) * len(POLICY) * len(STDEV_FACTOR) * len(ARRIVE_SCALE) * len(PROB) * len(DROP)

def usage_and_exit(exit_code):
    stdout.write('\nusage: run_all.py [--help] [--verbose] [--csv-out] [--save-stdout] [--pre-gen-tasks] [--arrival-trace] [--input-trace] [--user-input-trace] [--user-input-trace-debug]\n\n')
    sys.exit(exit_code)

def main(argv):
    try:
        opts, args = getopt.getopt(argv,"hvcspaiud",["help", "verbose", "csv-out", "save-stdout", "pre-gen-tasks", "arrival-trace", "input-trace", "user-input-trace", "user-input-trace-debug"])
    except getopt.GetoptError:
        usage_and_exit(2)

    verbose               = False
    save_stdout           = False
    pre_gen_tasks         = False
    use_arrival_trace     = False
    use_input_trace       = False
    use_user_input_trace  = False
    trace_debug           = False
    do_csv_output         = False
    out_sep               = '\t'

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
        elif opt in ("-p", "--pre-gen-tasks"):
            pre_gen_tasks = True
        elif opt in ("-a", "--arrival-trace"):
            use_arrival_trace = True
        elif opt in ("-i", "--input-trace"):
            use_input_trace = True
        elif opt in ("-u", "--user-input-trace"):
            use_user_input_trace = True
        elif opt in ("-d", "--user-input-trace-debug"):
            trace_debug = True
        else:
            stdout.write('\nERROR: Unrecognized input parameter %s\n' % opt)
            usage_and_exit(3)

    if (use_arrival_trace and use_input_trace):
        stdout.write('\nERROR: Cannot specify both arrival-trace and input-trace\n')
        usage_and_exit(4)

    if (use_arrival_trace and use_user_input_trace):
        stdout.write('\nERROR: Cannot specify both arrival-trace and user-input-trace\n')
        usage_and_exit(4)

    if (use_user_input_trace and use_input_trace):
        stdout.write('\nERROR: Cannot specify both use_user-input-trace and input-trace\n')
        usage_and_exit(4)


    process = []
    # Simulation directory
    for app in APP:
        sim_dir = time.strftime("sim_%d%m%Y_%H%M") + "_" + str(app)
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
            CONF_FILE = './stomp.json'
        else:
            CONF_FILE = './stomp2.json'

        with open(CONF_FILE) as conf_file:
            stomp_params = json.load(conf_file)

        stomp_params['general']['working_dir'] = os.getcwd() + '/' + sim_dir

        run_count = 0
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
                    for prob in PROB:
                        for arr_scale in ARRIVE_SCALE:
                            if(app == "ad"):
                                dl_scale = 5
                            elif(app == "mapping" or app == "package"):
                                dl_scale = 2.5
                            arr_scale = arr_scale/dl_scale
                            for ptoks in PTOKS_:

                                # if arr_scale < (1/stomp_params['simulation']['deadline_scale']):
                                #     print("Error: for arr_scale: %d. Arrival_scale less than 1 is not supported" %(arr_scale))
                                #     break

                                sim_output[arr_scale] = {}
                                stomp_params['simulation']['pwr_mgmt'] = pwr_mgmt
                                stomp_params['simulation']['total_ptoks'] = ptoks
                                stomp_params['simulation']['slack_perc'] = slack_perc
                                stomp_params['simulation']['arrival_time_scale'] = arr_scale

                                for policy in POLICY:
                                    if (policy in POLICY_SOTA and drop == True):
                                        print("No dropping for SOTA", policy)
                                        continue

                                    run_count += 1
                                    sim_output[arr_scale][policy] = {}

                                    stdev_factor = STDEV_FACTOR[0]
                                    stomp_params['simulation']['stdev_factor'] = stdev_factor
                                    stomp_params['simulation']['drop']         = drop
                                    stomp_params['simulation']['promote']      = PROMOTE

                                    sim_output[arr_scale][policy][stdev_factor] = {}
                                    sim_output[arr_scale][policy][stdev_factor]['avg_resp_time'] = {}
                                    sim_output[arr_scale][policy][stdev_factor]['met_deadline'] = {}

                                    ###########################################################################################
                                    # Update the simulation configuration by updating
                                    # the specific parameters in the input JSON data
                                    stomp_params['simulation']['application'] = app
                                    stomp_params['simulation']['policy'] = policy
                                    stomp_params['simulation']['sched_policy_module'] = 'policies.' + stomp_params['simulation']["policies"][policy]['tsched_policy']
                                    stomp_params['simulation']['meta_policy_module'] = 'meta_policies.' + stomp_params['simulation']["policies"][policy]['meta_policy']
                                    stomp_params['simulation']['deadline_scale'] = dl_scale
                                    if(app == "ad"):
                                        stomp_params['simulation']['mean_arrival_time'] = 50
                                    elif(app == "mapping" or app == "package"):
                                        stomp_params['simulation']['mean_arrival_time'] = 25
                                    for task in stomp_params['simulation']['tasks']:
                                        # Set the stdev for the service time
                                        for server, mean_service_time in stomp_params['simulation']['tasks'][task]['mean_service_time'].items():
                                            stdev_service_time = (stdev_factor*mean_service_time)
                                            stomp_params['simulation']['tasks'][task]['stdev_service_time'][server] = stdev_service_time

                                    stomp_params['general']['basename'] = policy + \
                                        "_pwr_mgmt_" + str(pwr_mgmt) + \
                                        "_slack_perc_" + str(slack_perc) + \
                                        "_drop_" + str(drop) + \
                                        "_arr_" + str(arr_scale) + \
                                        '_prob_' + str(prob) + \
                                        '_ptoks_' + str(ptoks)
                                    conf_str = json.dumps(stomp_params)

                                    ###########################################################################################
                                    # Create command and execute the simulation

                                    command = ['./stomp_main.py'
                                               + ' -c ' + CONF_FILE
                                               + ' -j \'' + conf_str + '\''
                                               ]

                                    command_str = ' '.join(command)

                                    if (pre_gen_tasks):
                                        command_str = command_str + ' -p'

                                    if (use_arrival_trace):
                                        if (policy == POLICY[0]) and (stdev_factor == STDEV_FACTOR[0]):
                                            command_str = command_str + ' -g generated_arrival_trace.trc'
                                        else:
                                            command_str = command_str + ' -a generated_arrival_trace.trc'

                                    if (use_input_trace):
                                        if (policy == POLICY[0]):
                                            command_str = command_str + ' -g generated_trace_stdf_' + str(stdev_factor) + '.trc'
                                        else:
                                            command_str = command_str + ' -i generated_trace_stdf_' + str(stdev_factor) + '.trc'
                                    
                                    if trace_debug:
                                        command_str = command_str + ' -i ../user_traces/user_gen_trace_prob_' + str(prob) + '.trc.trim'
                                    elif (use_user_input_trace):
                                        if (app == 'synthetic'):
                                            command_str = command_str + ' -i ../user_traces/user_gen_trace_prob_' + str(prob) + '.trc'
                                        elif (app == 'ad'):
                                            command_str = command_str + ' -i ../input_trace/ad_' + str(stomp_params['simulation']['mean_arrival_time']) + '_trace_uniform_' + str(int(prob*100)) + '.trc'
                                        elif (app == 'mapping'):
                                            command_str = command_str + ' -i ../input_trace/mapping_' + str(stomp_params['simulation']['mean_arrival_time']) + '_trace_uniform_' + str(int(prob*100)) + '.trc'
                                        elif (app == 'package'):
                                            command_str = command_str + ' -i ../input_trace/package_' + str(stomp_params['simulation']['mean_arrival_time']) + '_trace_uniform_' + str(int(prob*100)) + '.trc'

                                    if (verbose):
                                        print('Running', command_str)

                                    sys.stdout.flush()
                                    # output = subprocess.check_output(command_str, stderr=subprocess.STDOUT, shell=True)
                                    stdout_fname=sim_dir + "/out" + str(run_count) + "_" + stomp_params['general']['basename']
                                    with open(stdout_fname, 'wb') as out:
                                        p = subprocess.Popen(command_str, stdout=out, stderr=subprocess.STDOUT, shell=True)
                                        process.append(p)
                                        if len(process) >= JOBS_LIM:
                                            print(str(run_count) + "/" + str(total_count))
                                            for p in process:
                                                p.wait()
                                            del process[:]
        
    for p in process:
        p.wait()
                                    # if (save_stdout):
                                    #     fh = open(sim_dir + '/run_stdout_' + policy + "_drop_" + str(drop) + "_arr_" + str(arr_scale) + '_prob_' + str(prob) + '.out', 'w')

                                    # ###########################################################################################
                                    # # Parse the output line by line
                                    # output_list = output.splitlines()
                                    # i = 0
                                    # for i in range(len(output_list)):
                                    #     if (save_stdout):
                                    #         fh.write('%s\n' % (output_list[i]))
                                    #     if output_list[i].strip() == "Response time (avg):":
                                    #         for j in range(i+1, len(output_list)):
                                    #             line = output_list[j]
                                    #             if not line.strip():
                                    #                 break
                                    #             (key, value) = line.split(':')
                                    #             sim_output[arr_scale][policy][stdev_factor]['avg_resp_time'][key.strip()] = value.strip()
                                    #             #sys.stdout.write('Set sim_output[%s][%s][%s][%s][%s] = %s\n' % (arr_scale, policy, stdev_factor, 'avg_resp_time', key.strip(), value.strip()))

                                    #     elif output_list[i].strip() == "Met Deadline:":
                                    #         for j in range(i+1, len(output_list)):
                                    #             line = output_list[j]
                                    #             if not line.strip():
                                    #                 break
                                    #             (key, value) = line.split(':')
                                    #             sim_output[arr_scale][policy][stdev_factor]['met_deadline'][key.strip()] = value.strip()
                                    #             #sys.stdout.write('Set sim_output[%s][%s][%s][%s][%s] = %s\n' % (arr_scale, policy, stdev_factor, 'avg_resp_time', key.strip(), value.strip()))


                                    #     elif output_list[i].strip() == "Histograms:":
                                    #         line = output_list[i+1]
                                    #         histogram = line.split(':')[1]
                                    #         sim_output[arr_scale][policy][stdev_factor]['queue_size_hist'] = histogram.strip()

                                    #     elif "Total simulation time:" in output_list[i].strip():
                                    #         elems = output_list[i].split(":")
                                    #         #stdout.write('HERE: %s : %s : %s\n' % (str(policy), str(stdev_factor), elems[1]))
                                    #         #stdout.write('%s\n' % (output_list[i].strip()))
                                    #         #sys.stdout.flush()
                                    #         sim_output[arr_scale][policy][stdev_factor]['total_sim_time'] = elems[1]

                                    # if (save_stdout):
                                    #     fh.close()
                                    # num_executions += 1
                                    # time.sleep(1)



        # ###############################################################################################
        # # Dump outputs to files
        # # Met deadline
        # if (do_csv_output):
        #     fh = open(sim_dir + '/met_deadline.csv', 'w')
        # else:
        #     fh = open(sim_dir + '/met_deadline.out', 'w')

        # fh.write('  Arr_scale%s Policy%s Stdev_Factor%s\n' % (out_sep, out_sep, out_sep))
        # for arr_scale in ARRIVE_SCALE:
        #     # fh.write('Arrival_Scale %lf\n' % arr_scale)


        #     for policy in sorted(sim_output[arr_scale].iterkeys()):
        #         # fh.write('%s\n' % policy)
        #         first_time = True
        #         for stdev_factor in sorted(sim_output[arr_scale][policy].iterkeys()):
        #             # if first_time:
        #             #     # Print header
        #             #     for key in sorted(sim_output[arr_scale][policy][stdev_factor]['met_deadline'].iterkeys()):
        #             #         fh.write('%s%s%s%s%s' % (key, out_sep, out_sep, out_sep, out_sep))
        #             #     fh.write('\n')
        #             #     first_time = False
        #             # Print values
        #             fh.write('  %s%s%s%s%s%s' % (str(arr_scale), out_sep, policy, out_sep, str(stdev_factor), out_sep))
        #             for key in sorted(sim_output[arr_scale][policy][stdev_factor]['met_deadline'].iterkeys()):
        #                 tl = sim_output[arr_scale][policy][stdev_factor]['met_deadline'][key].split()
        #                 for tt in tl:
        #                     fh.write('%s%s' % (tt, out_sep))
        #             fh.write('\n')
        #         # fh.write('\n\n')
        # fh.close()

        # # Average respose time
        # if (do_csv_output):
        #     fh = open(sim_dir + '/avg_resp_time.csv', 'w')
        # else:
        #     fh = open(sim_dir + '/avg_resp_time.out', 'w')
        # for arr_scale in ARRIVE_SCALE:
        #     fh.write('Arrival_Scale %lf\n' % arr_scale)
        #     for policy in sorted(sim_output[arr_scale].iterkeys()):
        #         fh.write('%s\n' % policy)
        #         first_time = True
        #         for stdev_factor in sorted(sim_output[arr_scale][policy].iterkeys()):
        #             if first_time:
        #                 # Print header
        #                 fh.write('  Arr_scale%s Policy%s Stdev_Factor%s' % (out_sep, out_sep, out_sep))
        #                 for key in sorted(sim_output[arr_scale][policy][stdev_factor]['avg_resp_time'].iterkeys()):
        #                     fh.write('%s%s%s%s%s' % (key, out_sep, out_sep, out_sep, out_sep))
        #                 fh.write('\n')
        #                 first_time = False
        #             # Print values
        #             fh.write('  %s%s%s%s%s%s' % (str(arr_scale), out_sep, policy, out_sep, str(stdev_factor), out_sep))
        #             for key in sorted(sim_output[arr_scale][policy][stdev_factor]['avg_resp_time'].iterkeys()):
        #                 tl = sim_output[arr_scale][policy][stdev_factor]['avg_resp_time'][key].split()
        #                 for tt in tl:
        #                     fh.write('%s%s' % (tt, out_sep))
        #             fh.write('\n')
        #         fh.write('\n\n')
        # fh.close()

        # # Queue size histogram
        # if (do_csv_output):
        #     fh = open(sim_dir + '/queue_size_hist.csv', 'w')
        # else:
        #     fh = open(sim_dir + '/queue_size_hist.out', 'w')
        # for arr_scale in ARRIVE_SCALE:
        #     fh.write('Arrival_Scale %lf\n' % arr_scale)
        #     for policy in sorted(sim_output[arr_scale].iterkeys()):
        #         fh.write('%s\n' % policy)
        #         fh.write('  Arr_Scale%sStdev_Factor%sQueue_Histogram\n' % (out_sep, out_sep))
        #         for stdev_factor in sorted(sim_output[arr_scale][policy].iterkeys()):
        #             fh.write('  %s%s%s%s' % (str(arr_scale), out_sep, str(stdev_factor), out_sep))
        #             tl = sim_output[arr_scale][policy][stdev_factor]['queue_size_hist'].replace(',',' ').split()
        #             for tt in tl:
        #                 fh.write('%s%s' % (tt, out_sep))
        #             fh.write('\n')
        #     fh.write('\n\n')
        # fh.close()

        # # Total Simulation Time
        # if (do_csv_output):
        #     fh = open(sim_dir + '/total_sim_time.csv', 'w')
        # else:
        #     fh = open(sim_dir + '/total_sim_time.out', 'w')
        # for arr_scale in ARRIVE_SCALE:
        #     fh.write('Arrival_Scale %lf\n' % arr_scale)
        #     for policy in sorted(sim_output[arr_scale].iterkeys()):
        #         fh.write('%s\n' % policy)
        #         fh.write('  Arr_Scale%sStdev_Factor%sTotal_Sim_Time\n' % (out_sep, out_sep))
        #         for stdev_factor in sorted(sim_output[arr_scale][policy].iterkeys()):
        #             fh.write('  %s%s%s%s' % (str(arr_scale), out_sep, str(stdev_factor), out_sep))
        #             tl = sim_output[arr_scale][policy][stdev_factor]['total_sim_time'].replace(',',' ').split()
        #             for tt in tl:
        #                 fh.write('%s%s' % (tt, out_sep))
        #             fh.write('\n')
        #     fh.write('\n\n')
        # fh.close()


        # elapsed_time = time.time() - start_time
        # stdout.write('%d configurations executed in %.2f secs.\nResults written to %s\n' % (num_executions, elapsed_time, sim_dir))


if __name__ == "__main__":
   main(sys.argv[1:])
