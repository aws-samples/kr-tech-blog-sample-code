# EBS Performance Monitoring MCP Server

## Overview

Monitoring and analyzing Amazon EBS volume performance is a critical challenge in cloud infrastructure operations. While AWS CloudWatch provides various EBS metrics, obtaining actionable insights requires complex calculations and multiple API calls.

This project provides an EBS Performance Monitoring MCP Server built using the Model Context Protocol (MCP). Integrated with AI agents, it enables EBS volume performance analysis through intuitive natural language commands instead of complex CloudWatch queries or AWS CLI commands.

Key capabilities that enhance EBS operational efficiency:
- **Comprehensive Performance Analysis**: Analyze IOPS, throughput, latency, and utilization in one request
- **Bursting Performance Calculation**: Measure actual bursting performance based on active time
- **Snapshot Actual Size Calculation**: Accurate data size calculation using EBS Direct API
- **Multi-Volume Parallel Analysis**: Analyze and compare multiple volumes simultaneously

---

## Business Background and Customer Needs

### Limitations of Traditional EBS Monitoring

#### 1. Complexity of CloudWatch Metrics Interpretation
AWS CloudWatch provides various metrics for EBS volumes, but practical performance analysis requires additional work:
- **Multiple Metric Combination**: Query IOPS, throughput, and latency separately, then calculate manually
- **Bursting Performance Calculation**: Requires active time-based performance calculation using VolumeIdleTime
- **Utilization Calculation**: Manual calculation of actual usage ratio against provisioned performance

#### 2. Difficulty in Determining Snapshot Size
EBS snapshots are stored incrementally, making it difficult to determine actual data size:
- **Volume Size ≠ Snapshot Size**: A 100GB volume snapshot may actually use only 10GB
- **Cost Prediction Difficulty**: Cannot predict snapshot costs without knowing actual stored data size
- **EBS Direct API Required**: Separate API calls needed to query actual block count

### Key Scenarios Requiring EBS Performance Monitoring

- **Performance Bottleneck Diagnosis**: Verify if EBS is the cause when application latency occurs
- **Capacity Planning**: Decide on volume type changes or size adjustments based on current utilization
- **Cost Optimization**: Identify over-provisioned volumes and downsize
- **Snapshot Management**: Establish snapshot retention policies based on actual data size

---

## Solution Architecture

```
┌─────────────────┐     ┌─────────────────────────────────────┐
│   AI Client     │     │     EBS Performance Monitoring      │
│  (Kiro, Claude) │────▶│           MCP Server                │
└─────────────────┘     └─────────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
            │  CloudWatch   │   │    EC2 API    │   │ EBS Direct API│
            │     API       │   │               │   │               │
            └───────────────┘   └───────────────┘   └───────────────┘
                    │                   │                   │
                    ▼                   ▼                   ▼
            ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
            │ Metrics       │   │ Volume Config │   │ Snapshot Block│
            │ Collection    │   │ Query         │   │ Size Calc     │
            │ IOPS/Thru     │   │ Type/Size/IOPS│   │               │
            └───────────────┘   └───────────────┘   └───────────────┘
```

### Module Structure

```
ebs-performance-monitoring-mcp/
├── src/ebs_performance_monitoring/
│   ├── server.py              # FastMCP server (5 tools)
│   ├── performance_analyzer.py # Performance analysis logic
│   ├── cloudwatch_client.py   # CloudWatch API client
│   ├── volume_client.py       # EC2 volume info query
│   ├── ec2_client.py          # EC2 instance EBS bandwidth
│   ├── snapshot_calculator.py # Snapshot size calculation
│   ├── formatting.py          # Output formatting utilities
│   └── models.py              # Data models
└── tests/
```

---

## Available Tools

| Tool | Function |
|------|----------|
| `get_volume_performance` | Single/multi-volume performance analysis (IOPS, throughput, latency, utilization) |
| `list_metrics` | EBS/snapshot supported metrics list |
| `get_info` | EBS volume/snapshot information query |
| `get_snapshot_size` | Snapshot actual block data size calculation (EBS Direct API) |
| `analyze_bottleneck` | EBS and EC2 performance bottleneck analysis |

---

## Installation and Setup

### Prerequisites

#### Required IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "ec2:DescribeSnapshots",
        "ec2:DescribeVolumes",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceTypes",
        "ebs:ListSnapshotBlocks",
        "ebs:ListChangedBlocks"
      ],
      "Resource": "*"
    }
  ]
}
```

### MCP Server Configuration

`.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "ebs-performance-monitoring": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/ebs-performance-monitoring-mcp",
        "ebs-performance-monitoring"
      ],
      "env": {
        "AWS_PROFILE": "default",
        "AWS_REGION": "ap-northeast-2"
      }
    }
  }
}
```

---

## Core Implementation

### FastMCP-Based Server Setup

FastMCP uses a decorator-based tool registration approach that automatically converts functions into MCP tools callable by AI clients.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ebs-performance-monitoring")

@mcp.tool()
async def get_volume_performance(
    volume_ids: list[str],
    hours: int = 24,
    region: Optional[str] = None
) -> str:
    """Analyzes EBS volume performance."""
    analyzer = PerformanceAnalyzer(region=region)
    # ...
```

### Bursting Performance Calculation Algorithm

To measure actual bursting performance of EBS volumes, VolumeIdleTime is utilized. IOPS and throughput are calculated based on active time rather than total time to understand actual workload characteristics.

```python
# Active time = Total time - Idle time
active_time = total_seconds - idle_time

if active_time > 0:
    # Bursting IOPS based on active time
    bursting_read_iops = read_ops / active_time
    bursting_write_iops = write_ops / active_time
    
    # Bursting throughput based on active time
    bursting_read_throughput = (read_bytes / active_time) / BYTES_PER_MIB
    bursting_write_throughput = (write_bytes / active_time) / BYTES_PER_MIB
```

### Snapshot Actual Size Calculation

The EBS Direct API is used to query the actual number of data blocks stored in a snapshot. This allows accurate determination of actual used data size rather than volume size.

```python
# Query all blocks (ListSnapshotBlocks)
while True:
    response = ebs_client.list_snapshot_blocks(
        SnapshotId=snapshot_id,
        MaxResults=10000
    )
    total_blocks += len(response.get("Blocks", []))
    block_size = response.get("BlockSize", 512 * 1024)  # 512 KiB
    
    next_token = response.get("NextToken")
    if not next_token:
        break

# Calculate actual data size
actual_size_gib = (total_blocks * block_size) / (1024 ** 3)
```

---

## Usage Examples

### Single Volume Performance Analysis

Natural language command: "Analyze the performance of volume vol-0441ced32697bae75 for the last 24 hours"

```
╔══════════════════════════════════════════════════════════╗
║          EBS Volume Performance Analysis                 ║
╚══════════════════════════════════════════════════════════╝

┌─ Volume Info ────────────────────────────────────────────┐
│  Volume ID        : vol-0441ced32697bae75                │
│  Type / Size      : gp3 / 100 GB                         │
│  Analysis Period  : 24 hours                             │
└──────────────────────────────────────────────────────────┘

┌─ Average Performance ────────────────────────────────────┐
│  Read IOPS        : 125.50                               │
│  Write IOPS       : 89.25                                │
│  Total IOPS       : 214.75                               │
│                                                          │
│  Read Throughput  : 15.234 MiB/s                         │
│  Write Throughput : 8.567 MiB/s                          │
│  Total Throughput : 23.801 MiB/s                         │
└──────────────────────────────────────────────────────────┘

┌─ Bursting Performance (Active Time) ─────────────────────┐
│  Total IOPS       : 1,250.00                             │
│  Total Throughput : 156.789 MiB/s                        │
└──────────────────────────────────────────────────────────┘

┌─ Utilization ────────────────────────────────────────────┐
│  I/O Utilization  : 17.18 %                              │
│  IOPS Utilization : 7.16 %                               │
│  Thru Utilization : 19.04 %                              │
└──────────────────────────────────────────────────────────┘
```

### Snapshot Actual Size Calculation

Natural language command: "Calculate the actual data size of snapshot snap-0d13f2453df86e8de"

```
╔══════════════════════════════════════════════════════════╗
║              Snapshot Size Analysis                      ║
╚══════════════════════════════════════════════════════════╝

┌─ Snapshot Info ──────────────────────────────────────────┐
│  Snapshot ID     : snap-0d13f2453df86e8de                │
│  Volume ID       : vol-0441ced32697bae75                 │
│  State           : completed                             │
└──────────────────────────────────────────────────────────┘

┌─ Size Details ───────────────────────────────────────────┐
│  Volume Size     : 100 GB                                │
│  Block Size      : 512 KiB                               │
│  Total Blocks    : 45,678                                │
│                                                          │
│  Actual Data     : 22.304 GiB                            │
│  Usage           : 22.3 % of volume                      │
└──────────────────────────────────────────────────────────┘
```

### Multi-Volume Comparison Analysis

Natural language command: "Compare the performance of these 3 volumes: vol-111, vol-222, vol-333"

```
╔══════════════════════════════════════════════════════════╗
║        EBS Multi-Volume Performance Analysis             ║
╚══════════════════════════════════════════════════════════╝

  Analysis Period: 24 hours
  Total Volumes: 3

┌─ vol-111 ────────────────────────────────────────────────┐
│  Type / Size      : gp3 / 100 GB                         │
│  Avg IOPS         : 214.75                               │
│  Avg Throughput   : 23.801 MiB/s                         │
│  IOPS Util        : 7.16 %                               │
└──────────────────────────────────────────────────────────┘

┌─ vol-222 ────────────────────────────────────────────────┐
│  Type / Size      : io2 / 500 GB                         │
│  Avg IOPS         : 8,542.30                             │
│  Avg Throughput   : 245.678 MiB/s                        │
│  IOPS Util        : 42.71 %                              │
└──────────────────────────────────────────────────────────┘

┌─ vol-333 ────────────────────────────────────────────────┐
│  Type / Size      : gp2 / 50 GB                          │
│  Avg IOPS         : 45.20                                │
│  Avg Throughput   : 5.234 MiB/s                          │
│  IOPS Util        : 30.13 %                              │
└──────────────────────────────────────────────────────────┘
```

### EBS & EC2 Bottleneck Analysis

Natural language command: "Analyze the bottleneck between EBS and EC2 for volume vol-0441ced32697bae75"

```
╔══════════════════════════════════════════════════════════╗
║          EBS & EC2 Bottleneck Analysis                   ║
╚══════════════════════════════════════════════════════════╝

┌─ EC2 Instance Info ──────────────────────────────────────┐
│  Instance ID      : i-0123456789abcdef0                  │
│  Instance Type    : m5.xlarge                            │
│  EBS Optimized    : Yes                                  │
└──────────────────────────────────────────────────────────┘

┌─ EC2 EBS Bandwidth ──────────────────────────────────────┐
│  Baseline IOPS    : 6,000                                │
│  Maximum IOPS     : 10,000                               │
│  Baseline Thru    : 143.75 MiB/s                         │
│  Maximum Thru     : 593.75 MiB/s                         │
└──────────────────────────────────────────────────────────┘

┌─ Bottleneck Analysis ────────────────────────────────────┐
│  Effective IOPS   : 3,000 (Limited by EBS)               │
│  Effective Thru   : 125.00 MiB/s (Limited by EBS)        │
│                                                          │
│  ✓ Sufficient performance headroom                       │
└──────────────────────────────────────────────────────────┘
```

---

## Advanced Usage Scenarios

- **Performance Bottleneck Diagnosis**: "Check if this volume has high latency, and let me know if IOPS utilization is close to 100%"
- **Cost Optimization Analysis**: "Find volumes with IOPS utilization below 10% and analyze if they can be downgraded to gp2"
- **Snapshot Cleanup**: "Calculate the actual size of all snapshots for this volume and sort by largest"
- **Capacity Planning**: "Look at the IOPS utilization trend over the last 7 days and determine if a volume upgrade is needed"

---

## Conclusion

This solution enables comprehensive EBS performance analysis through natural language commands without complex CloudWatch queries and manual calculations. The bursting performance calculation and snapshot actual size calculation features provide information that is difficult to obtain directly from the AWS console.

This MCP-based approach dramatically simplifies infrastructure operations and enables complex analysis tasks through natural conversation with AI agents.

---

## License

MIT License
