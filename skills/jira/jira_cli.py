import os
import sys
import json
import argparse
from datetime import datetime
import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
TIMERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_timers.json")

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Config file not found at {CONFIG_PATH}. Please run setup or create config.json.")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_timers():
    if not os.path.exists(TIMERS_PATH):
        return {}
    try:
        with open(TIMERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_timers(timers):
    with open(TIMERS_PATH, "w", encoding="utf-8") as f:
        json.dump(timers, f, ensure_ascii=False, indent=2)

def get_headers(config):
    pat = config.get("pat_token", "").strip()
    if not pat or pat == "YOUR_PERSONAL_ACCESS_TOKEN_HERE":
        print("Error: Personal Access Token (pat_token) is not set in config.json.")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def get_base_url(config):
    url = config.get("jira_url", "https://jira.atomcorp.org").rstrip("/")
    return url

def test_connection():
    cfg = load_config()
    url = f"{get_base_url(cfg)}/rest/api/2/myself"
    try:
        res = requests.get(url, headers=get_headers(cfg), timeout=40)
        if res.status_code == 200:
            data = res.json()
            print(json.dumps({"status": "ok", "user": data.get("displayName"), "username": data.get("name"), "email": data.get("emailAddress")}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"status": "error", "code": res.status_code, "response": res.text}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))

def get_my_tasks(limit=15):
    cfg = load_config()
    jql = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
    url = f"{get_base_url(cfg)}/rest/api/2/search"
    params = {"jql": jql, "maxResults": limit, "fields": "summary,status,priority,updated,created,worklog"}
    try:
        res = requests.get(url, headers=get_headers(cfg), params=params, timeout=40)
        if res.status_code == 200:
            data = res.json()
            issues = []
            for item in data.get("issues", []):
                issues.append({
                    "key": item.get("key"),
                    "summary": item["fields"].get("summary"),
                    "status": item["fields"]["status"].get("name"),
                    "priority": item["fields"]["priority"].get("name") if item["fields"].get("priority") else None,
                    "updated": item["fields"].get("updated")
                })
            print(json.dumps({"status": "ok", "total": data.get("total"), "issues": issues}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"status": "error", "code": res.status_code, "response": res.text}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))

def get_issue(issue_key):
    cfg = load_config()
    url = f"{get_base_url(cfg)}/rest/api/2/issue/{issue_key}"
    try:
        res = requests.get(url, headers=get_headers(cfg), timeout=40)
        if res.status_code == 200:
            data = res.json()
            fields = data.get("fields", {})
            issue_data = {
                "key": data.get("key"),
                "summary": fields.get("summary"),
                "description": fields.get("description"),
                "status": fields["status"].get("name") if fields.get("status") else None,
                "assignee": fields["assignee"].get("displayName") if fields.get("assignee") else None,
                "reporter": fields["reporter"].get("displayName") if fields.get("reporter") else None,
                "timeestimate": fields.get("timeestimate"),
                "timespent": fields.get("timespent"),
                "created": fields.get("created"),
                "updated": fields.get("updated")
            }
            print(json.dumps({"status": "ok", "issue": issue_data}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"status": "error", "code": res.status_code, "response": res.text}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))

def add_worklog(issue_key, time_spent, comment=None, started_iso=None):
    cfg = load_config()
    url = f"{get_base_url(cfg)}/rest/api/2/issue/{issue_key}/worklog"
    now_str = started_iso or datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S.000%z")
    payload = {
        "timeSpent": time_spent,
        "started": now_str
    }
    if comment:
        payload["comment"] = comment
    try:
        res = requests.post(url, headers=get_headers(cfg), json=payload, timeout=40)
        if res.status_code in (200, 201):
            data = res.json()
            return {"status": "ok", "data": data}
        else:
            return {"status": "error", "code": res.status_code, "response": res.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def search_jql(jql, limit=15):
    cfg = load_config()
    url = f"{get_base_url(cfg)}/rest/api/2/search"
    params = {"jql": jql, "maxResults": limit, "fields": "summary,status,assignee,updated"}
    try:
        res = requests.get(url, headers=get_headers(cfg), params=params, timeout=40)
        if res.status_code == 200:
            data = res.json()
            issues = []
            for item in data.get("issues", []):
                issues.append({
                    "key": item.get("key"),
                    "summary": item["fields"].get("summary"),
                    "status": item["fields"]["status"].get("name"),
                    "assignee": item["fields"]["assignee"].get("displayName") if item["fields"].get("assignee") else None,
                    "updated": item["fields"].get("updated")
                })
            print(json.dumps({"status": "ok", "total": data.get("total"), "issues": issues}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"status": "error", "code": res.status_code, "response": res.text}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))

def create_issue(project_key, summary, description=None, issue_type="Task", assign_to_me=True):
    cfg = load_config()
    url = f"{get_base_url(cfg)}/rest/api/2/issue"
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type}
        }
    }
    if description:
        payload["fields"]["description"] = description
        
    headers = get_headers(cfg)
    
    if assign_to_me:
        try:
            myself_res = requests.get(f"{get_base_url(cfg)}/rest/api/2/myself", headers=headers, timeout=40)
            if myself_res.status_code == 200:
                username = myself_res.json().get("name")
                if username:
                    payload["fields"]["assignee"] = {"name": username}
        except Exception:
            pass

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=40)
        if res.status_code in (200, 201):
            data = res.json()
            print(json.dumps({
                "status": "ok",
                "key": data.get("key"),
                "id": data.get("id"),
                "self": data.get("self")
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"status": "error", "code": res.status_code, "response": res.text}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))

def transition_issue(issue_key, target_status):
    cfg = load_config()
    headers = get_headers(cfg)
    url_trans = f"{get_base_url(cfg)}/rest/api/2/issue/{issue_key}/transitions"
    try:
        res = requests.get(url_trans, headers=headers, timeout=40)
        if res.status_code != 200:
            return {"status": "error", "message": f"Could not get transitions: {res.text}"}
        transitions = res.json().get("transitions", [])
        matched_id = None
        target_lower = target_status.lower()
        for tr in transitions:
            if tr.get("name", "").lower() == target_lower or tr.get("to", {}).get("name", "").lower() == target_lower:
                matched_id = tr.get("id")
                break
        if not matched_id and transitions:
            # Check if any transition contains target substring
            for tr in transitions:
                if target_lower in tr.get("name", "").lower() or target_lower in tr.get("to", {}).get("name", "").lower():
                    matched_id = tr.get("id")
                    break

        if not matched_id:
            valid_names = [t.get("name") for t in transitions]
            return {"status": "error", "message": f"Transition '{target_status}' not found. Available: {valid_names}"}

        post_res = requests.post(url_trans, headers=headers, json={"transition": {"id": matched_id}}, timeout=40)
        if post_res.status_code in (200, 204):
            return {"status": "ok", "transition_id": matched_id, "status_name": target_status}
        else:
            return {"status": "error", "code": post_res.status_code, "response": post_res.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def update_issue(issue_key, summary=None, description=None):
    cfg = load_config()
    headers = get_headers(cfg)
    url = f"{get_base_url(cfg)}/rest/api/2/issue/{issue_key}"
    fields = {}
    if summary:
        fields["summary"] = summary
    if description:
        fields["description"] = description
    if not fields:
        return {"status": "error", "message": "Nothing to update"}
    try:
        res = requests.put(url, headers=headers, json={"fields": fields}, timeout=40)
        if res.status_code in (200, 204):
            return {"status": "ok", "key": issue_key, "summary": summary}
        else:
            return {"status": "error", "code": res.status_code, "response": res.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def add_comment_to_issue(issue_key, comment):
    cfg = load_config()
    headers = get_headers(cfg)
    url = f"{get_base_url(cfg)}/rest/api/2/issue/{issue_key}/comment"
    try:
        res = requests.post(url, headers=headers, json={"body": comment}, timeout=15)
        if res.status_code in (200, 201):
            return {"status": "ok", "key": issue_key, "comment": comment}
        else:
            return {"status": "error", "code": res.status_code, "response": res.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}



def start_timer(issue_key):
    timers = load_timers()
    now_dt = datetime.now().astimezone()
    start_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    formatted_start = now_dt.strftime("%H:%M:%S")
    
    timers[issue_key.upper()] = {
        "start_iso": start_iso,
        "start_formatted": formatted_start
    }
    save_timers(timers)
    print(json.dumps({
        "status": "ok",
        "key": issue_key.upper(),
        "start_time": formatted_start,
        "message": f"Таймер запущен для {issue_key.upper()} в {formatted_start}"
    }, ensure_ascii=False, indent=2))

def stop_timer(issue_key, comment=None, transition_done=True):
    timers = load_timers()
    key_upper = issue_key.upper()
    
    start_dt = None
    if key_upper in timers:
        timer_info = timers.pop(key_upper)
        save_timers(timers)
        start_dt = datetime.fromisoformat(timer_info["start_iso"])

    end_dt = datetime.now().astimezone()

    if start_dt:
        diff_seconds = int((end_dt - start_dt).total_seconds())
        minutes = max(1, diff_seconds // 60)
        hours = minutes // 60
        rem_minutes = minutes % 60

        if hours > 0:
            time_spent_str = f"{hours}h {rem_minutes}m" if rem_minutes > 0 else f"{hours}h"
        else:
            time_spent_str = f"{minutes}m"
        start_formatted = start_dt.strftime("%H:%M")
        end_formatted = end_dt.strftime("%H:%M")
        full_comment = f"Выполнено с {start_formatted} по {end_formatted}."
        if comment:
            full_comment += f" {comment}"
        wl_result = add_worklog(key_upper, time_spent_str, full_comment, started_iso=start_dt.strftime("%Y-%m-%dT%H:%M:%S.000%z"))
    else:
        # No timer was running
        start_formatted = None
        end_formatted = end_dt.strftime("%H:%M")
        time_spent_str = None
        full_comment = comment or "Задача выполнена"
        wl_result = None

    trans_result = None
    if transition_done:
        trans_result = transition_issue(key_upper, "Done")
        if trans_result.get("status") != "ok":
            trans_result = transition_issue(key_upper, "Завершено")

    print(json.dumps({
        "status": "ok",
        "key": key_upper,
        "has_timer": start_dt is not None,
        "start_time": start_formatted,
        "end_time": end_formatted,
        "time_spent": time_spent_str,
        "comment": full_comment,
        "worklog": wl_result,
        "transition": trans_result
    }, ensure_ascii=False, indent=2))

def list_timers():
    timers = load_timers()
    if not timers:
        print(json.dumps({"status": "ok", "timers": []}, ensure_ascii=False))
        return
    now_dt = datetime.now().astimezone()
    active_list = []
    for key, info in timers.items():
        start_dt = datetime.fromisoformat(info["start_iso"])
        elapsed_min = int((now_dt - start_dt).total_seconds() // 60)
        active_list.append({
            "key": key,
            "start_time": info["start_formatted"],
            "elapsed_minutes": elapsed_min
        })
    print(json.dumps({"status": "ok", "timers": active_list}, ensure_ascii=False, indent=2))

def main():
    parser = argparse.ArgumentParser(description="Jira Data Center CLI Helper")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("test", help="Test connection to Jira")
    
    my_tasks_parser = subparsers.add_parser("my-tasks", help="Get my open tasks")
    my_tasks_parser.add_argument("--limit", type=int, default=15)

    get_parser = subparsers.add_parser("get", help="Get details of a specific issue")
    get_parser.add_argument("key", help="Issue Key (e.g. PROJ-123)")

    worklog_parser = subparsers.add_parser("worklog", help="Add worklog time to issue")
    worklog_parser.add_argument("key", help="Issue Key (e.g. PROJ-123)")
    worklog_parser.add_argument("time", help="Time spent (e.g. '2h 30m', '45m', '1d')")
    worklog_parser.add_argument("--comment", "-m", help="Comment for worklog", default=None)

    search_parser = subparsers.add_parser("search", help="Search issues by JQL")
    search_parser.add_argument("jql", help="JQL query string")
    search_parser.add_argument("--limit", type=int, default=15)

    create_parser = subparsers.add_parser("create", help="Create new issue")
    create_parser.add_argument("project", help="Project Key (e.g. TAU)")
    create_parser.add_argument("summary", help="Issue summary / title")
    create_parser.add_argument("--description", "-d", help="Issue description", default=None)
    create_parser.add_argument("--type", "-t", help="Issue type (default: Task)", default="Task")

    start_timer_parser = subparsers.add_parser("start-timer", help="Start timer for an issue")
    start_timer_parser.add_argument("key", help="Issue Key (e.g. TAU-27)")

    stop_timer_parser = subparsers.add_parser("stop-timer", help="Stop timer for an issue and log work")
    stop_timer_parser.add_argument("key", help="Issue Key (e.g. TAU-27)")
    stop_timer_parser.add_argument("--comment", "-m", help="Optional worklog comment", default=None)

    transition_parser = subparsers.add_parser("transition", help="Transition issue status")
    transition_parser.add_argument("key", help="Issue Key (e.g. TAU-27)")
    transition_parser.add_argument("status", help="Target status name (e.g. Done)")

    update_parser = subparsers.add_parser("update", help="Update issue fields")
    update_parser.add_argument("key", help="Issue Key (e.g. TAU-28)")
    update_parser.add_argument("--summary", "-s", help="New summary", default=None)
    update_parser.add_argument("--description", "-d", help="New description", default=None)

    comment_parser = subparsers.add_parser("comment", help="Add comment to an issue")
    comment_parser.add_argument("key", help="Issue Key (e.g. TAU-28)")
    comment_parser.add_argument("text", help="Comment text")

    subparsers.add_parser("list-timers", help="List all running timers")

    args = parser.parse_args()

    if args.command == "test":
        test_connection()
    elif args.command == "my-tasks":
        get_my_tasks(args.limit)
    elif args.command == "get":
        get_issue(args.key)
    elif args.command == "worklog":
        res = add_worklog(args.key, args.time, args.comment)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.command == "search":
        search_jql(args.jql, args.limit)
    elif args.command == "create":
        create_issue(args.project, args.summary, args.description, args.type)
    elif args.command == "start-timer":
        start_timer(args.key)
    elif args.command == "stop-timer":
        stop_timer(args.key, args.comment)
    elif args.command == "transition":
        res = transition_issue(args.key, args.status)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.command == "update":
        res = update_issue(args.key, args.summary, args.description)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.command == "comment":
        res = add_comment_to_issue(args.key, args.text)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.command == "list-timers":
        list_timers()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()


