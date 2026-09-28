# Title
---

EKS Pod Failure Investigation - S3 Data Priority

# Description
---

Runbook for investigating EKS Pod failures. Pre-collected diagnostic data in S3 contains all necessary information. ALWAYS use S3 data as the primary source. The S3 path is provided in the incident context - use it DIRECTLY without listing or searching. Do NOT use kubectl or EKS access until S3 data has been fully analyzed.

## MCP Tools for S3 Access

**CRITICAL: Use MCP tools to access S3 data. Do NOT use AWS CLI or kubectl for S3 access.**

### Available Tools

1. **`get_collected_data`** - Get complete incident data (START HERE)
   - Input: `incident_id` (format: `timestamp/namespace/pod_name`)
   - Returns: Complete JSON with all diagnostic data
   - Example: `2026-02-10T08-03-58Z/default/crashloop-test`

2. **`get_incident_file`** - Get specific file from incident
   - Input: `path` (format: `timestamp/namespace/pod_name/filename`)
   - Returns: File content
   - Example: `2026-02-10T08-03-58Z/default/crashloop-test/failure-info.json`

3. **`list_incident_files`** - List all available files
   - Input: `timestamp`, `namespace`, `pod_name`
   - Returns: Array of filenames
   - Use only if you need to see what files exist

### Quick Start

1. Extract `incident_id` from webhook context
2. Call `get_collected_data` with the `incident_id`
3. Analyze the complete JSON response
4. Use `get_incident_file` only if you need specific raw files

### Example incident_id Extraction

From webhook context:
```
s3://bucket/incidents/2026-02-10T08-03-58Z/default/crashloop-test/
```

Extract as incident_id:
```
2026-02-10T08-03-58Z/default/crashloop-test
```

# Content
---

# EKS Pod Failure Investigation Runbook

## CRITICAL: Data Source Priority

**S3 collected data is the PRIMARY and PREFERRED source for investigation.**

### Why S3 Data First?
- S3 contains point-in-time snapshot captured at failure moment
- Pod may have been restarted, rescheduled, or deleted since failure
- Node logs (dmesg, kubelet, containerd) are NOT accessible via kubectl
- Previous container logs may be lost after restart
- S3 data is complete and immutable

### Investigation Order (MANDATORY)
1. **FIRST**: Read S3 collected data using MCP tools with the incident_id from context
2. **SECOND**: Only use kubectl/EKS access if S3 data is insufficient or missing

---

## Step 1: Access S3 Data via MCP

Use the `get_collected_data` MCP tool with the incident_id from the webhook context.

### Incident ID Format
```
timestamp/namespace/pod_name
```

Example:
```
2026-02-10T08-03-58Z/default/crashloop-test
```

### Timestamp Format
- Format: `YYYY-MM-DDTHH-MM-SSZ`
- Timezone: UTC
- Example: `2026-02-10T08-03-58Z` means February 10, 2026 at 08:03:58 UTC

---

## Step 2: Analyze collected-data.json

The `get_collected_data` tool returns a complete JSON containing ALL diagnostic data:
- Pod manifest and describe output
- Container logs (current and previous)
- Node logs (kubelet, containerd, dmesg)
- Failure information

---

## Step 3: Analyze by Failure Type

### For OOMKilled:
1. Check `failureInfo` - Confirm failure type and exit code (137)
2. Search `nodeLogs.dmesg` - Look for "Out of memory", "oom-kill", "Killed process"
3. Check `podManifest` - Verify resource limits and requests
4. Check `nodeLogs.memUsage` - Check node memory pressure

### For CrashLoopBackOff:
1. Check `logs.previous` - Logs before crash (CRITICAL - not available via kubectl after restart)
2. Check `logs.current` - Current container logs
3. Check `podDescribe` - Exit codes, restart count, events
4. Check `nodeLogs.containerd` - Container runtime errors

### For CreateContainerConfigError:
1. Check `failureInfo` - Confirm failure type and container name
2. Check `podDescribe` - Look for Secret/ConfigMap reference errors
3. Check `podManifest` - Verify Secret/ConfigMap references exist
4. Check `logs.current` - Container creation error messages

### For DeadlineExceeded:
1. Check `failureInfo` - Confirm failure type and Job timeout
2. Check `podDescribe` - Job activeDeadlineSeconds setting
3. Check `logs.current` - Application logs before timeout
4. Check `nodeLogs.kubelet` - Pod termination signals

### For ContainerCreatingTimeout:
1. Check `failureInfo` - Confirm timeout-based detection
2. Check `podDescribe` - Image pull progress and events
3. Check `nodeLogs.containerd` - Image pull errors or delays
4. Check `nodeLogs.kubelet` - Container creation attempts

### For UnschedulableTimeout (IP Exhaustion):
1. Check `failureInfo` - Confirm timeout-based detection
2. Check `podDescribe` - Scheduling failure reasons and events
3. Check `nodeLogs.ipamd` - VPC CNI IP allocation failures
4. Check `nodeLogs.kubelet` - Pod scheduling attempts
5. Look for "failed to assign an IP address" in Events

### For Error/Failed:
1. Check `failureInfo` - Exit code and reason
2. Check `logs.current` - Application error logs
3. Check `podDescribe` - Pod events and conditions

---

## Step 4: Infrastructure Analysis (S3 Only)

These logs are ONLY available in S3, NOT via kubectl:

| Data Field | Information | kubectl Equivalent |
|------------|-------------|-------------------|
| nodeLogs.dmesg | OOM killer, kernel errors | NOT AVAILABLE |
| nodeLogs.kubelet | Pod lifecycle, image pull | NOT AVAILABLE |
| nodeLogs.containerd | Container runtime | NOT AVAILABLE |
| nodeLogs.ipamd | VPC CNI, network issues | NOT AVAILABLE |
| nodeLogs.diskUsage | Node disk status | NOT AVAILABLE |
| nodeLogs.memUsage | Node memory status | NOT AVAILABLE |
| logs.previous | Pre-crash logs | May be lost after restart |

---

## Step 5: When to Use kubectl/EKS Access

Only use kubectl or EKS access when:
- S3 data is not provided in the incident context
- S3 data is missing or corrupted
- You need to check CURRENT state (not failure-time state)
- You need to check related resources not in S3 (Services, ConfigMaps, Secrets)

**Remember**: kubectl shows CURRENT state, S3 shows FAILURE-TIME state. For root cause analysis, failure-time state is more valuable.

---

## Data Structure Quick Reference

| Field | Priority | Contains |
|-------|----------|----------|
| failureInfo | HIGHEST | Failure type, container, exit code |
| logs.previous | HIGH | Pre-crash container logs |
| nodeLogs.dmesg | HIGH | OOM events, kernel errors |
| podDescribe | MEDIUM | Pod status, events, conditions |
| podManifest | MEDIUM | Full Pod spec, resource limits |
| nodeLogs.kubelet | MEDIUM | Pod lifecycle issues |
| logs.current | MEDIUM | Current container logs |

---

## Quick Start Checklist

1. [ ] Extract `incident_id` from webhook context (format: `timestamp/namespace/pod_name`)
2. [ ] Call `get_collected_data` MCP tool with the `incident_id`
3. [ ] Check `failureInfo` for failure type
4. [ ] Follow failure-type-specific analysis steps above
5. [ ] Only use kubectl if S3 data is missing or need current state
