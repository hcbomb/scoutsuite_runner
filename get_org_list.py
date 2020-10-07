import argparse
import boto3
import re
import csv
import json
import sys
import datetime
import time
import traceback

csv_headers = ['aws_profile_name', 'aws_account_id', 'ou', 'ou_name', 'status']

client_type = 'organizations'
default_region = 'us-east-1'

next_token = None
max_results = 20
backoff = 1 # backoff by fibonnacci

client = None
master_account = {}
master_ou = {}

time_start = datetime.datetime.now()


def get_timestamp():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f%z')


def run_setup():
    global client

    parser = argparse.ArgumentParser()

    parser.add_argument('-p',
                        '--profile',
                        dest='profile',
                        default=None,
                        help='Run with a named profile')
    parser.add_argument('--access-key-id',
                         action='store',
                         default=None,
                         dest='aws_access_key_id',
                         help='AWS Access Key ID')
    parser.add_argument('--secret-access-key',
                         action='store',
                         default=None,
                         dest='aws_secret_access_key',
                         help='AWS Secret Access Key')

    args = parser.parse_args()

    if args.profile:
            session = boto3.Session(profile_name=args.profile)
            client = session.client(client_type)
    else:
            client = boto3.client(client_type, aws_access_key_id=args.aws_access_key_id, aws_secret_access_key=args.aws_secret_access_key)
    

def copy_list(account, ou=None):
    '''
    '''
    account_id = account['Id']
    if account_id in master_account:
        print(f'{get_timestamp()} account {account_id} already in master list')
    else:
        master_account[account_id] = {}

    for key in account.keys():
        if key == 'JoinedTimestamp':
            master_account[account_id]['time_joined'] = account['JoinedTimestamp'].strftime('%F %T%z')
            master_account[account_id]['time_joined_epoch'] = datetime.datetime.utcfromtimestamp(account['JoinedTimestamp'].timestamp()).timestamp()
        else:
            master_account[account_id][key] = account[key]

    master_account[account_id]['org_id'] = account['Arn'].split('/')[1]


def append_ou_policies(ou_id, policy_type, next_token=None, last_check=None):
    '''
    iterate through specified service control or tag policy and copy to ou info
    :type ou_id: str
    :param ou_id: ou reference
    :type policy_type: str
    :param policy_type: service control or tag policy
    :type next_token: str
    :param next_token: paginator token
    :type last_check: datetime
    :param last_check: timestamp of the last iteration of this API
    '''

    try:
        if next_token is None:
            time_check = datetime.datetime.now()
            response = client.list_policies_for_target(TargetId=ou_id,Filter=policy_type, MaxResults=max_results)
        else:
            time_check = datetime.datetime.now()

            # if there's a token specified, last_check timestamp must be provided
            assert(type(last_check) == datetime.datetime)
            run_diff = (time_check - last_check).total_seconds()

            if run_diff < 1:
                delta = round(1 - run_diff, 6)
                print(f'{get_timestamp()} sleeping for: {delta} seconds')
                time.sleep(delta)

            response = client.list_policies_for_target(NextToken=next_token, MaxResults=max_results)

            last_check = time_check
    except Exception as e:
        if type(e).__name__ == "TooManyRequestsException":
            print(f'{get_timestamp()} force sleeping for: {backoff} second')
            time.sleep(backoff)
            backoff += backoff
            # retry
            append_ou_policies(ou_id, policy_type, next_token, time_check)
        else:
            print(f'{get_timestamp()} print traceback: \n{traceback.format_exc()}')
            sys.exit(1)

    resp_code = response['ResponseMetadata'].get('HTTPStatusCode')

    if resp_code != 200:
        print(f'{get_timestamp()} response error: {resp_code}')
        time.sleep(1)

    next_token = response.get('NextToken')
    ou = master_ou[ou_id]

    if not ou.get('policy_detail'):
        ou['policy_detail'] = {}

    ou_policy_head = ou['policy_detail']

    # append if policies captured do not exit
    if not ou_policy_head.get(policy_type):
        ou_policy_detail = ou['policy_detail'][policy_type] = {}

    for policy in response['Policies']:
        ou_policy_detail[policy['Id']] = policy

    # if there are more policies to collect, make recursive call along with the tracking references
    if next_token:
        append_ou_policies(ou_id, policy_type, next_token, time_check)


def copy_ou(ou, parent_id=None):
    '''
    inventory ou into ou lists, include parent ou reference if provided
    :type parent_id: str
    :param parent_id: ou id
    '''
    ou_id = ou['Id']
    if ou_id in master_ou:
        print(f'{get_timestamp()} ou {ou_id} already in master list')
    else:
        master_ou[ou_id] = {}

    # capture org object type
    if 'o-' in ou_id:
        master_ou[ou_id]['Type'] = 'ORGANIZATION'
    elif 'r-' in ou_id:
        master_ou[ou_id]['Type'] = 'ROOT'
    else:
        master_ou[ou_id]['Type'] = 'ORGANIZATIONAL_UNIT'

# ou['Organization'].keys()
# dict_keys(['Id', 'Arn', 'FeatureSet', 'MasterAccountArn', 'MasterAccountId', 'MasterAccountEmail', 'AvailablePolicyTypes'])
    for key in ou.keys():
        master_ou[ou_id][key] = ou[key]

    # if parent_id specified, update parent and current references
    if parent_id:
        master_ou[ou_id]['parent_id'] = parent_id

        # update parent with child id reference
        if not master_ou[parent_id].get('child_id'):
            master_ou[parent_id]['child_id'] = [ou_id]
        else:
            master_ou[parent_id]['child_id'].append(ou_id)

    # append policy information for ou
    for policy_type in ['SERVICE_CONTROL_POLICY','TAG_POLICY']:
            append_ou_policies(ou_id, policy_type)


def append_ou_info(account_id, ou_reference=None):
    '''
    add ou information to account
    if not associated to an ou, then add detail
    :type account_id: str
    :param account_id: aws account record from recent API call, not mastser
    :type ou_reference: str
    :param ou_reference: ou id to update account record with ou info
    '''
    account = master_account.get(account_id)
    ou = account.get('ou')

    if not account.get('ou_detail'):
        account['ou_detail'] = {}

    ou_detail = account['ou_detail']

    # append ou information to account
    if ou_reference:
        if ou and ou != ou_reference:
            print(f'{get_timestamp()} account ou validation check: orig ou={ou} new ou={ou_reference}')
        account['ou'] = ou_reference

        ou_info = master_ou[ou_reference]

        ou_detail['ou_arn'] = ou_info.get('Arn')
        ou_detail['ou_name'] = ou_info.get('Name')

    else:
        ou_detail['message'] = 'not associated to an ou'


def process_accounts(parent_id, next_token=None, idx=0, count=0, last_check=0):
    '''
    based on parent id, gather all ous and associated accounts for tracking
    :type parent_id: str
    :param parent_id: ou id
    :type next_token: str
    :param next_token: token for pagination
    :type idx: int
    :param idx: iterator index for tracking
    :type count: int
    :param count: count of total accounts
    '''

    # iterate through all orgs from parent
    try:
        if next_token == None:
            time_check = datetime.datetime.now()
            response = client.list_accounts_for_parent(ParentId=parent_id, MaxResults=max_results)

        else:
            time_check = datetime.datetime.now()
            run_diff = (time_check - last_check).total_seconds()

            if run_diff < 1:
                delta = round(1 - run_diff, 6)
                print(f'{get_timestamp()} sleeping for: {delta} seconds')
                time.sleep(delta)

            response = client.list_accounts_for_parent(ParentId=parent_id, NextToken=next_token, MaxResults=max_results)

            last_check = time_check
    except Exception as e:
        print(f'{get_timestamp()} printing traceback: \n{traceback.format_exc()}')
        if type(e).__name__ == "TooManyRequestsException":
            print(f'{get_timestamp()} force sleeping for: {backoff} second')
            time.sleep(backoff)
            backoff += backoff
            return
        else:
            sys.exit(1)

    '''response.keys()
    dict_keys(['Children', 'NextToken', 'ResponseMetadata'])
    '''

    resp_code = response['ResponseMetadata'].get('HTTPStatusCode')

    if resp_code != 200:
        print(f'{get_timestamp()} response error: {resp_code}')
        time.sleep(1)

    next_token = response.get('NextToken')
    idx += 1
    ou_id = parent_id if 'r-' not in parent_id else None

    for account in response['Accounts']:
        # add accounts
        if account['Id'] not in master_account:
            print(f'account is missing from original list: aws_account_id={account["Id"]} aws_account_name={account["Name"]}')

        # append some final relevant org info for account
        append_ou_info(account['Id'], ou_id)

    count += len(response['Accounts'])
    print(f'processed aws accounts for ou={parent_id}: count={len(response["Accounts"])} total={count}')

    # if there are more policies to collect, make recursive call along with the tracking references
    if next_token:
        process_accounts(parent_id, next_token, idx, count, time_check)
'''             
        append_ou_policies(ou_id, policy_type, next_token, last_check)

        resp_accounts = client.list_accounts_for_parent(ParentId=ou_id)
        for account in resp_accounts['Accounts']:
            # add accounts
            if account['Id'] not in master_account:
                print(f'accout is missing from original list: aws_account_id={account["Id"]} aws_account_name={account["Name"]}')

            # append some final relevant org info for account
            append_ou_info(account['Id'], ou_id)

'''

def process_org_units(parent_id, next_token=None, idx=0):
    '''
    based on parent id, gather all ous and associated accounts for tracking
    :type parent_id: str
    :param parent_id: ou id
    :type next_token: str
    :param next_token: token for pagination
    :type idx: int
    :param idx: iterator index for tracking
    :type count: int
    :param count: count of total accounts
    '''

    # iterate through all orgs from parent
    try:
        if next_token == None:
            last_check = datetime.datetime.now()
            response = client.list_organizational_units_for_parent(ParentId=parent_id,  MaxResults=max_results)

        else:
            time_check = datetime.datetime.now()
            run_diff = (time_check - last_check).total_seconds()

            if run_diff < 1:
                delta = round(1 - run_diff, 6)
                print(f'sleeping for: {delta} seconds')
                time.sleep(delta)

            response = client.list_organizational_units_for_parent(ParentId=parent_id, NextToken=next_token, MaxResults=max_results)

            last_check = time_check
    except Exception as e:
        print(f'printing traceback: \n{traceback.format_exc()}')
        if type(e).__name__ == "TooManyRequestsException":
            print(f'force sleeping for: {backoff} second')
            time.sleep(backoff)
            backoff += backoff
            return
        else:
            sys.exit(1)

    '''response.keys()
    dict_keys(['Children', 'NextToken', 'ResponseMetadata'])
    '''

    resp_code = response['ResponseMetadata'].get('HTTPStatusCode')

    if resp_code != 200:
        print(f'{get_timestamp()} response error: {resp_code}')
        time.sleep(1)

    next_token = response.get('NextToken')
    idx += 1

    # process each ou for its associated accounts and then traverse for child ous
    for ou in response['OrganizationalUnits']:
        ou_id = ou['Id']
        print(f'tracking OU details: ou_id={ou_id} parent_id={parent_id}')

        copy_ou(ou, parent_id)

        # hard enforce rate limiting
        time.sleep(.1)

        print(f'processing aws accounts for ou={ou_id}: ou_depth={idx}')

        # gather accounts associated to ou 
        process_accounts(ou_id)

        process_org_units(ou_id, next_token, idx)


def finalize_lists(filename_account_list='aws_account_list.csv', filename_accounts='aws_account_detail.txt', filename_orgs='aws_orgs_detail.txt'):

    fpa = open(filename_account_list, 'w')
    fp_accounts = open(filename_accounts, 'w')
    fp_orgs = open(filename_orgs, 'w')

    account_writer = csv.writer(fpa, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    # write csv header
    account_writer.writerow(csv_headers)

    for aws_account_id in master_account:
        account = master_account[aws_account_id]

        temp_ou_name = account.get('ou_detail').get('ou_name') if account.get('ou_detail') else None

        # write to account csv
        account_writer.writerow([
                    re.sub(r'[ _,\/]', '_', account['Name']).replace('__','_'),
                    #re.sub(r'[ _,()]', '_', account['Name']).replace('__','_'),
                    #account['Name'].replace(' ', '_').replace(',','_'),
                    aws_account_id, 
                    account.get('ou'),
                    temp_ou_name,
                    account['Status']])

        # write account detail
        fp_accounts.write(json.dumps(account))
        fp_accounts.write('\n')

    for org_id in master_ou:
        fp_orgs.write(json.dumps(master_ou[org_id]))
        fp_orgs.write('\n')

    # close fps
    fpa.close()
    fp_accounts.close()
    fp_orgs.close()


if __name__ == "__main__":
    run_setup()

    # collect all accounts under root
    print(f'begin collecting aws accounts from root.')

    list_iter = 0

    while(True):

        print(f'processing list pull: idx={list_iter}')
        try:
            if next_token is None:
                last_check = datetime.datetime.now()
                response = client.list_accounts()
            else:
                time_check = datetime.datetime.now()

                run_diff = (time_check - last_check).total_seconds()

                if run_diff < 1:
                    delta = round(1 - run_diff, 6)
                    print(f'sleeping for: {delta} seconds')
                    time.sleep(delta)

                response = client.list_accounts(NextToken=next_token, MaxResults=max_results)

                last_check = time_check
        except Exception as e:
            print(f'printing traceback: \n{traceback.format_exc()}')
            if type(e).__name__ == "TooManyRequestsException":
                print(f'force sleeping for: {backoff} second')
                time.sleep(backoff)
                backoff += backoff
                continue
            else:
                sys.exit(1)

        '''response.keys()
        dict_keys(['Accounts', 'NextToken', 'ResponseMetadata'])
        '''

        resp_code = response['ResponseMetadata'].get('HTTPStatusCode')

        if resp_code != 200:
            print(f'{get_timestamp()} response error: {resp_code}')

        next_token = response.get('NextToken')

        for account in response['Accounts']:
            copy_list(account)

        # if no more entries, exit
        if not next_token:
            break
        list_iter += 1

    print(f'{get_timestamp()} completed collecting aws accounts from root. count={len(master_account)}')
    print(f'{get_timestamp()} begin collecting org units from root.')

    resp_roots = client.list_roots()
    for root in resp_roots['Roots']:
        parent_id = root['Id']
        copy_ou(root)

        # gather accounts not associated to an ou 
        process_accounts(parent_id)     
        process_org_units(parent_id)

    print(f'{get_timestamp()} completed collecting org units from root. count={len(master_ou)}')

    '''
    from pprint import pprint as pp
    list_master = list(set(master_account))
    xi = 0
    x = master_account[list_master[xi]]
    ou_master = list(set(master_ou))
    yi = 0
    y = master_ou[ou_master[yi]]
    pp(x)
    pp(y)

    account_id = account['Id']
    pp(account)
    pp(master_account[account_id])
    len(response['Accounts'])

    b 372
    b 370
    b 419

    b 254
    b 219

    import traceback
    print(traceback.format_exc())
    type(e).__name__

    '''

    # dump all account and org information into CSV for processing, JSON for collection
    finalize_lists()

    time_end = datetime.datetime.now()
    print(f'{get_timestamp()} completed org collector script. duration: {time_end-time_start}')

