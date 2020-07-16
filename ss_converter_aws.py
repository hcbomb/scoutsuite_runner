import copy
import datetime
import json
import sys
import os
import argparse
import logging
import logging.handlers as handlers
import configparser
import traceback
import time
import pytz

BASEFOLDER = None
LOGFOLDER = None
LOGFILE = 'converter.scoutsuite.aws.log'
LOGFILE_PATH = None

SERVICE_EV_FIELDS = {
'acm': ['certificates'],
'awslambda': ['functions'],
'cloudformation': ['stacks'],
'cloudtrail': ['data_logging_trails','trails'],
'cloudwatch': ['alarms'],
'config': ['recorders','rules'],
'directconnect': ['connections'],
'ec2': ['images', 'instances', 'network_interfaces', 'security_groups', 'snapshots', 'volumes'],
'efs': ['filesystems'],
'elasticache': ['clusters', 'security_groups'],
'elb': ['elb_policies'],
'elbv2': ['elb_policies'],
'emr': ['clusters'],
'iam': ['credential_reports', 'groups', 'password_policy', 'policies', 'permissions', 'roles', 'users'],
'rds': ['instances', 'parameter_groups', 'security_groups', 'snapshots', 'subnet_groups'],
'redshift': ['parameter_groups', 'security_groups'],
'route53': ['domains', 'hosted_zones'],
's3': ['buckets'],
'ses': ['identities'],
'sns': ['topics'],
'sqs': ['queues'],
'vpc': ['flow_logs', 'peering_connections', 'vpcs']
}

logger = None
orig_timestamp=None

base_details = {}
account_details = {}
ev_template = {}
events = {}

def GetLogger(logFilename, loggerName, logLevel=logging.DEBUG, 
              backupCount=5, utc=True, intervalMinutes=24 * 60):
    '''
    build logger file for the script

    Args:
        logFilename: full path of the log file
        loggerName: 
        logLevel: configured log level. default DEBUG
        backupCount: number of backup log files to rotate
        utc: use UTC timezone. default true.
        intervalMinutes: interval to rotate log files

    Returns:
        logger: logger pointer

    '''
    global logger

    logger = logging.getLogger(loggerName)
    logger.setLevel(logLevel)
    handler = handlers.TimedRotatingFileHandler(logFilename, when='M',
                                                interval=intervalMinutes,
                                                backupCount=backupCount,
                                                encoding=None, utc=utc)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s",
                                  datefmt="%Y-%m-%d %H:%M:%S%z")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def prepare_logging():
    '''
    enable for script logging

    '''
    global BASEFOLDER, LOGFOLDER, LOGFILE_PATH, logger
    BASEFOLDER = os.path.abspath(os.path.dirname(__file__)) 

    LOGFOLDER = os.path.join(BASEFOLDER, 'log')
    if not os.path.exists(LOGFOLDER):
        os.makedirs(LOGFOLDER)
    LOGFILE_PATH = os.path.join(LOGFOLDER, LOGFILE)
    logger = GetLogger(LOGFILE_PATH, __file__)    


def _process_service_events(service_name, ev_template_service, results_service):
    ''' 
            need to process the results for the aws service into 4 different types:
            * summary - includes all static summary information for the aws account
            * filters - any pre-configured filters from the scan
            * findings - any identified vulnerable configurations
            * external_attack_surface - any identified vulnerable ext attack surface
            * inventory - based on service, capture per service artifact + summary

            :param service_name:    name of aws service
            :type service_name:             str
            :param ev_template_service:     template to copy event info from
            :type ev_template_service:      dict
            :param results_service: collection of service results to extract
            :type results_service:  dict
    '''

    global events

    # template for service events
    ev_temp = copy.deepcopy(ev_template_service)
    ev_temp['_time'] = datetime.datetime.now().strftime('%F %T%z')
    ev_temp['service'] = service_name

    ev_summary = copy.deepcopy(ev_temp)
    ev_summary['type'] = 'summary'
    ev_summary['id'] = f'{service_name}:summary'
    ev_filters = copy.deepcopy(ev_temp)
    ev_filters['type'] = 'filters'
    ev_findings = copy.deepcopy(ev_temp)
    ev_findings['type'] = 'findings'
    ev_ext = copy.deepcopy(ev_temp)
    ev_ext['type'] = 'external_attack_surface'
    ev_inventory = copy.deepcopy(ev_temp)
    ev_inventory['type'] = 'inventory'

    my_filters = {}
    my_findings = {}
    my_ext = {}
    my_inventory = {}

    # iterate through service data
    for key in results_service.keys():
        logger.debug(f'key list dump: service={service_name} keys: <{",".join(results_service.keys())}>')
        # everything not iterable will added to summary event
        if not isinstance(results_service[key], dict):
            ev_summary[key] = results_service[key]

        elif key == 'filters':
            for vv in results_service[key]:
                my_filters[vv] = {}
                my_filters[vv]['id'] = f'{key}:{vv}'
                my_filters[vv].update(ev_filters)
                my_filters[vv].update(results_service[key][vv])

        elif key == 'findings':
            for vv in results_service[key]:
                my_findings[vv] = {}
                my_findings[vv]['id'] = f'{key}:{vv}'
                my_findings[vv].update(ev_filters)
                my_findings[vv].update(results_service[key][vv])

        elif key == 'external_attack_surface':
            for vv in results_service[key]:
                my_ext[vv] = {}
                my_ext[vv]['id'] = f'{key}:{vv}'
                my_ext[vv].update(ev_ext)
                my_ext[vv].update(results_service[key][vv])     

        # need to iterate if among specified service events
        elif key in SERVICE_EV_FIELDS[service_name]:
            # special use cases for service subtypes are nested an extra level
            service_key_iterator = results_service[key]
            if key == 'permissions':
                service_key_iterator = results_service[key]['Action']

            for vv in service_key_iterator:
                my_inventory[vv] = {}
                my_inventory[vv]['id'] = f'{key}:{vv}'
                my_inventory[vv]['sub_type'] = key
                my_inventory[vv].update(ev_inventory)

                if isinstance(service_key_iterator[vv], dict):
                    my_inventory[vv].update(service_key_iterator[vv])
                else:
                    logger.debug(f'service key: {vv} type: {type(service_key_iterator[vv])}')

        # if regions, then need to breakdown even further
        # region based summary, then iterate through each region's items
        elif key == 'regions':
            # iterate through the regions
            for region in results_service[key]:
                # prepare region-based summary
                id_region = f'summary:{service_name}:{region}'
                my_inventory[id_region] = {}
                my_inventory[id_region]['sub_type'] = 'summary'
                my_inventory[id_region]['id'] = id_region
                my_inventory[id_region]['region'] = region
                my_inventory[id_region].update(ev_inventory)

                for rkey in results_service[key][region].keys():
                    if rkey in SERVICE_EV_FIELDS[service_name]:
                        service_key_iterator = results_service[key][region][rkey]

                        for vv in service_key_iterator:
                            my_id = f'{service_name}:{region}:{rkey}:{vv}'
                            my_inventory[my_id] = {}
                            my_inventory[my_id]['id'] = my_id
                            my_inventory[my_id]['region'] = region
                            my_inventory[my_id]['sub_type'] = rkey
                            my_inventory[my_id].update(ev_inventory)
                            my_inventory[my_id].update(service_key_iterator[vv])

                    # add summary key
                    else:
                        my_inventory[id_region][rkey] = results_service[key][region][rkey]

                    
        # any other special type of asset for the service
        else: # add inventory summary page for the region + per asset
            logger.debug(f'UNKNOWN key: {key} type: {type(results_service[key])}')
            '''
            my_inventory[vv] = {}
            my_inventory[vv]['sub_type'] = key
            my_inventory[vv].update(ev_temp)
            my_inventory[vv].update(results_service[key][vv])
            '''

    # all info back to global
    events[service_name] = {}
    events[service_name]['summary'] = ev_summary
    for ev in my_filters:
        ev_id = my_filters[ev].get('id')
        if ev in events[service_name] or ev_id in events[service_name]:
            logger.warning(f"event already exists: service={service_name} id={ev} orig type: {events[service_name][ev]['type']}")
        events[service_name][ev] = my_filters[ev]

    for ev in my_findings:
        ev_id = my_findings[ev].get('id')
        if ev in events[service_name] or ev_id in events[service_name]:
            logger.warning(f"event already exists: service={service_name} id={ev} orig type: {events[service_name][ev]['type']}")
        events[service_name][ev] = my_findings[ev]

        '''
        for region in account_details[key][service][s].keys():
            for id in account_details[key][service][s][region]['certificates']:
                ev_ss = {}
                ev_ss['_time'] = datetime.datetime.now().strftime('%F %T%z')
                ev_ss['type'] = service
                ev_ss['region'] = region
                ev_ss['sub_type'] = 'certificates'
                #ev_ss['id'] = id
                ev_ss.update(ev_template)
                ev_ss.update(account_details[key][service][s][region]['certificates'][id])
        '''
    pass
    for ev in my_ext:
        ev_id = my_ext[ev].get('id')
        if ev in events[service_name] or ev_id in events[service_name]:
            logger.warning(f"event already exists: service={service_name} id={ev} orig type: {events[service_name][ev]['type']}")
        events[service_name][ev] = my_ext[ev]

    for ev in my_inventory:
        ev_id = my_inventory[ev].get('id')
        if ev in events[service_name] or ev_id in events[service_name]:
            logger.warning(f"event already exists: service={service_name} id={ev} orig type: {events[service_name][ev]['type']}")
        events[service_name][ev] = my_inventory[ev]


if __name__ == "__main__":

    prepare_logging()

    parser = argparse.ArgumentParser(description=("Convert ScoutSuite AWS report.\n\n"
                                                  "  Configuration:\n"
                                                  "    - Logs collected in: %s\n"
                                                  "    - Work folder: %s\n\n") % (repr(LOGFOLDER),
                                                                              repr(BASEFOLDER)),
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-s', dest='results_file', required=True, help='ScoutSuite scan report input')
    parser.add_argument('-d', dest='json_out', required=True, help='Destination file to convert ScoutSuite scan report')

    args = parser.parse_args()    

    try:
        with open(args.results_file) as f:
            json_payload = f.readlines()
            json_payload.pop(0)
            json_payload = ''.join(json_payload)
            json_file = json.loads(json_payload)
    except Exception as e:
        logger.error(f'Failed to read ScoutSuite results: {args.results_file}. Reason: {traceback.format_exc()}')

    # set original timesetamp against results file
    tz = pytz.timezone("US/Pacific")
    #orig_timestamp = datetime.datetime.fromtimestamp(os.stat(args.results_file).st_mtime).localize(tz)

    for key in json_file.keys():
        if isinstance(json_file[key], dict) or isinstance(json_file[key], list):
            account_details[key] = json_file[key]
        elif isinstance(json_file[key], str):
            base_details[key] = json_file[key]
        else:
            logger.debug(f'unknown type: key: {key} type: {type(json_file[key])}')
            base_details[key] = json_file[key]

    # prune particular names for base event template
    for bkey in base_details:
        if bkey == 'account_id':
            ev_template['aws_account_id'] = base_details[bkey]
        elif bkey == 'result_format':
            pass
        else:
            ev_template[bkey] = base_details[bkey]

    # service list is general and has no detail from aws account
    del(account_details['service_list'])

    for key in account_details.keys():
        events[key] = {}
        #
        if key == 'last_run':
            try:
                events[key].update(account_details[key])
                events[key]['_time'] = datetime.datetime.now().strftime('%F %T%z')
                events[key]['type'] = key
                events[key]['id'] = f'{key}:summary'
                continue
            except Exception as e:
                logger.error(f'Failed to process account detail type={key} Reason: {traceback.format_exc()}')

        elif key == 'services':
            ''' each service is broken down into 4 subtype categories:
                * summary for the service
                * filters for anything specified
                * findings for any triggers
                * inventory configuration per service 
            '''
            try:
                for service_name in account_details['services'].keys():
                    _process_service_events(service_name, ev_template, account_details['services'][service_name])

                continue
            except Exception as e:
                logger.error(f'Failed to process account detail type={key} Reason: {traceback.format_exc()}')

        try:
            for ev_key in account_details[key].keys():
                events[key][ev_key] = {}
                events[key][ev_key]['_time'] = datetime.datetime.now().strftime('%F %T%z')
                events[key][ev_key]['type'] = key
                events[key][ev_key]['id'] = f'{key}:{ev_key}'
                # copy 
                events[key][ev_key].update(ev_template)
                events[key][ev_key].update(account_details[key][ev_key])
        except Exception as e:
            logger.error(f'Failed to process account detail type={key} target={ev_key} Reason: {traceback.format_exc()}')

    try:
        # write to new file
        with open(args.json_out, 'w') as wf:
            for ev_type in events.keys():
                try:
                    if ev_type == 'last_run':
                        json.dump(events[ev_type], wf)
                        wf.write('\n')    # force newline
                        continue

                    for ev in events[ev_type]:
                        json.dump(events[ev_type][ev], wf)
                        wf.write('\n')    # force newline
                except Exception as e:
                    logger.error(f'Failed to write results: {ev_type}. Reason: {traceback.format_exc()}')
    except Exception as e:
        logger.error(f'Failed to read ScoutSuite results: {args.json_out}. Reason: {traceback.format_exc()}')

