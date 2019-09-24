import argparse
import json
import os
from collections import OrderedDict

import taskcluster
from six import iteritems, itervalues
from six.moves.urllib import request

from . import taskgraph

TC_ROOT = "https://taskcluster.net"
QUEUE_BASE = "https://queue.taskcluster.net/v1/task"


here = os.path.abspath(os.path.dirname(__file__))


def get_triggers(event):
    # Set some variables that we use to get the commits on the current branch
    ref_prefix = "refs/heads/"
    pull_request = "pull_request" in event
    branch = None
    if not pull_request and "ref" in event:
        branch = event["ref"]
        if branch.startswith(ref_prefix):
            branch = branch[len(ref_prefix):]

    return pull_request, branch


def fetch_event_data():
    try:
        task_id = os.environ["TASK_ID"]
    except KeyError:
        print("WARNING: Missing TASK_ID environment variable")
        # For example under local testing
        return None

    resp = request("%s/%s" % (QUEUE_BASE, task_id))

    task_data = json.load(resp)
    event_data = task_data.get("extra", {}).get("github_event")
    if event_data is not None:
        return event_data


def filter_triggers(event, all_tasks):
    is_pr, branch = get_triggers(event)
    triggered = {}
    for name, task in iteritems(all_tasks):
        if "trigger" in task:
            if is_pr and "pull-request" in task["trigger"]:
                triggered[name] = task
            elif branch is not None and "branch" in task["trigger"]:
                for trigger_branch in task["trigger"]["branch"]:
                    if (trigger_branch == branch or
                        trigger_branch.endswith("*") and branch.startswith(trigger_branch[:-1])):
                        triggered[name] = task
    return triggered


def get_run_jobs(event):
    import jobs
    paths = jobs.get_paths(revish="%s..%s" % (event["before"],
                                              event["after"]))
    return jobs.get_jobs(paths)


def filter_schedule_if(event, tasks):
    scheduled = {}
    run_jobs = None
    for name, task in iteritems(tasks):
        if "schedule-if" in task:
            if "run-job" in task["schedule-if"]:
                if run_jobs is None:
                    run_jobs = get_run_jobs(event)
                if any(item in run_jobs for item in task["schedule-if"]):
                    scheduled[name] = task
        else:
            scheduled[name] = task
    return scheduled


def get_fetch_rev(event):
    is_pr, _ = get_triggers(event)
    if is_pr:
        return event["pull_request"]["merge_commit_sha"]
    else:
        return event["after"]


def build_full_command(event, task):
    cmd_args = {
        "task_name": task["name"],
        "repo_url": event["repository"]["url"],
        "fetch_rev": get_fetch_rev(event),
        "task_cmd": task["command"],
        "install_str": "",
    }

    options = task.get("options", {})
    options_args = []
    if options.get("oom-killer"):
        options_args.append("--oom-killer")
    if options.get("xvfb"):
        options_args.append("--xvfb")
    if not options.get("hosts"):
        options_args.append("--no-hosts")
    if not options.get("hosts"):
        options_args.append("--no-hosts")
    if options.get("checkout"):
        options_args.append("--checkout=%s" % options["checkout"])
    for browser in options.get("browser", []):
        options_args.append("--browser=%s" % browser)
    if options.get("checkout"):
        options_args.append("--checkout=%s" % options["checkout"])


    cmd_args["options_str"] = "\n".join("  %s" % item for item in options_args)

    install_packages = task.get("install")
    if install_packages:
        install_items = ["apt update -qqy"]
        install_items.extend("apt install -qqy %s" % item
                             for item in install_packages)
        cmd_args["install_str"] = "\n".join("sudo %s;" % item for item in install_items)

    return ["/bin/bash",
            "--login",
            "-c",
            """
~/start.sh
  %(repo_url)s
  %(fetch_rev)s;
%(install_str)s
cd web-platform-tests;
./tools/ci/run_tc.py
  %(options_str)s
  %(task_cmd)s;
""" % cmd_args]


def create_tc_task(event, task, taskgroup_id, required_task_ids):
    command = build_full_command(event, task)
    worker_type = ("wpt-docker-worker"
                   if event["repository"]["full_name"] == 'web-platform-tests/wpt'
                   else "github-worker")
    task_id = taskcluster.slugId()
    task_data = {
        "taskGroupId": taskgroup_id,
        "created": taskcluster.fromNowJSON(""),
        "deadline": taskcluster.fromNowJSON(task["deadline"]),
        "provisionerId": task["provisionerId"],
        "workerType": worker_type,
        "priority": "lowest",
        "metadata": {
            "name": task["name"],
            "description": task.get("description", ""),
            "owner": "%s@users.noreply.github.com" % event["sender"]["login"],
            "source": event["repository"]["url"]
        },
        "payload": {
            "artifacts": task.get("artifacts"),
            "command": command,
            "image": task.get("image"),
            "maxRunTime": task.get("maxRunTime"),
            "env": task.get("env", []),
        },
        "extra": {
            "github_event": json.dumps(event)
        }
    }
    if required_task_ids:
        task_data["dependencies"] = required_task_ids
        task_data["requires"] = "all-completed"
    return task_id, task_data


def build_task_graph(event, all_tasks, tasks):
    task_id_map = OrderedDict()
    taskgroup_id = os.environ.get("TASK_ID", taskcluster.slugId())

    def add_task(task_name, task):
        required_ids = []
        if "require" in task:
            for required_name in task["require"]:
                if required_name not in task_id_map:
                    add_task(required_name,
                             all_tasks[required_name])
                required_ids.append(task_id_map[required_name][0])
        task_id, task_data = create_tc_task(event, task, taskgroup_id, required_ids)
        task_id_map[task_name] = (task_id, task_data)

    for task_name, task in iteritems(tasks):
        add_task(task_name, task)

    return task_id_map


def create_tasks(queue, task_id_map):
    for (task_id, task_data) in itervalues(task_id_map):
        queue.createTask(task_id, task_data)


def get_event(**kwargs):
    if "event_path" in kwargs:
        with open(kwargs["event_path"]) as f:
            event_str = f.read()
    elif "TASK_EVENT" in os.environ:
        event_str = os.environ["TASK_EVENT"]
    else:
        event_str = fetch_event_data()
    if not event_str:
        raise ValueError("Can't find GitHub event definition; for local testing pass --event-path")
    return json.loads(event_str)


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path",
                        help="Path to file containing serialized GitHub event")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't actually create the tasks, just output the tasks that "
                        "would be created")
    return parser


def run(venv, **kwargs):
    queue = taskcluster.Queue({'rootUrl': TC_ROOT})

    event = get_event(**kwargs)

    all_tasks = taskgraph.load_tasks_from_path(os.path.join(here, "tasks/test.yml"))

    triggered_tasks = filter_triggers(event, all_tasks)
    scheduled_tasks = filter_schedule_if(event, triggered_tasks)

    task_id_map = build_task_graph(event, all_tasks, scheduled_tasks)

    if not kwargs["dry_run"]:
        create_tasks(queue, task_id_map)
    else:
        print(json.dumps(task_id_map, indent=2))
