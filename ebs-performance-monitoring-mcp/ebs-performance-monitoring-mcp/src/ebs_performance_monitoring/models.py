"""Data Model Definitions

Defines dataclasses used for EBS CloudWatch metric calculations.

Features:
- IOPS average, maximum, minimum value calculation
- Throughput calculation
- Snapshot size query
- Advanced metric calculation
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class MetricDataPoint:
    """Single data point of CloudWatch metric
    
    Attributes:
        timestamp: Timestamp of the data point
        value: Metric value
        unit: Metric unit (e.g., Count, Bytes, Seconds)
    """
    timestamp: datetime
    value: float
    unit: str


@dataclass
class MetricResult:
    """CloudWatch metric query result
    
    Attributes:
        metric_name: CloudWatch metric name
        volume_id: EBS volume ID
        datapoints: List of data points
        average: Average value (optional)
        maximum: Maximum value (optional)
        minimum: Minimum value (optional)
        sum: Sum total (optional)
    """
    metric_name: str
    volume_id: str
    datapoints: list[MetricDataPoint]
    average: Optional[float] = None
    maximum: Optional[float] = None
    minimum: Optional[float] = None
    sum: Optional[float] = None


@dataclass
class SnapshotInfo:
    """EBS Snapshot Information
    
    Attributes:
        snapshot_id: Snapshot ID
        volume_id: Source volume ID
        size_gb: Snapshot size in GB
        start_time: Snapshot creation start time
        state: Snapshot state (pending, completed, error)
        description: Snapshot description (optional)
    """
    snapshot_id: str
    volume_id: str
    size_gb: int
    start_time: datetime
    state: str
    description: Optional[str] = None


@dataclass
class PerformanceSummary:
    """Volume Performance Summary
    
    Summarizes actual usage compared to provisioned performance.
    
    Attributes:
        volume_id: EBS volume ID
        volume_type: Volume type
        size_gb: Volume size in GB
        period_hours: Analysis period in hours
        
        # Provisioned performance
        provisioned_iops: Provisioned IOPS
        provisioned_throughput_mib_s: Provisioned throughput in MiB/s
        
        # Average performance
        avg_read_iops: Average read IOPS
        avg_write_iops: Average write IOPS
        avg_total_iops: Average total IOPS
        avg_read_throughput_mib_s: Average read throughput in MiB/s
        avg_write_throughput_mib_s: Average write throughput in MiB/s
        avg_total_throughput_mib_s: Average total throughput in MiB/s
        
        # Bursting performance
        bursting_read_iops: Bursting read IOPS
        bursting_write_iops: Bursting write IOPS
        bursting_total_iops: Bursting total IOPS
        bursting_read_throughput_mib_s: Bursting read throughput in MiB/s
        bursting_write_throughput_mib_s: Bursting write throughput in MiB/s
        bursting_total_throughput_mib_s: Bursting total throughput in MiB/s
        
        # Latency
        avg_read_latency_ms: Average read latency in ms
        avg_write_latency_ms: Average write latency in ms
        
        # Workload
        total_read_ops: Total read operations
        total_write_ops: Total write operations
        total_read_bytes: Total read bytes
        total_write_bytes: Total write bytes
        
        # Utilization
        io_utilization_percent: I/O utilization percentage
        iops_utilization_percent: IOPS utilization (% of provisioned)
        throughput_utilization_percent: Throughput utilization (% of provisioned)
        
        # Burst balance (gp2 only)
        burst_balance: Burst balance percentage
    """
    volume_id: str
    volume_type: str
    size_gb: int
    period_hours: float
    
    # Provisioned performance
    provisioned_iops: int
    provisioned_throughput_mib_s: float
    
    # Average performance
    avg_read_iops: float
    avg_write_iops: float
    avg_total_iops: float
    avg_read_throughput_mib_s: float
    avg_write_throughput_mib_s: float
    avg_total_throughput_mib_s: float
    
    # Bursting performance
    bursting_read_iops: float
    bursting_write_iops: float
    bursting_total_iops: float
    bursting_read_throughput_mib_s: float
    bursting_write_throughput_mib_s: float
    bursting_total_throughput_mib_s: float
    
    # Latency
    avg_read_latency_ms: float
    avg_write_latency_ms: float
    
    # Workload
    total_read_ops: int
    total_write_ops: int
    total_read_bytes: int
    total_write_bytes: int
    
    # Utilization
    io_utilization_percent: float
    iops_utilization_percent: float
    throughput_utilization_percent: float
    
    # Burst balance
    burst_balance: Optional[float] = None


@dataclass
class MultiVolumeResult:
    """Multi-Volume Analysis Result
    
    Attributes:
        volumes: List of per-volume performance summaries
        total_volumes: Total number of volumes
        analysis_period_hours: Analysis period in hours
        summary: Overall summary statistics
    """
    volumes: list[PerformanceSummary]
    total_volumes: int
    analysis_period_hours: float
    summary: dict
