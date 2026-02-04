
import os
import re
import sys
import csv
import json
import time
import base64
import warnings
import logging
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
warnings.filterwarnings("ignore")

# Input CSV (pipeline copies filtered CSV here)
input_file = Path("Deployment_Automation/GVault_Deployment_Steps.csv")

output_dir = 'output_files'
sub_dir1 = "mdl_output_files"
sub_dir2 = "vpk_output_files"
sub_dir3 = "loader_output_files"
join_dir1 = os.path.join(output_dir, sub_dir1)
join_dir2 = os.path.join(output_dir, sub_dir2)
join_dir3 = os.path.join(output_dir, sub_dir3)

# --- Load authentication and payloads ---
with open("authentication.json") as json_file:
    json_data = json.load(json_file)
    ENVIRONMENT = os.getenv("ENVIRONMENT")  # 'POC1' or 'Contingency' (from pipeline)
    if ENVIRONMENT:
        json_data["env"] = ENVIRONMENT
    env = json_data['env']

baseurl = json_data[env+'.baseurl']
authurl = json_data[env+'.authurl']
username = json_data[env+'.username']
password = json_data[env+'.password']

with open("payload.json") as json_file:
    payload_json_data = json.load(json_file)
api_version = payload_json_data['api']['version']
api_job_task = payload_json_data['api']['job_task']
api_job_status = payload_json_data['api']['job_status']
update_body_parameters = payload_json_data['paylod_parameters']['update']
create_body_parameters = payload_json_data['paylod_parameters']['create']
mdl_output_dir = payload_json_data['output_dir']['mdl_output_dir']
vpk_output_dir = payload_json_data['output_dir']['vpk_output_dir']
loader_output_dir = payload_json_data['output_dir']['loader_output_dir']
ftp_folder = payload_json_data['ftp']['ftp_folder']

with open("deployment.json") as deployment_json_file:
    deployment_json_data = json.load(deployment_json_file)
vpk_deployment_type = deployment_json_data['deployment_type']['vpk']
mdl_deployment_type = deployment_json_data['deployment_type']['mdl']
loader_deployment_type = deployment_json_data['deployment_type']['loader']
validate_deployment_settings = deployment_json_data['deployment_settings']['validate']
import_deployment_settings = deployment_json_data['deployment_settings']['import']
deploy_deployment_settings = deployment_json_data['deployment_settings']['deploy']

# Paths
base_dir = os.path.dirname(__file__)
packages_dir = os.path.join(base_dir, "input_files", "packages")
mdl_dir = os.path.join(base_dir, "input_files", "mdl")
loader_dir = os.path.join(base_dir, "input_files", "loader")

if not os.path.exists('logs'):
    os.makedirs('logs')
os.makedirs(join_dir1, exist_ok=True)
os.makedirs(join_dir2, exist_ok=True)
os.makedirs(join_dir3, exist_ok=True)

logger = logging.getLogger(__name__)
log_format = "%(asctime)s - %(levelname)s - %(message)s"
handler = TimedRotatingFileHandler("logs/logfile.log", when="midnight", interval=1)
formatter = logging.Formatter(log_format)
handler.setFormatter(formatter)
handler.suffix = "%Y%m%d"
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
logger.info("******Started Deployment Automation Script******")

# ---------- Functions (unchanged behavior except env-aware column updates later) ----------
def import_package(baseurl, Headers, files, pkg_name):
    import_package_request = requests.put(baseurl+'/services/package', headers=Headers, files=files)
    import_response = import_package_request.json()
    response.append('***Import Package API Response***')
    response.append(json.dumps(import_response,indent=4))
    job_id = import_package_request.json()['job_id']
    import_job = get_job_status(baseurl, api_Headers, job_id)
    import_job_status = import_job['data']['status']
    if import_job_status == 'SUCCESS':
        print('Import Package Job Status:',str(import_job_status))
        href = import_job['data']['links'][1]['href']
        parts = href.split('/')
        pkg_id = parts[5] if len(parts)>5 else None
        print('Package ID:',pkg_id)
        vpk_path = os.path.join(packages_dir, vpk_filename)
        if validate_deployment_settings is True:
            if os.path.exists(vpk_path):
                with open(vpk_path, "rb") as vpk_file:
                    validate_files = {'file': vpk_file}
                    validate_response = validate_package(baseurl,vpk_Headers,validate_files, pkg_id)
            else:
                print('Import Package Completed')
            return import_job_status, pkg_id, validate_response
    else:
        sys.exit(f" Import Package API Failed: {import_job}")

def validate_package(baseurl, Headers, files, pkg_id):
    validate_package_request = requests.post(baseurl+'/services/package/actions/validate', headers=Headers, files=files)
    validate_response = validate_package_request.json()
    validate_response_result = validate_response['responseStatus']
    response.append('***Validate Package API Response***')
    response.append(json.dumps(validate_response,indent=4))
    if validate_response_result == 'SUCCESS':
        print('Validate Package Completed')
        return validate_response_result
    else:
        sys.exit(f" Validate Package API Failed: {validate_response}")

def download_package_logs(deploy_results_response, pkg_name):
    try:
        response_details = deploy_results_response.get('responseDetails', {})
        deployment_logs = response_details.get('deployment_log', [])
        if not deployment_logs:
            logger.info("No deployment logs found in response")
            return
        deployment_logs_dir = os.path.join(os.path.dirname(__file__), "deployment_logs")
        os.makedirs(deployment_logs_dir, exist_ok=True)

        for log_entry in deployment_logs:
            filename = log_entry.get('filename', 'unknown')
            download_url = log_entry.get('url', '')
            created_date = log_entry.get('created_date__v', '')
            if download_url:
                r = requests.get(download_url, headers=api_Headers)
                if r.status_code == 200:
                    if 'validation' in filename.lower():
                        local_filename = f"{pkg_name}_validation.log"
                    elif 'deployment' in filename.lower():
                        local_filename = f"{pkg_name}_deployment.log"
                    else:
                        local_filename = filename
                    file_path = os.path.join(deployment_logs_dir, local_filename)
                    with open(file_path, 'wb') as f:
                        f.write(r.content)
                    logger.info(f" Downloaded: {local_filename}")
                    logger.info(f" Location: {file_path}")
                    logger.info(f" Created: {created_date}")
                else:
                    logger.error(f"Failed to download {filename}: HTTP {r.status_code}")
            else:
                logger.error(f" No download URL found for {filename}")
    except Exception as e:
        logger.error(f"Error downloading package logs: {e}")

def deploy_package(baseurl, Headers, pkg_id, vpk_filename):
    deploy_url = baseurl + '/vobject/vault_package__v/' + str(pkg_id) + '/actions/deploy'
    deploy_package_request = requests.post(deploy_url, headers=Headers)  # removed files=files
    try:
        deploy_response = deploy_package_request.json()
    except ValueError:
        deploy_response = {
            'responseStatus': 'FAILURE',
            'responseMessage': f'HTTP {deploy_package_request.status_code} (non-JSON)',
            'raw': deploy_package_request.text
        }
    dep_status = deploy_response.get('responseStatus', 'FAILURE')
    response.append('***Deploy Package API Response***')
    response.append(json.dumps(deploy_response, indent=4))
    job_id = deploy_response.get('job_id')
    if dep_status == 'SUCCESS' and job_id:
        deploy_job_status = get_job_status(baseurl, api_Headers, job_id)
        deploy_job_status_result = deploy_job_status['data']['status']
        if deploy_job_status_result == 'SUCCESS':
            rd_status, rd_response, full_response = retrieve_deploy_package_results(baseurl, Headers, pkg_id)
            pkg_name = vpk_filename.replace('.vpk', '')
            logger.info(f"{pkg_name} - Deployed Successfully into Vault")
            print(f"{pkg_name} - Deployed Successfully into Vault ")
            download_package_logs(full_response, pkg_name)
            return deploy_job_status_result, rd_status, rd_response, full_response
        else:
            return 'FAILURE', deploy_job_status_result, deploy_response, deploy_response
    else:
        # Immediate failure (no job queued)
        return 'FAILURE', None, deploy_response, deploy_response

def retrieve_deploy_package_results(baseurl, Headers, pkg_id):
    r = requests.get(baseurl+'/vobject/vault_package__v/'+str(pkg_id)+'/actions/deploy/results', headers=Headers, files=files)
    resp = r.json()
    response.append('***Retrieve Package Deploy Results API Response***')
    response.append(json.dumps(resp,indent=4))
    new_response = {k: resp['responseDetails'][k] for k in list(resp['responseDetails'])[:list(resp['responseDetails']).index("package_status__v") + 1]}
    print(new_response)
    return resp['responseStatus'], new_response, resp

def get_job_status(Vault_URL, Headers, job_id):
    job_status_response = requests.get(Vault_URL+api_job_status+str(job_id),headers = Headers)
    job_status = job_status_response.json()
    if job_status['data']['status']=='SUCCESS' or job_status['data']['status']=='ERRORS_ENCOUNTERED':
        response.append('***Retrieve Job Status API Response***')
        response.append(json.dumps(job_status,indent=4))
        return job_status
    else:
        time.sleep(10)
        return get_job_status(Vault_URL, api_Headers, job_id)

def excute_mdl(auth_url,headers,filename):
    mdl_path = os.path.join(mdl_dir, filename)
    output_file = os.path.join(mdl_output_dir, "output_"+filename)
    if os.path.exists(mdl_path):
        with open(mdl_path, 'rb') as f, open(output_file, 'w',encoding="utf-8") as out_text:
            binary_data = f.read()
            mdl_request = requests.post(auth_url+"/mdl/execute",headers=headers, data=binary_data)
            mdl_result_response = mdl_request.json()
            json.dump(mdl_request.json(), out_text, ensure_ascii = False, indent = 4)
            if mdl_result_response['responseStatus'] == 'SUCCESS':
                mdl_name = filename.replace('.txt','')
                print(f"{mdl_name} - MDL Executed Successfully")
                logger.info(f"{mdl_name} - MDL Executed Successfully")
                return mdl_result_response['responseStatus'], mdl_result_response
            else:
                print(mdl_result_response)
                sys.exit(f"Execute MDL Script API: {mdl_result_response}")
    else:
        print(f"File not found: {mdl_path}")
        sys.exit(f"File not found: {mdl_path}")

def load_data_objects(baseurl, Headers, payload):
    load_request = requests.post(baseurl+api_version+'load', headers=Headers, data=json.dumps(payload))
    load_data_objects_response = load_request.json()
    response.append('***Load Data Objects API Response***')
    response.append(json.dumps(load_data_objects_response,indent=4))
    print(load_data_objects_response)
    if load_data_objects_response['responseStatus'] == 'FAILURE':
        print(load_data_objects_response['responseMessage'])
        sys.exit(f"Load Data Objects API Failed: {load_data_objects_response}")
    else:
        pass
    load_job_id = load_request.json()['job_id']
    get_job_status(baseurl, api_Headers, load_job_id)
    print("Load Job ID : ",str(load_job_id))

def create_folder(folder_path):
    url = f'{baseurl}/services/file_staging/items'
    Headers = {
        'Authorization': sessionID,
        'Accept': 'application/json',
        'Content-Type': 'multipart/form-data'
    }
    payload = { 'kind': 'folder', 'path': folder_path }
    requests.post(url, headers={'Authorization': sessionID} , data=payload)

def create_file(file,folder_path):
    url = f'{baseurl}/services/file_staging/items'
    Headers = {
        'Authorization': sessionID,
        'Accept': 'application/json'
    }
    files_local = {
        'file': open(file, 'rb'),
        'kind': (None, 'file'),
        'path': (None, folder_path),
        'overwrite': (None, 'true')
    }
    r = requests.post(url,headers=Headers,files=files_local)
    create_file_response = r.json()
    print(create_file_response)
    response.append('***Create File FTP API Response***')
    response.append(json.dumps(create_file_response,indent=4))
    return create_file_response['data']['path']

def file_staging(loader_file,payload,loader_file_name):
    file_path = ftp_folder
    folder = '/'+file_path
    create_folder(folder)
    create_file(loader_file,f"{folder}/{loader_file_name}")
    load_data_objects(baseurl, load_Headers, payload)

def prase_value(value):
    if isinstance(value, str):
        val = value.strip().lower()
        if val == 'true':
            return True
        elif val == 'false' or val == '':
            return False
    return value

def get_password(pwd):
    password_bytes = pwd.encode('ascii')
    password_base64 = base64.b64decode(password_bytes)
    decoded_password = password_base64.decode('ascii')
    return decoded_password

def ensure_csv_not_open(file_path: str) -> None:
    try:
        with open(file_path, 'a'):
            return
    except PermissionError:
        logger.error(f"CSV file is open/locked: {file_path}")
        print(f"'{file_path}' is open in another program (e.g., Excel). Please close it and rerun.")
        sys.exit(f"CSV file '{file_path}' is open. Close it and rerun the script.")

# ---------- EXECUTION ----------
print("Vault URL : "+baseurl)
auth_url = authurl + '/auth'
print("Logging into Vault...")
logger.info("Logging into Vault...")
logger.info(f"Vault URL : {baseurl}")
logger.info(f"User : {username}")
password = get_password(password)
credentials = {'username': username, 'password': password}
authResponse = requests.post(auth_url, data=None, params=credentials)
authContent = authResponse.json()
if authContent['responseStatus'] == 'FAILURE':
    sys.exit(authContent['responseMessage'])
sessionID = authContent['sessionId']
print(sessionID)
logger.info(f"sessionID : {sessionID}")
userId=str(authContent['userId'])
print("Logged into Vault!!!")
logger.info("Logged into Vault!!!")
load_Headers = {'Authorization': sessionID,'Accept':'application/json','Content-Type':'application/json'}
vpk_Headers = {'Authorization': sessionID,'Accept':'application/json'}
api_Headers = {'Authorization': sessionID}
deploy_Headers = {'Authorization': sessionID,'Content-Type':'application/x-www-form-urlencoded'}
mdl_headers = {'Authorization': sessionID,'Accept':'application/json','Content-Type': 'application/json'}

# Read input CSV
ensure_csv_not_open(input_file)
try:
    df = pd.read_csv(input_file)
    print("df ...", df)
except FileNotFoundError:
    print(f"File not found: {input_file}")
    sys.exit(1)
except pd.errors.EmptyDataError:
    print("The file is empty.")
    sys.exit(1)
except Exception as e:
    print(f"Error reading file: {e}")
    sys.exit(1)

# --- Environment-aware columns for retry logic ---
ENVIRONMENT = json_data['env']  # already overridden above if pipeline set ENVIRONMENT
step_col = f"{ENVIRONMENT} Step Status"        # 'Completed' / 'Failed'
env_status_col = f"{ENVIRONMENT} Status"       # 'SUCCESS' / 'FAILURE'

# Ensure these columns exist
if step_col not in df.columns:
    df[step_col] = ''
if env_status_col not in df.columns:
    df[env_status_col] = ''

# Process rows only if THIS environment's step is not Completed
for idx, row in df.iterrows():
    start_time = datetime.now().strftime("%H:%M:%S")

    def mark_result(file_name, success: bool, deploy_log: str = 'N/A'):
        """Update environment-specific columns and common columns, then persist row."""
        df.loc[df['File Name'] == file_name, 'Import Start Time'] = df.get('Import Start Time', 'N/A')
        df.loc[df['File Name'] == file_name, 'Import End Time'] = df.get('Import End Time', 'N/A')
        df.loc[df['File Name'] == file_name, 'Deployment Start Time'] = df.get('Deployment Start Time', start_time)
        df.loc[df['File Name'] == file_name, 'Deployment End Time'] = datetime.now().strftime("%H:%M:%S")
        df.loc[df['File Name'] == file_name, 'Deployment Log'] = str(deploy_log)
        df.loc[df['File Name'] == file_name, 'Executed By'] = str(userId)

        # Env-aware columns used by pipeline filtering
        df.loc[df['File Name'] == file_name, env_status_col] = 'SUCCESS' if success else 'FAILURE'
        df.loc[df['File Name'] == file_name, step_col] = 'Completed' if success else 'Failed'

        ensure_csv_not_open(input_file)
        df.to_csv(input_file, index=False)

    # Skip if already completed for this environment
    if str(row.get(step_col, '')).strip() == 'Completed':
        continue

    # ---- VPK ----
    if row['File Type'] == 'VPK' and vpk_deployment_type is True:
        vpk_filename = (row['File Name'])
        vpk_path = os.path.join(packages_dir, vpk_filename)
        if os.path.exists(vpk_path):
            with open(vpk_path, "rb") as vpk_file:
                files = {'file': vpk_file}
                response = []
                try:
                    if import_deployment_settings is True:
                        import_status, package_id, validate_status = import_package(baseurl, vpk_Headers, files, vpk_filename)
                        df.loc[df['File Name'] == vpk_filename, 'Import Start Time'] = str(start_time)
                        df.loc[df['File Name'] == vpk_filename, 'Import End Time'] = datetime.now().strftime("%H:%M:%S")
                        df.loc[df['File Name'] == vpk_filename, 'Import Status'] = str(import_status)
                        df.loc[df['File Name'] == vpk_filename, 'Vault Package ID'] = str(package_id)
                        df.loc[df['File Name'] == vpk_filename, 'Package Validation Status'] = str(validate_status)
                    else:
                        package_id = row.get('Vault Package ID')

                    if deploy_deployment_settings is True:
                        deploy_start_time = datetime.now().strftime("%H:%M:%S")
                        deploy_status, retrive_deploy_status, retrive_response, deploy_full_response = deploy_package(baseurl, deploy_Headers, package_id, vpk_filename)
                        # Write detailed common columns
                        df.loc[df['File Name'] == vpk_filename, 'Deployment Start Time'] = str(deploy_start_time)
                        df.loc[df['File Name'] == vpk_filename, 'Deployment End Time'] = datetime.now().strftime("%H:%M:%S")
                        df.loc[df['File Name'] == vpk_filename, 'Deployment Status'] = str(deploy_status)
                        df.loc[df['File Name'] == vpk_filename, 'Deployment Log'] = str(retrive_response)

                        # Env-aware status for retry logic
                        mark_result(vpk_filename, success=(str(deploy_status).upper() == 'SUCCESS'), deploy_log=retrive_response)
                    else:
                        # If deploy settings are false, mark completed without deployment
                        mark_result(vpk_filename, success=True, deploy_log='SKIPPED_DEPLOY')
                except Exception as e:
                    logger.error(f"VPK deployment error for {vpk_filename}: {e}")
                    mark_result(vpk_filename, success=False, deploy_log=str(e))
                    continue
                # Save text output
                response_text = "\n".join(response)
                file_path = os.path.join(vpk_output_dir, f"{vpk_filename}_response.txt")
                with open(file_path,'w') as f:
                    f.write(response_text)
                time.sleep(1)
        else:
            print(f"File not found: {vpk_path}")
            mark_result(vpk_filename, success=False, deploy_log=f"File not found: {vpk_path}")

    # ---- MDL ----
    elif row['File Type'] == 'MDL' and mdl_deployment_type is True:
        mdl_filename = (row['File Name'])
        try:
            mdl_status, mdl_log = excute_mdl(authurl, mdl_headers, mdl_filename)
            df.loc[df['File Name'] == mdl_filename, 'Import Start Time'] = 'N/A'
            df.loc[df['File Name'] == mdl_filename, 'Import End Time'] = 'N/A'
            df.loc[df['File Name'] == mdl_filename, 'Import Status'] = 'N/A'
            df.loc[df['File Name'] == mdl_filename, 'Vault Package ID'] = 'N/A'
            df.loc[df['File Name'] == mdl_filename, 'Package Validation Status'] = 'N/A'
            df.loc[df['File Name'] == mdl_filename, 'Deployment Status'] = str(mdl_status)
            mark_result(mdl_filename, success=(str(mdl_status).upper() == 'SUCCESS'), deploy_log=mdl_log)
            # Save text output
            response_text = json.dumps(mdl_log, indent=4)
            file_path = os.path.join(mdl_output_dir, f"{mdl_filename}_response.txt")
            with open(file_path,'w', encoding='utf-8') as f:
                f.write(response_text)
        except Exception as e:
            logger.error(f"MDL error for {mdl_filename}: {e}")
            mark_result(mdl_filename, success=False, deploy_log=str(e))

    # ---- Loader ----
    elif row['File Type'] == 'Loader' and loader_deployment_type is True:
        loader_file_name = (row['File Name'])
        loader_file = os.path.join(loader_dir, loader_file_name)
        try:
            df.loc[df['File Name'] == loader_file_name, 'Deployment Start Time'] = str(start_time)
            if row.get('action') == 'update':
                fields = update_body_parameters
            elif row.get('action') == 'create':
                fields = create_body_parameters
            else:
                fields = []

            payload_dict = {key: prase_value(row.get(key, '')) for key in fields}
            payload_dict['file'] = f"{ftp_folder}/{loader_file_name}"
            payload = [payload_dict]
            response = []
            file_staging(loader_file, payload, loader_file_name)
            mark_result(loader_file_name, success=True, deploy_log='Loader executed')
            # Save text output
            response_text = "\n".join(response)
            file_path = os.path.join(loader_output_dir, f"{loader_file_name}_response.txt")
            with open(file_path,'w') as f:
                f.write(response_text)
        except Exception as e:
            logger.error(f"Loader error for {loader_file_name}: {e}")
            mark_result(loader_file_name, success=False, deploy_log=str(e))

logger.info("Deployment Automation Script Completed")


# Rename CSV file environment-wise after deployment
try:
    # Current environment from ENVIRONMENT variable
    env_name = ENVIRONMENT if ENVIRONMENT else "UnknownEnv"
    
    # Timestamp for uniqueness
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Original file path
    original_csv = input_file
    
    # New file name format: GVault_Deployment_Steps_<ENV>_<timestamp>.csv
    new_csv_name = f"GVault_Deployment_Steps_{env_name}_{timestamp}.csv"
    
    # New file path in same directory
    new_csv_path = original_csv.parent / new_csv_name
    
    # Rename the file
    os.rename(original_csv, new_csv_path)
    
    print(f"CSV file renamed to: {new_csv_path}")
    logger.info(f"CSV file renamed to: {new_csv_path}")
except Exception as e:
    logger.error(f"Error renaming CSV file: {e}")
    print(f"Error renaming CSV file: {e}")
