"""FastMCP-based MCP Server

AWS EBS Performance Monitoring MCP Server.
Provides 5 integrated tools:
- get_volume_performance: Single/multi-volume performance analysis
- list_metrics: EBS/snapshot supported metrics list
- get_info: EBS volume/snapshot information query
- get_snapshot_size: Snapshot block data size calculation
- analyze_bottleneck: EBS and EC2 bottleneck analysis
"""

import logging
from typing import Optional, Literal

import boto3
from botocore.exceptions import ClientError
from mcp.server.fastmcp import FastMCP

from .performance_analyzer import PerformanceAnalyzer
from .snapshot_calculator import SnapshotCalculator
from .volume_client import VolumeClient
from .ec2_client import EC2Client
from .formatting import make_header, make_section

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("ebs-performance-monitoring")


def _dataclass_to_dict(obj) -> dict:
    """Convert dataclass to dictionary"""
    if hasattr(obj, "__dict__"):
        result = {}
        for key, value in obj.__dict__.items():
            if isinstance(value, list):
                result[key] = [_dataclass_to_dict(item) for item in value]
            elif hasattr(value, "__dict__"):
                result[key] = _dataclass_to_dict(value)
            else:
                result[key] = value
        return result
    return obj


@mcp.tool()
async def get_volume_performance(
    volume_ids: list[str],
    hours: int = 24,
    region: Optional[str] = None
) -> str:
    """Analyzes EBS volume performance. Supports single or multiple volumes.
    
    Comprehensively analyzes performance metrics for the last N hours (default 24 hours).
    
    Returns:
    - Volume info (type, size, provisioned IOPS/throughput)
    - Average IOPS (read/write/total)
    - Average throughput (read/write/total, MiB/s)
    - Bursting IOPS/throughput (based on active time)
    - Latency (read/write, ms)
    - Total read/write workload
    - Utilization (I/O, IOPS, throughput - % of provisioned)
    - Burst balance (gp2 volumes)
    
    Args:
        volume_ids: List of EBS volume IDs (e.g., ["vol-1234567890abcdef0"] or ["vol-111", "vol-222"])
        hours: Analysis period in hours (default: 24)
        region: AWS region (optional)
    """
    analyzer = PerformanceAnalyzer(region=region)
    W = 58  # Internal content area width (excluding borders)
    
    if len(volume_ids) == 1:
        # Single volume analysis
        s = await analyzer.analyze_volume(volume_ids[0], hours=hours)
        
        lines = []
        
        # Header
        lines.extend(make_header("EBS Volume Performance Analysis"))
        
        # Volume Info
        lines.extend(make_section("Volume Info", [
            f"Volume ID        : {s.volume_id}",
            f"Type / Size      : {s.volume_type} / {s.size_gb} GB",
            f"Analysis Period  : {s.period_hours} hours",
        ]))
        
        # Provisioned Performance
        lines.extend(make_section("Provisioned Performance", [
            f"IOPS             : {s.provisioned_iops:,}",
            f"Throughput       : {s.provisioned_throughput_mib_s} MiB/s",
        ]))
        
        # Average Performance
        lines.extend(make_section("Average Performance", [
            f"Read IOPS        : {s.avg_read_iops:,.2f}",
            f"Write IOPS       : {s.avg_write_iops:,.2f}",
            f"Total IOPS       : {s.avg_total_iops:,.2f}",
            "",
            f"Read Throughput  : {s.avg_read_throughput_mib_s:.3f} MiB/s",
            f"Write Throughput : {s.avg_write_throughput_mib_s:.3f} MiB/s",
            f"Total Throughput : {s.avg_total_throughput_mib_s:.3f} MiB/s",
        ]))
        
        # Bursting Performance
        lines.extend(make_section("Bursting Performance (Active Time)", [
            f"Read IOPS        : {s.bursting_read_iops:,.2f}",
            f"Write IOPS       : {s.bursting_write_iops:,.2f}",
            f"Total IOPS       : {s.bursting_total_iops:,.2f}",
            "",
            f"Read Throughput  : {s.bursting_read_throughput_mib_s:.3f} MiB/s",
            f"Write Throughput : {s.bursting_write_throughput_mib_s:.3f} MiB/s",
            f"Total Throughput : {s.bursting_total_throughput_mib_s:.3f} MiB/s",
        ]))
        
        # Latency
        lines.extend(make_section("Latency", [
            f"Read Latency     : {s.avg_read_latency_ms:.3f} ms",
            f"Write Latency    : {s.avg_write_latency_ms:.3f} ms",
        ]))
        
        # Workload
        total_read_gib = round(s.total_read_bytes / (1024**3), 3)
        total_write_gib = round(s.total_write_bytes / (1024**3), 3)
        lines.extend(make_section("Workload", [
            f"Total Read Ops   : {s.total_read_ops:,}",
            f"Total Write Ops  : {s.total_write_ops:,}",
            f"Total Read       : {total_read_gib} GiB",
            f"Total Write      : {total_write_gib} GiB",
        ]))
        
        # Utilization
        util_content = [
            f"I/O Utilization  : {s.io_utilization_percent:.2f} %",
            f"IOPS Utilization : {s.iops_utilization_percent:.2f} %",
            f"Thru Utilization : {s.throughput_utilization_percent:.2f} %",
        ]
        if s.burst_balance is not None:
            util_content.append(f"Burst Balance    : {s.burst_balance:.1f} %")
        lines.extend(make_section("Utilization", util_content))
        
        return "\n".join(lines)
    else:
        # Multi-volume analysis
        multi_result = await analyzer.analyze_multiple_volumes(volume_ids, hours=hours)
        
        lines = []
        
        # Header
        lines.extend(make_header("EBS Multi-Volume Performance Analysis"))
        
        # Summary
        lines.extend(make_section("Summary", [
            f"Analysis Period  : {multi_result.analysis_period_hours} hours",
            f"Total Volumes    : {multi_result.total_volumes}",
        ]))
        
        # Each volume info
        for vol in multi_result.volumes:
            lines.extend(make_section(vol.volume_id, [
                f"Type / Size      : {vol.volume_type} / {vol.size_gb} GB",
                f"Avg IOPS         : {vol.avg_total_iops:,.2f}",
                f"Avg Throughput   : {vol.avg_total_throughput_mib_s:.3f} MiB/s",
                f"Burst IOPS       : {vol.bursting_total_iops:,.2f}",
                f"Burst Throughput : {vol.bursting_total_throughput_mib_s:.3f} MiB/s",
                f"Read Latency     : {vol.avg_read_latency_ms:.3f} ms",
                f"Write Latency    : {vol.avg_write_latency_ms:.3f} ms",
                f"IOPS Util        : {vol.iops_utilization_percent:.2f} %",
            ]))
        
        return "\n".join(lines)


@mcp.tool()
def list_metrics(
    resource_type: Literal["ebs", "snapshot", "all"] = "all"
) -> str:
    """Returns the list of supported EBS and snapshot metrics.
    
    Args:
        resource_type: Resource type to query ("ebs", "snapshot", "all", default: "all")
    """
    lines = []
    lines.extend(make_header("Supported Metrics"))
    
    if resource_type in ("ebs", "all"):
        ebs_metrics = [
            ("VolumeReadOps", "Number of read operations"),
            ("VolumeWriteOps", "Number of write operations"),
            ("VolumeReadBytes", "Bytes read"),
            ("VolumeWriteBytes", "Bytes written"),
            ("VolumeTotalReadTime", "Total read time (seconds)"),
            ("VolumeTotalWriteTime", "Total write time (seconds)"),
            ("VolumeIdleTime", "Idle time (seconds)"),
            ("VolumeQueueLength", "Pending I/O requests"),
            ("VolumeThroughputPercentage", "Throughput utilization (%)"),
            ("VolumeConsumedReadWriteOps", "Consumed IOPS (io1/io2)"),
            ("BurstBalance", "Burst credit balance (%, gp2)"),
        ]
        content = [f"{metric:<28} {desc}" for metric, desc in ebs_metrics]
        lines.extend(make_section("EBS CloudWatch Metrics (AWS/EBS)", content))
    
    if resource_type in ("snapshot", "all"):
        snap_attrs = [
            ("snapshot_id", "Snapshot ID"),
            ("volume_id", "Source volume ID"),
            ("volume_size_gb", "Volume size (GB)"),
            ("state", "State (pending/completed/error)"),
            ("start_time", "Creation start time"),
            ("block_size", "Block size (512 KiB)"),
            ("changed_blocks_count", "Changed blockcount"),
            ("actual_size_gib", "Actual data size (GiB)"),
        ]
        content = [f"{attr:<28} {desc}" for attr, desc in snap_attrs]
        lines.extend(make_section("Snapshot Attributes (EBS Direct API)", content))
    
    return "\n".join(lines)


@mcp.tool()
async def get_info(
    resource_type: Literal["volume", "snapshot"],
    resource_id: str,
    volume_id_for_snapshots: Optional[str] = None,
    max_results: int = 100,
    region: Optional[str] = None
) -> str:
    """Queries EBS volume or snapshot information.
    
    Args:
        resource_type: Resource type ("volume" or "snapshot")
        resource_id: Resource ID (volume ID or snapshot ID, enter "list" for snapshot list)
        volume_id_for_snapshots: Volume ID for snapshot list query (required when resource_id is "list")
        max_results: Maximum results for snapshot list (default: 100)
        region: AWS region (optional)
    
    Examples:
    - Volume info: resource_type="volume", resource_id="vol-xxx"
    - Snapshot info: resource_type="snapshot", resource_id="snap-xxx"
    - Volume's snapshot list: resource_type="snapshot", resource_id="list", volume_id_for_snapshots="vol-xxx"
    """
    lines = []
    
    if resource_type == "volume":
        client = VolumeClient(region=region)
        c = await client.get_volume_config(resource_id)
        
        lines.extend(make_header("EBS Volume Information"))
        
        lines.extend(make_section("Basic Info", [
            f"Volume ID        : {c.volume_id}",
            f"Type             : {c.volume_type}",
            f"Size             : {c.size_gb} GB",
            f"State            : {c.state}",
            f"AZ               : {c.availability_zone}",
            f"Encrypted        : {c.encrypted}",
            f"Multi-Attach     : {c.multi_attach_enabled}",
        ]))
        
        lines.extend(make_section("Performance", [
            f"Provisioned IOPS : {c.iops:,}",
            f"Provisioned Thru : {c.throughput_mib_s} MiB/s",
            f"Baseline IOPS    : {c.baseline_iops:,}",
            f"Baseline Thru    : {c.baseline_throughput_mib_s} MiB/s",
        ]))
        
    else:  # snapshot
        calculator = SnapshotCalculator(region=region)
        if resource_id.lower() == "list":
            if not volume_id_for_snapshots:
                return "Error: volume_id_for_snapshots is required for snapshot list query."
            snapshots = await calculator.list_volume_snapshots(
                volume_id=volume_id_for_snapshots,
                max_results=max_results
            )
            
            lines.extend(make_header("Snapshot List"))
            
            lines.extend(make_section("Summary", [
                f"Volume ID        : {volume_id_for_snapshots}",
                f"Total Snapshots  : {len(snapshots)}",
            ]))
            
            for snap in snapshots:
                lines.extend(make_section(snap.snapshot_id, [
                    f"State            : {snap.state}",
                    f"Size             : {snap.size_gb} GB",
                    f"Start Time       : {snap.start_time}",
                ]))
        else:
            snapshot = await calculator.get_snapshot_size(resource_id)
            snap_dict = _dataclass_to_dict(snapshot)
            
            lines.extend(make_header("Snapshot Information"))
            
            content = [f"{key:<16} : {value}" for key, value in snap_dict.items()]
            lines.extend(make_section("Details", content))
    
    return "\n".join(lines)


@mcp.tool()
async def get_snapshot_size(
    snapshot_id: str,
    previous_snapshot_id: Optional[str] = None,
    region: Optional[str] = None
) -> str:
    """Calculates actual block data size of a snapshot.
    
    Uses EBS Direct API (ListChangedBlocks/ListSnapshotBlocks) to calculate
    the actual number and size of data blocks stored in the snapshot.
    
    Args:
        snapshot_id: EBS snapshot ID (e.g., snap-1234567890abcdef0)
        previous_snapshot_id: Previous snapshot ID for incremental size calculation (optional)
        region: AWS region (optional)
    
    Returns:
    - Snapshot metadata (ID, volume ID, state)
    - Volume size (GB)
    - Block size (512 KiB)
    - Total blocks / changed blocks count
    - Actual data size (GiB)
    - Incremental size (compared to previous snapshot, optional)
    """
    calculator = SnapshotCalculator(region=region)
    
    # Get snapshot metadata
    try:
        snapshot_meta = await calculator.get_snapshot_size(snapshot_id)
    except ValueError as e:
        return f"Error: {str(e)}"
    
    # Create EBS Direct API client
    if region:
        ebs_client = boto3.client("ebs", region_name=region)
    else:
        ebs_client = boto3.client("ebs")
    
    # Query block data
    block_size = 512 * 1024  # 512 KiB
    total_blocks = 0
    next_token = None
    
    try:
        if previous_snapshot_id:
            # Query incremental blocks (ListChangedBlocks)
            while True:
                params = {
                    "SecondSnapshotId": snapshot_id,
                    "FirstSnapshotId": previous_snapshot_id,
                    "MaxResults": 10000
                }
                if next_token:
                    params["NextToken"] = next_token
                
                response = ebs_client.list_changed_blocks(**params)
                total_blocks += len(response.get("ChangedBlocks", []))
                next_token = response.get("NextToken")
                if not next_token:
                    break
        else:
            # Query all blocks (ListSnapshotBlocks)
            while True:
                params = {
                    "SnapshotId": snapshot_id,
                    "MaxResults": 10000
                }
                if next_token:
                    params["NextToken"] = next_token
                
                response = ebs_client.list_snapshot_blocks(**params)
                total_blocks += len(response.get("Blocks", []))
                block_size = response.get("BlockSize", block_size)
                next_token = response.get("NextToken")
                if not next_token:
                    break
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ValidationException":
            return f"Error: Failed to query snapshot blocks\nSnapshot may not be completed or access denied.\nSnapshot: {snapshot_id}, State: {snapshot_meta.state}"
        return f"Error: {str(e)}"
    
    # Calculate size
    actual_size_bytes = total_blocks * block_size
    actual_size_gib = actual_size_bytes / (1024 ** 3)
    volume_size_gb = snapshot_meta.size_gb
    usage_percent = (actual_size_gib / volume_size_gb * 100) if volume_size_gb > 0 else 0
    
    lines = []
    lines.extend(make_header("Snapshot Size Analysis"))
    
    lines.extend(make_section("Snapshot Info", [
        f"Snapshot ID      : {snapshot_id}",
        f"Volume ID        : {snapshot_meta.volume_id}",
        f"State            : {snapshot_meta.state}",
    ]))
    
    lines.extend(make_section("Size Details", [
        f"Volume Size      : {volume_size_gb} GB",
        f"Block Size       : {block_size // 1024} KiB",
        f"Total Blocks     : {total_blocks:,}",
        "",
        f"Actual Data      : {actual_size_gib:.3f} GiB",
        f"Usage            : {usage_percent:.1f} % of volume",
    ]))
    
    if previous_snapshot_id:
        lines.extend(make_section("Incremental Comparison", [
            f"Previous Snap    : {previous_snapshot_id}",
            f"Changed Blocks   : {total_blocks:,}",
            f"Incremental Size : {actual_size_gib:.3f} GiB",
        ]))
    
    return "\n".join(lines)


@mcp.tool()
async def analyze_bottleneck(
    volume_id: str,
    hours: int = 24,
    region: Optional[str] = None
) -> str:
    """Analyzes performance bottleneck between EBS volume and attached EC2 instance.
    
    Compares EBS volume provisioned performance with EC2 instance EBS dedicated bandwidth
    to identify whether the actual bottleneck is EBS or EC2.
    
    Args:
        volume_id: EBS volume ID (e.g., vol-1234567890abcdef0)
        hours: Analysis period in hours (default: 24)
        region: AWS region (optional)
    
    Returns:
    - EC2 instance info (ID, type, EBS optimized status)
    - EC2 EBS bandwidth (baseline/max IOPS, baseline/max throughput)
    - EBS volume provisioned performance
    - Actual usage and utilization
    - Bottleneck analysis result (IOPS/throughput limiting factor)
    """
    lines = []
    
    # Get EC2 instance EBS bandwidth via EC2 client
    ec2_client = EC2Client(region=region)
    ec2_bandwidth = await ec2_client.get_ebs_bandwidth_for_volume(volume_id)
    
    if not ec2_bandwidth:
        lines.extend(make_header("Bottleneck Analysis"))
        lines.extend(make_section("Error", [
            f"Volume ID        : {volume_id}",
            "",
            "⚠ Volume is not attached to an EC2 instance.",
            "  Cannot perform EC2 EBS bandwidth analysis.",
        ]))
        return "\n".join(lines)
    
    # Analyze EBS volume performance
    analyzer = PerformanceAnalyzer(region=region)
    perf = await analyzer.analyze_volume(volume_id, hours=hours)
    
    # Calculate bottleneck analysis
    ebs_iops_limit = perf.provisioned_iops
    ec2_iops_limit = ec2_bandwidth.baseline_iops
    effective_iops_limit = min(ebs_iops_limit, ec2_iops_limit)
    iops_limiting_factor = "EBS" if ebs_iops_limit <= ec2_iops_limit else "EC2"
    
    ebs_throughput_limit = perf.provisioned_throughput_mib_s
    ec2_throughput_limit = ec2_bandwidth.baseline_throughput_mib_s
    effective_throughput_limit = min(ebs_throughput_limit, ec2_throughput_limit)
    throughput_limiting_factor = "EBS" if ebs_throughput_limit <= ec2_throughput_limit else "EC2"
    
    # Calculate utilization
    ebs_iops_util = (perf.avg_total_iops / ebs_iops_limit * 100) if ebs_iops_limit > 0 else 0
    ec2_iops_util = (perf.avg_total_iops / ec2_iops_limit * 100) if ec2_iops_limit > 0 else 0
    ebs_throughput_util = (perf.avg_total_throughput_mib_s / ebs_throughput_limit * 100) if ebs_throughput_limit > 0 else 0
    ec2_throughput_util = (perf.avg_total_throughput_mib_s / ec2_throughput_limit * 100) if ec2_throughput_limit > 0 else 0
    
    # Generate output
    lines.extend(make_header("EBS & EC2 Bottleneck Analysis"))
    
    lines.extend(make_section("EC2 Instance Info", [
        f"Instance ID      : {ec2_bandwidth.instance_id}",
        f"Instance Type    : {ec2_bandwidth.instance_type}",
        f"EBS Optimized    : {'Yes' if ec2_bandwidth.ebs_optimized else 'No'}",
    ]))
    
    lines.extend(make_section("EC2 EBS Bandwidth", [
        f"Baseline IOPS    : {ec2_bandwidth.baseline_iops:,}",
        f"Maximum IOPS     : {ec2_bandwidth.maximum_iops:,}",
        f"Baseline Thru    : {ec2_bandwidth.baseline_throughput_mib_s:.2f} MiB/s",
        f"Maximum Thru     : {ec2_bandwidth.maximum_throughput_mib_s:.2f} MiB/s",
    ]))
    
    lines.extend(make_section("EBS Volume Info", [
        f"Volume ID        : {perf.volume_id}",
        f"Type / Size      : {perf.volume_type} / {perf.size_gb} GB",
        f"Provisioned IOPS : {perf.provisioned_iops:,}",
        f"Provisioned Thru : {perf.provisioned_throughput_mib_s:.2f} MiB/s",
    ]))
    
    lines.extend(make_section(f"Actual Usage (Last {hours}h)", [
        f"Avg IOPS         : {perf.avg_total_iops:,.2f}",
        f"Avg Throughput   : {perf.avg_total_throughput_mib_s:.3f} MiB/s",
        f"Burst IOPS       : {perf.bursting_total_iops:,.2f}",
        f"Burst Throughput : {perf.bursting_total_throughput_mib_s:.3f} MiB/s",
    ]))
    
    lines.extend(make_section("Utilization Comparison", [
        "                      EBS          EC2",
        f"IOPS Utilization   : {ebs_iops_util:6.2f} %     {ec2_iops_util:6.2f} %",
        f"Thru Utilization   : {ebs_throughput_util:6.2f} %     {ec2_throughput_util:6.2f} %",
    ]))
    
    # Bottleneck analysis result
    bottleneck_content = [
        f"Effective IOPS   : {effective_iops_limit:,} (Limited by {iops_limiting_factor})",
        f"Effective Thru   : {effective_throughput_limit:.2f} MiB/s (Limited by {throughput_limiting_factor})",
        "",
    ]
    
    if ebs_iops_util > 80 or ec2_iops_util > 80:
        if iops_limiting_factor == "EBS":
            bottleneck_content.append("⚠ IOPS Bottleneck: Consider increasing EBS volume IOPS")
        else:
            bottleneck_content.append("⚠ IOPS Bottleneck: Consider upgrading EC2 instance type")
    elif ebs_throughput_util > 80 or ec2_throughput_util > 80:
        if throughput_limiting_factor == "EBS":
            bottleneck_content.append("⚠ Throughput Bottleneck: Consider increasing EBS volume throughput")
        else:
            bottleneck_content.append("⚠ Throughput Bottleneck: Consider upgrading EC2 instance type")
    else:
        bottleneck_content.append("✓ Sufficient performance headroom")
    
    lines.extend(make_section("Bottleneck Analysis", bottleneck_content))
    
    return "\n".join(lines)


def main():
    """MCP server main function"""
    mcp.run()


if __name__ == "__main__":
    main()
