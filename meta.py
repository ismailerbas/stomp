from __future__ import division
from __future__ import print_function
from abc import ABCMeta, abstractmethod
import numpy
import pprint
import sys
import operator
import logging
import datetime

import time
import networkx as nx
from csv import reader

def read_matrix(matrix):
    lmatrix = []
    f = open(matrix)
    next(f)
    csv_reader = reader(f)
    for row in csv_reader:
        # logging.info(row)
        lmatrix.append(list(map(str,row)))
    f.close()
    return lmatrix 

class MetaTask(object):

    def __init__(self, tid, comp_cost=[]):
        self.tid = int(tid)# task id - this is unique
        self.rank = -1 # This is updated during the 'Task Prioritisation' phase 
        self.processor = -1
        self.ast = 0 
        self.aft = 0 
        self.scheduled = 0

    def __repr__(self):
        return str(self.tid)
    """
    To utilise the NetworkX graph library, we need to make the node structure hashable  
    Implementation adapted from: http://stackoverflow.com/a/12076539        
    """

    def __hash__(self):
        return hash(self.tid)

    def __eq__(self, task):
        if isinstance(task, self.__class__):
            return self.tid == task.tid
        return NotImplemented

    
    def __lt__(self,task): 
        if isinstance(task,self.__class__):
            return self.tid < task.tid

    def __le__(self,task):
        if isinstance(task,self.__class__):
            return self.tid <= task.tid

class DAG:
    def __init__(self, graph, comp, parent_dict, atime, deadline, priority, dag_type):


        self.graph              = graph
        self.comp               = comp
        self.parent_dict        = parent_dict
        self.arrival_time       = atime
        self.deadline           = deadline
        self.resp_time          = 0
        self.slack              = deadline
        self.priority           = priority
        self.ready_time         = atime
        self.dag_type           = dag_type
        self.dropped            = 0
        self.completed_peid     = {}
        self.noaffinity_time    = 0
        # logging.info("Created %d,%d" % (self.arrival_time,self.deadline))


class META:

    E_PWR_MGMT          = 1
    E_TASK_ARRIVAL      = 2
    E_SERVER_FINISHES   = 3
    E_NOTHING           = 4

    E_META_DONE         = 0

    def __init__(self, meta_params, stomp_sim):

        self.params         = meta_params
        self.stomp          = stomp_sim

        self.working_dir    = self.params['general']['working_dir']
        self.basename       = self.params['general']['basename']

        self.dag_trace_files                = {}
        self.output_trace_file              = self.params['general']['output_trace_file']
        self.input_trace_file               = self.params['general']['input_trace_file'][1]
        self.stdev_factor                   = self.params['simulation']['stdev_factor']

        self.global_task_trace              = []

        self.dag_dict                       = {}
        self.dag_id_list                    = []
        self.server_types                   = ["cpu_core", "gpu", "fft_accel"]
    def run(self):

        ### Read input DAGs ####
        dags_completed = 0
        dags_dropped = 0
        end_list = []
        dropped_list = []

        in_trace_name = self.working_dir + '/' + self.input_trace_file
        logging.info(in_trace_name)
        # print("inputs/random_comp_5_{1}.txt".format(5, self.stdev_factor))
        with open(in_trace_name, 'r') as input_trace:
                line_count = 0;
                for line in input_trace.readlines():
                    tmp = line.strip().split(',')
                    if (line_count >= 0):
                        atime = int(int(tmp.pop(0))*self.params['simulation']['arrival_time_scale'])
                        dag_id = int(tmp.pop(0))
                        dag_type = tmp.pop(0)
                        graph = nx.read_graphml("inputs/random_dag_{0}.graphml".format(dag_type), MetaTask)
                        #### AFFINITY ####
                        # Add matrix to maintain parent node id's
                        ####
                        parent_dict = {}
                        for node in graph.nodes():
                            parent_list = []
                            for pred_node in graph.predecessors(node):
                                parent_list.append(pred_node.tid)
                            parent_dict[node.tid] = parent_list
                            # logging.info(str(node.tid) + ": " + str(parent_dict[node.tid]))

                        comp = read_matrix("inputs/random_comp_{0}_{1}.txt".format(dag_type, self.stdev_factor))
                        priority = int(tmp.pop(0))
                        deadline = int(tmp.pop(0))
                        the_dag_trace = DAG(graph, comp, parent_dict, atime, deadline, priority,dag_type)
                        self.dag_dict[dag_id] = the_dag_trace
                        self.dag_id_list.append(dag_id)
                    line_count += 1

        logging.info("Dropped,DAG ID,DAG Priority,DAG Type,Slack,Response Time,No-Affinity Time")
                    
        while(self.dag_id_list or self.stomp.E_TSCHED_DONE == 0):
            ## TODO: Need an order to push into ready queue (Task ordering like HEFT)
            temp_task_trace = []
            completed_list = []
            dropped_dag_id_list = []

            self.stomp.tlock.acquire()
            while(len(self.stomp.tasks_completed)):
                completed_list.append(self.stomp.tasks_completed.pop(0))
            self.stomp.tlock.release()


            while (len(completed_list)):
                task_completed = completed_list.pop(0)
                dag_id_completed = task_completed.dag_id

                ## If the task belongs to a non-dropped DAG
                if dag_id_completed in self.dag_dict:
                    dag_completed = self.dag_dict[dag_id_completed]
                    # logging.info('Task completed : %d,%d,%d' % ((task_completed.arrival_time + task_completed.task_lifetime),dag_id_completed,task_completed.tid))
                    
                    for node in dag_completed.graph.nodes():
                        if node.tid == task_completed.tid:
                            dag_completed.ready_time = task_completed.arrival_time + task_completed.task_lifetime
                            # if (dag_completed.ready_time < dag_completed.arrival_time):
                            #   logging.info("BAD:" + str(dag_completed.ready_time) + ',' + str(dag_completed.arrival_time) + ',' + str(task_completed.arrival_time) + ',' + str(task_completed.task_lifetime) + str('....................................................................'))
                            dag_completed.resp_time = dag_completed.ready_time - dag_completed.arrival_time
                            dag_completed.slack = dag_completed.deadline - dag_completed.resp_time
                            #### AFFINITY ####
                            # Add completed id and HW id to a table
                            ####
                            dag_completed.completed_peid[task_completed.tid] = task_completed.peid
                            dag_completed.noaffinity_time += task_completed.noaffinity_time
                            
                            # print("Completed: %d,%d,%d,%d,%d,%d" % (dag_id_completed,task_completed.tid,dag_completed.slack,dag_completed.deadline,task_completed.arrival_time,task_completed.task_lifetime))
                            dag_completed.graph.remove_node(node)
                            break;


                    ## Dag execution completed ##
                    if (len(dag_completed.graph.nodes()) == 0):
                        dags_completed += 1
                        ## Calculate stats for the DAG                      
                        # logging.info(str(self.params['simulation']['sched_policy_module'].split('.')[-1].split('_')[-1]) + ',' + str(dag_id_completed) + ',' + str(dag_completed.priority) + ',' +str(dag_completed.slack))
                        # logging.info(str(dag_id_completed) + ',' + str(dag_completed.priority) + ',' +str(dag_completed.slack))
                        end_entry = (dag_id_completed,dag_completed.priority,dag_completed.dag_type,dag_completed.slack, dag_completed.resp_time, dag_completed.noaffinity_time)
                        end_list.append(end_entry)
                        # Remove DAG from active list
                        self.dag_id_list.remove(dag_id_completed)
                        del self.dag_dict[dag_id_completed]
                    


            for dag_id in self.dag_id_list:
                the_dag_sched = self.dag_dict[dag_id]

                ## Push ready tasks into queue
                for node,deg in the_dag_sched.graph.in_degree():
                    if deg == 0 and node.scheduled == 0:
                        task_entry = []
                        if (node.tid == 0):
                            atime = the_dag_sched.arrival_time
                        else:
                            atime = the_dag_sched.ready_time
                        task = the_dag_sched.comp[node.tid][0]
                        priority = the_dag_sched.priority
                        deadline = int(the_dag_sched.slack)
                        if (self.params['simulation']['sched_policy_module'].startswith("policies.ms1")):
                            deadline = int(the_dag_sched.deadline*float(the_dag_sched.comp[node.tid][1]))
                        if (self.params['simulation']['sched_policy_module'].startswith("policies.ms3")):
                            deadline = int(deadline*float(the_dag_sched.comp[node.tid][1]))

                        task_entry.append((atime,task,dag_id,node.tid,priority,deadline))
                        # logging.info( "Task arr: %d,%d,%d,%d" % (atime,dag_id,node.tid,deadline)) #Aporva
                        ## Ready task found, push into task queue
                        
                        stimes = []
                        count = 0
                        min_time = 100000
                        # Iterate over each column of comp entry.
                        for comp_time in the_dag_sched.comp[node.tid]:
                            # Ignore first two columns.
                            if (count <= 1):
                                count += 1
                                continue
                            else:
                                if (comp_time != "None" and (min_time > round(float(comp_time)))):
                                    min_time = round(float(comp_time))
                                stimes.append((self.server_types[count-2],comp_time))
                                # print(str(self.server_types[count-2])+ "," + str(comp_time))
                            count += 1
                        
                        task_entry.append(stimes)
                        ##### DROPPED ##########
                        if(self.params['simulation']['drop'] == True):
                            if(the_dag_sched.slack - min_time < 0 and the_dag_sched.priority == 1):
                                the_dag_sched.dropped = 1
                                dags_dropped += 1
                                dropped_entry = (dag_id,the_dag_sched.priority,the_dag_sched.dag_type,the_dag_sched.slack, the_dag_sched.resp_time, the_dag_sched.noaffinity_time)
                                dropped_list.append(dropped_entry)
                                dropped_dag_id_list.append(dag_id)
                                break
                        ##### DROPPED ##########

                        #### AFFINITY ####
                        # Pass parent id and HW id of parents with task
                        ####
                        parent_data = []
                        for parent in the_dag_sched.parent_dict[node.tid]:
                            parent_data.append((parent,the_dag_sched.completed_peid[parent]))
                        task_entry.append(parent_data)


                        temp_task_trace.append(task_entry)
                        # self.stomp.global_task_trace.append(task_entry)
                        # self.global_task_trace.sort(key=lambda tr_entry: tr_entry[0][0], reverse=False)
                        node.scheduled = 1
            
            ##### DROPPED ##########
            for dag_id_dropped in dropped_dag_id_list:
                # Remove DAG from active list
                self.dag_id_list.remove(dag_id_dropped)
                del self.dag_dict[dag_id_dropped]
            #########################

            self.stomp.lock.acquire()
            # When pushed into stomp, push in the order of arrival time
            while (len(temp_task_trace)):
                # logging.info('Inserting : %d,DAG:%d,TID:%d' % (temp_task_trace[0][0][0],temp_task_trace[0][0][2],temp_task_trace[0][0][3]))
                self.stomp.global_task_trace.append(temp_task_trace.pop(0))
                self.stomp.global_task_trace.sort(key=lambda tr_entry: tr_entry[0][0], reverse=False)

            # logging.info("Ready Task")

            if (len(self.stomp.global_task_trace) and (self.stomp.next_cust_arrival_time != self.stomp.global_task_trace[0][0][0])):
                self.stomp.next_cust_arrival_time = self.stomp.global_task_trace[0][0][0]
                # print("SA: " + str(self.stomp.next_cust_arrival_time))
            
            self.stomp.tlock.acquire()
            if(self.stomp.task_completed_flag == 1 and (len(self.stomp.tasks_completed) == 0)):
                self.stomp.task_completed_flag = 0
            self.stomp.tlock.release()


            self.stomp.lock.release()   



            
            self.stomp.E_META_START = 1
            # print("Start STOMP")
            self.stomp.stats['Tasks Generated by META'] = 1
            ## Handle a task being completed: Remove from dag, update ready_time, deadline

            if(len(self.dag_id_list) == 0):
                self.stomp.E_META_DONE = 1



            # logging.info("Completed Task")    
                

        # logging.info("META completed")

        end_list.sort(key=lambda end_entry: end_entry[0], reverse=False)
        while(len(end_list)):
            end_entry = end_list.pop(0)
            print("0," + str(end_entry[0]) + ',' + str(end_entry[1]) + ',' + str(end_entry[2]) + ',' + str(end_entry[3]) + ',' + str(end_entry[4]) + ',' + str(end_entry[5]))
            # end_entry = (dag_id_completed,dag_completed.priority,dag_completed.dag_type,dag_completed.slack, dag_completed.resp_time, dag_completed.noaffinity_time)
                        
        dropped_list.sort(key=lambda dropped_entry: dropped_entry[0], reverse=False)
        while(len(dropped_list)):
            dropped_entry = dropped_list.pop(0)
            print("1," + str(dropped_entry[0]) + ',' + str(dropped_entry[1]) + ',' + str(dropped_entry[2]) + ',' + str(dropped_entry[3]) + ',' + str(dropped_entry[4]) + ',' + str(dropped_entry[5]))


