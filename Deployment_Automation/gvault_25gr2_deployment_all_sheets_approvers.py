#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GVault 25GR2 Deployment Script — updated for Sample CSV + Azure Pipeline
------------------------------------------------------------------------
- Detects input from Deployment_Automation/GVault_Deployment_Steps.xlsx (if present)
  otherwise falls back to Deployment_Automation/GVault_Deployment_Steps.csv (as in pipeline)
- Processes ALL Excel sheets (each sheet = module) or single CSV
- Enforces per-environment approvals using an Approvals sheet (row-wise or wide)
  or JSON fallback for CSV
- Persists updates back (Excel or CSV) and, for CSV, renames to
  GVault_Deployment_Steps_<ENV>_<timestamp>.csv (as the pipeline expects)

Environment variables used by pipeline stages:
  ENVIRONMENT       -> e.g., 'POC1' or 'Contigency' (must match pipeline)
  BYPASS_APPROVALS  -> 'true' to bypass approvals gating
"""
import os
import sys
import json
import time
import base64
import logging
import warnings
from pathlib import Path
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import requests
import pandas as pd

warnings.filterwarnings("ignore")

# -----------------------------------------------------------------------------
# Resolve input file according to sample CSV + pipeline behavior
# -----------------------------------------------------------------------------
base_input_dir = Path("Deployment_Automation")
excel_path = base_input_dir / "GVault_Deployment_Steps.xlsx"
csv_path   = base_input_dir / "GVault_Deployment_Steps.csv"

# Prefer Excel (multi-sheet with Approvals); else CSV (pipeline copies CSV)
if excel_path.exists():
    input_file = excel_path
elif csv_path.exists():
    input_file = csv_path
else:
    print(f"ERROR: Neither '{excel_path}' nor '{csv_path}' found. Ensure pipeline copied CSV or provide Excel.")
    sys.exit(1)

# Output folders
output_dir = 'output_files'
sub_dir1 = "mdl_output_files"
sub_dir2 = "vpk_output_files"
sub_dir3 = "loader_output_files"
join_dir1 = os.path.join(output_dir, sub_dir1)
join_dir2 = os.path.join(output_dir, sub_dir2)
join_dir3 = os.path.join(output_dir, sub_dir3)

# Approvals override from CI (default false)
BYPASS_APPROVALS = str(os.getenv("BYPASS_APPROVALS", "false")).strip().lower() == "true"

# -----------------------------------------------------------------------------
# Load authentication and payloads
# -----------------------------------------------------------------------------
with open("authentication.json") as json_file:
    json_data = json.load(json_file)
    ENVIRONMENT = os.getenv("ENVIRONMENT")  # optional CI override (e.g., POC1 / Contigency)
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

# Ensure dirs
os.makedirs('logs', exist_ok=True)
os.makedirs(join_dir1, exist_ok=True)
os.makedirs(join_dir2, exist_ok=True)
os.makedirs(join_dir3, exist_ok=True)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
log_format = "%(asctime)s - %(levelname)s - %(message)s"
handler = TimedRotatingFileHandler("logs/logfile.log", when="midnight", interval=1)
formatter = logging.Formatter(log_format)
handler.setFormatter(formatter)
handler.suffix = "%Y%m%d"
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
logger.info("****** Started Deployment Automation Script ******")

# -----------------------------------------------------------------------------
# Vault API helpers (unchanged core logic)
# -----------------------------------------------------------------------------

def import_package(baseurl, Headers, files, pkg_name):
    import_package_request = requests.put(baseurl+'/services/package', headers=Headers, files=files)
    import_response = import_package_request.json()
    response.append('***Import Package API Response***')
    response.append(json.dumps(import_response, indent=4))
    job_id = import_package_request.json()['job_id']
    import_job = get_job_status(baseurl, api_Headers, job_id)
    import_job_status = import_job['data']['status']
    if import_job_status == 'SUCCESS':
        print('Import Package Job Status:', str(import_job_status))
        href = import_job['data']['links'][1]['href']
        parts = href.split('/')
        pkg_id = parts[5] if len(parts)>5 else None
        print('Package ID:', pkg_id)
        vpk_path = os.path.join(packages_dir, vpk_filename)
        if validate_deployment_settings is True:
            if os.path.exists(vpk_path):
                with open(vpk_path, "rb") as vpk_file:
                    validate_files = {'file': vpk_file}
                    validate_response = validate_package(baseurl, vpk_Headers, validate_files, pkg_id)
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
    response.append(json.dumps(validate_response, indent=4))
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
    deploy_package_request = requests.post(deploy_url, headers=Headers)
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
        return 'FAILURE', None, deploy_response, deploy_response


def retrieve_deploy_package_results(baseurl, Headers, pkg_id):
    r = requests.get(baseurl+'/vobject/vault_package__v/'+str(pkg_id)+'/actions/deploy/results', headers=Headers, files=files)
    resp = r.json()
    response.append('***Retrieve Package Deploy Results API Response***')
    response.append(json.dumps(resp, indent=4))
    new_response = {k: resp['responseDetails'][k] for k in list(resp['responseDetails'])[:list(resp['responseDetails']).index("package_status__v") + 1]}
    print(new_response)
    return resp['responseStatus'], new_response, resp


def get_job_status(Vault_URL, Headers, job_id):
    job_status_response = requests.get(Vault_URL+api_job_status+str(job_id), headers=Headers)
    job_status = job_status_response.json()
    if job_status['data']['status']=='SUCCESS' or job_status['data']['status']=='ERRORS_ENCOUNTERED':
        response.append('***Retrieve Job Status API Response***')
        response.append(json.dumps(job_status, indent=4))
        return job_status
    else:
        time.sleep(10)
        return get_job_status(Vault_URL, api_Headers, job_id)


def excute_mdl(auth_url, headers, filename):
    mdl_path = os.path.join(mdl_dir, filename)
    output_file = os.path.join(mdl_output_dir, "output_"+filename)
    if os.path.exists(mdl_path):
        with open(mdl_path, 'rb') as f, open(output_file, 'w', encoding="utf-8") as out_text:
            binary_data = f.read()
            mdl_request = requests.post(auth_url+"/mdl/execute", headers=headers, data=binary_data)
            mdl_result_response = mdl_request.json()
            json.dump(mdl_request.json(), out_text, ensure_ascii=False, indent=4)
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
    response.append(json.dumps(load_data_objects_response, indent=4))
    print(load_data_objects_response)
    if load_data_objects_response['responseStatus'] == 'FAILURE':
        print(load_data_objects_response['responseMessage'])
        sys.exit(f"Load Data Objects API Failed: {load_data_objects_response}")
    load_job_id = load_request.json()['job_id']
    get_job_status(baseurl, api_Headers, load_job_id)
    print("Load Job ID : ", str(load_job_id))


def create_folder(folder_path):
    url = f'{baseurl}/services/file_staging/items'
    Headers = {
        'Authorization': sessionID,
        'Accept': 'application/json',
        'Content-Type': 'multipart/form-data'
    }
    payload = { 'kind': 'folder', 'path': folder_path }
    requests.post(url, headers={'Authorization': sessionID} , data=payload)


def create_file(file, folder_path):
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
    r = requests.post(url, headers=Headers, files=files_local)
    create_file_response = r.json()
    print(create_file_response)
    response.append('***Create File FTP API Response***')
    response.append(json.dumps(create_file_response, indent=4))
    return create_file_response['data']['path']


def file_staging(loader_file, payload, loader_file_name):
    file_path = ftp_folder
    folder = '/' + file_path
    create_folder(folder)
    create_file(loader_file, f"{folder}/{loader_file_name}")
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

# -----------------------------------------------------------------------------
# File helpers + Approvals helpers
# -----------------------------------------------------------------------------

def ensure_file_not_open(file_path: str) -> None:
    try:
        with open(file_path, 'a'):
            return
    except PermissionError:
        logger.error(f"File is open/locked: {file_path}")
        print(f"'{file_path}' is open in another program. Please close it and rerun.")
        sys.exit(f"File '{file_path}' is open. Close it and rerun the script.")

def is_excel(path: str) -> bool:
    return str(path).lower().endswith((".xlsx", ".xls"))

def read_input(input_path):
    """Return (workbook_dict, is_excel_file).
    - If Excel: dict[str, DataFrame] for all sheets.
    - If CSV: {'__CSV__': DataFrame}
    """
    ensure_file_not_open(input_path)
    try:
        if is_excel(str(input_path)):
            wb = pd.read_excel(input_path, sheet_name=None, engine='openpyxl')
            if not wb:
                raise ValueError('The Excel file has no sheets.')
            return wb, True
        else:
            df = pd.read_csv(input_path)
            return {"__CSV__": df}, False
    except FileNotFoundError:
        print(f"File not found: {input_path}")
        sys.exit(1)
    except pd.errors.EmptyDataError:
        print("The file is empty.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)

# ---- approvals utilities ----

def _split_emails(text: str):
    if not text or str(text).strip() == "":
        return []
    import re
    return [e.strip().lower() for e in re.split(r"[;,]", str(text)) if e.strip()]

def _norm_env(env: str) -> str:
    return str(env).strip()

def _pick(r, *keys, default=""):
    for k in keys:
        v = r.get(k, "")
        if v not in (None, ""):
            return v
    return default

def _load_rowwise_approvals(appr_df: pd.DataFrame, env: str) -> dict:
    approvals = {}
    env_norm = _norm_env(env)
    for i, r in appr_df.iterrows():
        sheet = str(r.get("Sheet", "")).strip()
        row_env = str(r.get("Environment", "")).strip()
        if not sheet or row_env != env_norm:
            continue
        policy = str(r.get("Policy", "ANY")).strip().upper()
        if policy not in {"ALL", "ANY", "AT_LEAST_N"}:
            policy = "ANY"
        try:
            n_required = int(r.get("N", 1) or 1)
        except Exception:
            n_required = 1
        approvals[sheet] = {
            "policy": policy,
            "n": n_required,
            "approvers": _split_emails(r.get("Approvers", "")),
            "approved_by": _split_emails(r.get("Approved By", "")),
            "state": str(r.get("Approval State", "PENDING")).strip().upper(),
            "row_index": i,
        }
    return approvals

def _load_wide_approvals(appr_df: pd.DataFrame, env: str) -> dict:
    approvals = {}
    env_norm = _norm_env(env)
    prefix = f"{env_norm} "
    needed = {
        "approvers": prefix + "Approvers",
        "policy": prefix + "Policy",
        "n": prefix + "N",
        "approved_by": prefix + "Approved By",
        "state": prefix + "Approval State",
    }
    for i, r in appr_df.iterrows():
        sheet = str(r.get("Sheet", "")).strip()
        if not sheet:
            continue
        policy = str(r.get(needed["policy"], "ANY")).strip().upper()
        if policy not in {"ALL", "ANY", "AT_LEAST_N"}:
            policy = "ANY"
        try:
            n_required = int(_pick(r, needed["n"], default=1) or 1)
        except Exception:
            n_required = 1
        approvals[sheet] = {
            "policy": policy,
            "n": n_required,
            "approvers": _split_emails(r.get(needed["approvers"], "")),
            "approved_by": _split_emails(r.get(needed["approved_by"], "")),
            "state": str(r.get(needed["state"], "PENDING")).strip().upper(),
            "row_index": i,
        }
    return approvals

def load_approvals_from_workbook_env(workbook_dict: dict, env: str):
    key = next((k for k in workbook_dict.keys() if k.lower() == "approvals"), None)
    if not key:
        return {}, None
    appr_df = workbook_dict[key]
    if appr_df is None or getattr(appr_df, "empty", False):
        return {}, key
    cols = set(appr_df.columns.astype(str))
    if {"Sheet", "Environment", "Approvers", "Policy", "Approved By", "Approval State"}.issubset(cols):
        return _load_rowwise_approvals(appr_df, env), key
    else:
        env_norm = _norm_env(env)
        if any(c.startswith(f"{env_norm} ") for c in cols):
            return _load_wide_approvals(appr_df, env), key
    return {}, key

def load_approvals_from_json(cfg: dict, env: str):
    data = cfg.get("approvals", {})
    approvals = {}
    for sheet, by_env in data.items():
        env_meta = by_env.get(env, {}) if isinstance(by_env, dict) else {}
        approvals[sheet] = {
            "policy": str(env_meta.get("policy", "ANY")).upper(),
            "n": int(env_meta.get("n", 1) or 1),
            "approvers": [e.lower() for e in env_meta.get("approvers", [])],
            "approved_by": [e.lower() for e in env_meta.get("approved_by", [])],
            "state": str(env_meta.get("state", "PENDING")).upper(),
            "row_index": None,
        }
    return approvals

def is_policy_satisfied(meta: dict) -> bool:
    policy = meta["policy"]
    approvers = set([a.lower() for a in meta["approvers"]])
    approved = set([a.lower() for a in meta["approved_by"]])
    if policy == "ALL":
        return approvers.issubset(approved) and len(approvers) > 0
    if policy == "ANY":
        return len(approved.intersection(approvers)) >= 1
    if policy == "AT_LEAST_N":
        return len(approved.intersection(approvers)) >= int(meta.get("n", 1))
    return False

def is_sheet_approved(sheet_name: str, approvals_cfg: dict) -> (bool, str):
    meta = approvals_cfg.get(sheet_name)
    if meta is None:
        return True, "No approval rule configured (default allow)."
    state = meta.get("state", "PENDING").upper()
    if state != "APPROVED":
        return False, f"Approval State is '{state}'."
    if not is_policy_satisfied(meta):
        return False, f"Policy '{meta['policy']}' not satisfied."
    return True, "Approved and policy satisfied."

# -----------------------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Per-sheet processing
# -----------------------------------------------------------------------------

def process_df(df_local: pd.DataFrame) -> pd.DataFrame:
    ENV = json_data['env']
    # Align with sample CSV: '<ENV> Step Status' and '<ENV> Status'
    step_col = f"{ENV} Step Status"
    env_status_col = f"{ENV} Status"

    # Ensure env-aware columns exist (per sample CSV columns)
    if step_col not in df_local.columns:
        df_local[step_col] = ''
    if env_status_col not in df_local.columns:
        df_local[env_status_col] = ''

    for idx, row in df_local.iterrows():
        start_time = datetime.now().strftime("%H:%M:%S")

        def mark_result(file_name, success: bool, deploy_log: str = 'N/A'):
            # Update both common and env-specific fields
            df_local.loc[df_local['File Name'] == file_name, 'Deployment Start Time'] = df_local.get('Deployment Start Time', start_time)
            df_local.loc[df_local['File Name'] == file_name, 'Deployment End Time'] = datetime.now().strftime("%H:%M:%S")
            df_local.loc[df_local['File Name'] == file_name, 'Deployment Log'] = str(deploy_log)
            df_local.loc[df_local['File Name'] == file_name, 'Executed By'] = str(userId)
            df_local.loc[df_local['File Name'] == file_name, env_status_col] = 'SUCCESS' if success else 'FAILURE'
            df_local.loc[df_local['File Name'] == file_name, step_col] = 'Completed' if success else 'Failed'

        # Skip if already completed for this environment
        if str(row.get(step_col, '')).strip() == 'Completed':
            continue

        # ----- VPK -----
        if row.get('File Type') == 'VPK' and vpk_deployment_type is True:
            vpk_filename = (row.get('File Name'))
            vpk_path = os.path.join(packages_dir, vpk_filename)
            if os.path.exists(vpk_path):
                with open(vpk_path, "rb") as vpk_file:
                    global files
                    files = {'file': vpk_file}
                    response.clear()
                    try:
                        package_id = row.get('Vault Package ID')
                        if import_deployment_settings is True:
                            import_status, package_id, validate_status = import_package(baseurl, vpk_Headers, files, vpk_filename)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Import Start Time'] = str(start_time)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Import End Time'] = datetime.now().strftime("%H:%M:%S")
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Import Status'] = str(import_status)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Vault Package ID'] = str(package_id)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Package Validation Status'] = str(validate_status)
                        if deploy_deployment_settings is True:
                            deploy_start_time = datetime.now().strftime("%H:%M:%S")
                            deploy_status, rd_status, rd_response, deploy_full_response = deploy_package(baseurl, deploy_Headers, package_id, vpk_filename)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Deployment Start Time'] = str(deploy_start_time)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Deployment End Time'] = datetime.now().strftime("%H:%M:%S")
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Deployment Status'] = str(deploy_status)
                            df_local.loc[df_local['File Name'] == vpk_filename, 'Deployment Log'] = str(rd_response)
                            mark_result(vpk_filename, success=(str(deploy_status).upper() == 'SUCCESS'), deploy_log=rd_response)
                        else:
                            mark_result(vpk_filename, success=True, deploy_log='SKIPPED_DEPLOY')
                    except Exception as e:
                        logger.error(f"VPK deployment error for {vpk_filename}: {e}")
                        mark_result(vpk_filename, success=False, deploy_log=str(e))
                        continue
                    # Save per-file API response
                    response_text = "\n".join(response)
                    file_path = os.path.join(vpk_output_dir, f"{vpk_filename}_response.txt")
                    with open(file_path, 'w') as f:
                        f.write(response_text)
                    time.sleep(1)
            else:
                print(f"File not found: {vpk_path}")
                mark_result(vpk_filename, success=False, deploy_log=f"File not found: {vpk_path}")

        # ----- MDL -----
        elif row.get('File Type') == 'MDL' and mdl_deployment_type is True:
            mdl_filename = (row.get('File Name'))
            try:
                global response
                response = []
                mdl_status, mdl_log = excute_mdl(authurl, mdl_headers, mdl_filename)
                df_local.loc[df_local['File Name'] == mdl_filename, 'Import Start Time'] = 'N/A'
                df_local.loc[df_local['File Name'] == mdl_filename, 'Import End Time'] = 'N/A'
                df_local.loc[df_local['File Name'] == mdl_filename, 'Import Status'] = 'N/A'
                df_local.loc[df_local['File Name'] == mdl_filename, 'Vault Package ID'] = 'N/A'
                df_local.loc[df_local['File Name'] == mdl_filename, 'Package Validation Status'] = 'N/A'
                df_local.loc[df_local['File Name'] == mdl_filename, 'Deployment Status'] = str(mdl_status)
                mark_result(mdl_filename, success=(str(mdl_status).upper() == 'SUCCESS'), deploy_log=mdl_log)
                response_text = json.dumps(mdl_log, indent=4)
                file_path = os.path.join(mdl_output_dir, f"{mdl_filename}_response.txt")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(response_text)
            except Exception as e:
                logger.error(f"MDL error for {mdl_filename}: {e}")
                mark_result(mdl_filename, success=False, deploy_log=str(e))

        # ----- Loader -----
        elif row.get('File Type') == 'Loader' and loader_deployment_type is True:
            loader_file_name = (row.get('File Name'))
            loader_file = os.path.join(loader_dir, loader_file_name)
            try:
                df_local.loc[df_local['File Name'] == loader_file_name, 'Deployment Start Time'] = str(start_time)
                if row.get('action') == 'update':
                    fields = update_body_parameters
                elif row.get('action') == 'create':
                    fields = create_body_parameters
                else:
                    fields = []
                payload_dict = {key: prase_value(row.get(key, '')) for key in fields}
                payload_dict['file'] = f"{ftp_folder}/{loader_file_name}"
                payload = [payload_dict]
                global response
                response = []
                file_staging(loader_file, payload, loader_file_name)
                mark_result(loader_file_name, success=True, deploy_log='Loader executed')
                response_text = "\n".join(response)
                file_path = os.path.join(loader_output_dir, f"{loader_file_name}_response.txt")
                with open(file_path, 'w') as f:
                    f.write(response_text)
            except Exception as e:
                logger.error(f"Loader error for {loader_file_name}: {e}")
                mark_result(loader_file_name, success=False, deploy_log=str(e))

    return df_local

# -----------------------------------------------------------------------------
# Read input (CSV or Excel) and enforce approvals per ENV
# -----------------------------------------------------------------------------
workbook_dict, is_xl = read_input(input_file)
ENV = json_data["env"]

# Load approvals: Excel Approvals sheet if present; else JSON fallback for CSV
approvals_cfg, approvals_sheet_key = ({}, None)
if is_xl:
    approvals_cfg, approvals_sheet_key = load_approvals_from_workbook_env(workbook_dict, ENV)
else:
    approvals_cfg = load_approvals_from_json(deployment_json_data, ENV)

processed = {}
for sheet_name, df_sheet in workbook_dict.items():
    # Carry over Approvals sheet untouched
    if is_xl and approvals_sheet_key and sheet_name == approvals_sheet_key:
        processed[sheet_name] = df_sheet.copy()
        continue

    if df_sheet is None or getattr(df_sheet, 'empty', False):
        processed[sheet_name] = df_sheet
        continue

    # Approval gate (unless bypassed)
    if not BYPASS_APPROVALS:
        ok, reason = is_sheet_approved(sheet_name, approvals_cfg)
        if not ok:
            logger.warning(f"Skipping module '{sheet_name}' — {reason}")
            print(f"Skipping module '{sheet_name}' — {reason}")
            try:
                df_copy = df_sheet.copy()
                df_copy["Approval Gate"] = reason
                processed[sheet_name] = df_copy
            except Exception:
                processed[sheet_name] = df_sheet
            continue
    else:
        logger.warning(f"BYPASS_APPROVALS=true — proceeding without approvals for '{sheet_name}'")
        print(f"BYPASS_APPROVALS=true — proceeding without approvals for '{sheet_name}'")

    processed[sheet_name] = process_df(df_sheet.copy())

# Optional: stamp 'Last Checked At' in Approvals sheet
if is_xl and approvals_sheet_key:
    try:
        appr_df = processed.get(approvals_sheet_key, workbook_dict[approvals_sheet_key]).copy()
        appr_df["Last Checked At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        processed[approvals_sheet_key] = appr_df
    except Exception as e:
        logger.error(f"Failed to update 'Last Checked At' in Approvals: {e}")

# -----------------------------------------------------------------------------
# Persist results back
# -----------------------------------------------------------------------------
if is_xl:
    ensure_file_not_open(input_file)
    with pd.ExcelWriter(input_file, engine='openpyxl', mode='w') as writer:
        for sname, sdf in processed.items():
            sdf.to_excel(writer, sheet_name=sname, index=False, na_rep='N/A')
else:
    ensure_file_not_open(input_file)
    processed['__CSV__'].to_csv(input_file, index=False, na_rep='N/A')

logger.info("Deployment Automation Script Completed")

# CSV rename to match pipeline discovery pattern (Excel is not renamed)
try:
    if not is_xl:
        env_name = json_data['env'] if json_data.get('env') else 'Env'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_csv = input_file
        new_csv_name = f"GVault_Deployment_Steps_{env_name}_{timestamp}.csv"
        new_csv_path = original_csv.parent / new_csv_name
        os.rename(original_csv, new_csv_path)
        print(f"CSV file renamed to: {new_csv_path}")
        logger.info(f"CSV file renamed to: {new_csv_path}")
except Exception as e:
    logger.error(f"Error renaming file: {e}")
    print(f"Error renaming file: {e}")
