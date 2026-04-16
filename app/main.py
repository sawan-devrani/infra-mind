import os
from flask import Flask, jsonify
from kubernetes import client, config
from anthropic import Anthropic

app = Flask(__name__)
anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def get_cluster_state():
    config.load_incluster_config()  # runs inside the cluster
    v1 = client.CoreV1Api()

    # Fetch pods across all namespaces
    pods = v1.list_pod_for_all_namespaces()
    pod_states = []
    for pod in pods.items:
        pod_states.append({
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": pod.status.phase,
            "conditions": [
                {"type": c.type, "status": c.status, "reason": c.reason}
                for c in (pod.status.conditions or [])
            ]
        })

    # Fetch warning events
    events = v1.list_event_for_all_namespaces(field_selector="type=Warning")
    warning_events = [
        {
            "namespace": e.metadata.namespace,
            "name": e.involved_object.name,
            "reason": e.reason,
            "message": e.message,
            "count": e.count
        }
        for e in events.items
    ]

    return pod_states, warning_events


def summarize_with_claude(pod_states, warning_events):
    unhealthy_pods = [p for p in pod_states if p["phase"] not in ("Running", "Succeeded")]

    prompt = f"""You are an SRE assistant analyzing a Kubernetes cluster.

Here is the current cluster state:

UNHEALTHY PODS ({len(unhealthy_pods)} of {len(pod_states)} total):
{unhealthy_pods}

WARNING EVENTS (last {len(warning_events)}):
{warning_events}

Please provide:
1. A short executive summary (2-3 sentences) of cluster health
2. Top issues ranked by severity with likely root cause
3. Recommended immediate actions for each issue
Be concise and actionable."""

    message = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/summarize")
def summarize():
    pod_states, warning_events = get_cluster_state()
    summary = summarize_with_claude(pod_states, warning_events)
    return jsonify({
        "total_pods": len(pod_states),
        "warning_events": len(warning_events),
        "summary": summary
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
