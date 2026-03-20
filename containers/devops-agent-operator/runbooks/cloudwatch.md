# Title
---

EKS Pod Failure Investigation - CloudWatch Logs Data Priority

# Description
---

Runbook for investigating EKS Pod failures when CloudWatch Logs is configured as the data store. Pre-collected diagnostic data is stored as structured JSON events in CloudWatch Logs. ALWAYS use CloudWatch Logs data as the primary source. The Log Group and Log Stream are provided in the incident context. Do NOT use kubectl or EKS access until CloudWatch data has been fully analyzed.

# Content
---

# EKS Pod Failure Investigation Runbook (CloudWatch Logs)

## CRITICAL: Data Source Priority

**CloudWatch Logs collected data is the PRIMARY and PREFERRED source for investigation.**

### Why CloudWatch Data First?
- CloudWatch contains point-in-time snapshot captured at failure moment
- Pod may have been restarted, rescheduled, or deleted since failure
- Node logs (dmesg, kubelet, containerd) are NOT accessible via kubectl
- Previous container logs may be lost after restart
- CloudWatch data is immutable and queryable via Insights

### Investigation Order (MANDATORY)
1. **FIRST**: Query CloudWatch Logs using the Log Group and Log Stream from incident context
2. **SECOND**: Only use kubectl/EKS access if CloudWatch data is insufficient or missing

---

## Step 1: Locate CloudWatch Log Stream

The incident context contains the **Log Group** and **Log Stream**. Use them directly.

### Log Stream Structure
```
incidents/<timestamp>/<namespace>/<pod-name>
```

Example:
```
Log Group:  cw-log-group-devops-agent-operator
Log Stream: incidents/2026-02-14T09-30-00Z/production/api-server-7b4d9f
```

### Timestamp Format
- Format: `YYYY-MM-DDTHH-MM-SSZ`
- Timezone: UTC
- Example: `2026-02-14T09-30-00Z` means February 14, 2026 at 09:30:00 UTC

---

## Step 2: Query CloudWatch Logs

**IMPORTANT: Use CloudWatch Logs Insights for all queries.** Do NOT browse log streams directly or use `get-log-events` CLI. Logs Insights provides filtering, sorting, and aggregation capabilities that are essential for efficient investigation.

### CloudWatch Logs Insights (RECOMMENDED)

Query all data for a specific incident:
```sql
filter @logStream = "incidents/2026-02-14T09-30-00Z/production/api-server-7b4d9f"
| sort @timestamp asc
```

Query summary only:
```sql
filter @logStream = "incidents/2026-02-14T09-30-00Z/production/api-server-7b4d9f"
  and type = "summary"
```

### IMPORTANT: Retry on Empty Results

CloudWatch Logs ingestion has a delay (typically a few seconds, but can be up to a few minutes). If a Logs Insights query returns no results:

1. **Wait 30 seconds** and retry the same query
2. If still empty, **wait 1-2 minutes** and retry again
3. After 3 failed attempts, verify the Log Stream name is correct by broadening the filter:
   ```sql
   filter @logStream like /<pod-name>/
   | sort @timestamp desc
   | limit 10
   ```
4. Only after retries are exhausted, fall back to other investigation methods

---

## Step 3: Understand Event Structure

Each incident Log Stream contains structured JSON events in order:

| Order | Event Type | `type` Field | Contains |
|-------|-----------|--------------|----------|
| 1 | Summary | `summary` | incidentId, failure info, pod metadata, node info, events |
| 2 | Pod Manifest | `pod-manifest` | Full Pod spec (kubectl get pod -o yaml) |
| 3 | Pod Describe | `pod-describe` | Pod status details (kubectl describe pod) |
| 4~N | Container Logs | `container-log` | Container stdout/stderr (current and previous) |
| N+1~ | Node Logs | `node-log` | SSM-collected system logs |

### Event JSON Examples

**Summary event:**
```json
{
  "type": "summary",
  "incidentId": "2026-02-14T09-30-00Z/production/api-server-7b4d9f",
  "failure": {"type": "OOMKilled", "container": "app", "exitCode": 137},
  "pod": {"name": "api-server-7b4d9f", "namespace": "production", "nodeName": "ip-10-0-1-50"},
  "node": {"name": "ip-10-0-1-50", "instanceId": "i-0abc123"},
  "events": [...]
}
```

**Container log event:**
```json
{
  "type": "container-log",
  "container": "app",
  "previous": true,
  "content": "2026-02-14 09:29:55 ERROR: Out of memory..."
}
```

**Node log event:**
```json
{
  "type": "node-log",
  "source": "dmesg",
  "content": "[ 1234.567890] Out of memory: Killed process 12345 (app)..."  
}
```

### Large Events (Split)

Events exceeding 256KB are automatically split with `part`/`totalParts` fields:
```json
{"type": "container-log", "container": "app", "previous": false, "part": 1, "totalParts": 3, "content": "..."}
{"type": "container-log", "container": "app", "previous": false, "part": 2, "totalParts": 3, "content": "..."}
{"type": "container-log", "container": "app", "previous": false, "part": 3, "totalParts": 3, "content": "..."}
```

Reassemble with Insights:
```sql
filter @logStream = "incidents/2026-02-14T09-30-00Z/production/api-server-7b4d9f"
  and type = "container-log" and container = "app" and previous = 0
| sort part asc
```

---

## Step 4: Analyze by Failure Type

### For OOMKilled:
1. Query `type = "summary"` - Confirm failure type and exit code (137)
2. Query `type = "node-log" and source = "dmesg"` - Search for "Out of memory", "oom-kill", "Killed process"
3. Query `type = "pod-manifest"` - Check resource limits and requests
4. Query `type = "node-log" and source = "mem-usage"` - Check node memory pressure

```sql
filter @logStream = "incidents/<incident-id>"
  and type = "node-log" and source = "dmesg"
```

### For CrashLoopBackOff:
1. Query `type = "container-log" and previous = 1` - Logs before crash (CRITICAL)
2. Query `type = "container-log" and previous = 0` - Current container logs
3. Query `type = "pod-describe"` - Exit codes, restart count, events
4. Query `type = "node-log" and source = "containerd"` - Container runtime errors

```sql
filter @logStream = "incidents/<incident-id>"
  and type = "container-log" and previous = 1
```

### For CreateContainerConfigError:
1. Query `type = "summary"` - Confirm failure type and container name
2. Query `type = "pod-describe"` - Look for Secret/ConfigMap reference errors
3. Query `type = "pod-manifest"` - Verify Secret/ConfigMap references exist
4. Query `type = "container-log" and previous = 0` - Container creation error messages

### For DeadlineExceeded:
1. Query `type = "summary"` - Confirm failure type and Job timeout
2. Query `type = "pod-describe"` - Job activeDeadlineSeconds setting
3. Query `type = "container-log" and previous = 0` - Application logs before timeout
4. Query `type = "node-log" and source = "kubelet"` - Pod termination signals

### For ContainerCreatingTimeout:
1. Query `type = "summary"` - Confirm timeout-based detection
2. Query `type = "pod-describe"` - Image pull progress and events
3. Query `type = "node-log" and source = "containerd"` - Image pull errors or delays
4. Query `type = "node-log" and source = "kubelet"` - Container creation attempts

### For UnschedulableTimeout (IP Exhaustion):
1. Query `type = "summary"` - Confirm timeout-based detection
2. Query `type = "pod-describe"` - Scheduling failure reasons and events
3. Query `type = "node-log" and source = "ipamd"` - VPC CNI IP allocation failures
4. Query `type = "node-log" and source = "kubelet"` - Pod scheduling attempts
5. Look for "failed to assign an IP address" in Events

### For Error/Failed:
1. Query `type = "summary"` - Check exit code and reason
2. Query `type = "container-log" and previous = 0` - Application error logs
3. Query `type = "pod-describe"` - Pod events and conditions

---

## Step 5: Infrastructure Analysis (CloudWatch Only)

These logs are ONLY available in CloudWatch, NOT via kubectl:

| Event Filter | Information | kubectl Equivalent |
|-------------|-------------|-------------------|
| `type = "node-log" and source = "dmesg"` | OOM killer, kernel errors | NOT AVAILABLE |
| `type = "node-log" and source = "kubelet"` | Pod lifecycle, image pull | NOT AVAILABLE |
| `type = "node-log" and source = "containerd"` | Container runtime | NOT AVAILABLE |
| `type = "node-log" and source = "ipamd"` | VPC CNI, network issues | NOT AVAILABLE |
| `type = "node-log" and source = "disk-usage"` | Node disk status | NOT AVAILABLE |
| `type = "node-log" and source = "mem-usage"` | Node memory status | NOT AVAILABLE |
| `type = "container-log" and previous = 1` | Pre-crash logs | May be lost after restart |

---

## Step 6: When to Use kubectl/EKS Access

Only use kubectl or EKS access when:
- CloudWatch Log Stream is not provided in the incident
- CloudWatch events are missing or incomplete
- You need to check CURRENT state (not failure-time state)
- You need to check related resources not in CloudWatch (Services, ConfigMaps, Secrets)

**Remember**: kubectl shows CURRENT state, CloudWatch shows FAILURE-TIME state. For root cause analysis, failure-time state is more valuable.

---

## Useful CloudWatch Logs Insights Queries

### Get all node-log events for an incident
```sql
filter @logStream = "incidents/<incident-id>"
  and type = "node-log"
| sort @timestamp asc
```

### Find all OOMKilled incidents
```sql
filter type = "summary"
| filter failure.type = "OOMKilled"
| sort @timestamp desc
| limit 20
```

### Find all incidents in a namespace
```sql
filter type = "summary"
| filter pod.namespace = "production"
| sort @timestamp desc
| limit 20
```

### Find incidents by pod name pattern
```sql
filter type = "summary"
| filter pod.name like /api-server/
| sort @timestamp desc
```

---

## Data Priority Quick Reference

Analyze in the following order:

| Order | Event Type | Insights Filter |
|-------|-----------|----------------|
| 1 | summary | `type = "summary"` |
| 2 | container-log (previous) | `type = "container-log" and previous = 1` |
| 3 | container-log (current) | `type = "container-log" and previous = 0` |
| 4 | pod-manifest | `type = "pod-manifest"` |
| 5 | pod-describe | `type = "pod-describe"` |
| 6 | node-log (kubelet) | `type = "node-log" and source = "kubelet"` |
| 7 | node-log (dmesg) | `type = "node-log" and source = "dmesg"` |
| 8 | node-log (containerd) | `type = "node-log" and source = "containerd"` |
| 9 | node-log (ipamd) | `type = "node-log" and source = "ipamd"` |
| 10 | node-log (disk-usage) | `type = "node-log" and source = "disk-usage"` |
| 11 | node-log (mem-usage) | `type = "node-log" and source = "mem-usage"` |

---

## Quick Start Checklist

1. [ ] Get Log Group and Log Stream from incident context
2. [ ] Query `type = "summary"` event for failure overview
3. [ ] Check failure type (OOMKilled, CrashLoopBackOff, Error, etc.)
4. [ ] Follow failure-type-specific analysis steps above
5. [ ] Query node logs if infrastructure issue is suspected
6. [ ] Only use kubectl if CloudWatch data is missing or need current state
