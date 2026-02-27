"""CloudWatch API Client

Client module for communicating with AWS CloudWatch API to retrieve EBS metric data.

Features:
- Load AWS credentials from environment variables or AWS profile
- Query metric data by metric name, volume ID, and time range
- Support for EBS metric list
- Support for statistic types (Average, Sum, Minimum, Maximum, SampleCount)
"""

import asyncio
from datetime import datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from .models import MetricDataPoint, MetricResult


# Supported EBS CloudWatch metrics
SUPPORTED_EBS_METRICS = [
    "VolumeReadOps",
    "VolumeWriteOps",
    "VolumeReadBytes",
    "VolumeWriteBytes",
    "VolumeTotalReadTime",
    "VolumeTotalWriteTime",
    "VolumeIdleTime",
    "VolumeQueueLength",
    "VolumeThroughputPercentage",
    "VolumeConsumedReadWriteOps",
    "BurstBalance",
]

# Supported statistic types
SUPPORTED_STATISTICS = [
    "Average",
    "Sum",
    "Minimum",
    "Maximum",
    "SampleCount",
]

# CloudWatch namespace
EBS_NAMESPACE = "AWS/EBS"


class CloudWatchClient:
    """AWS CloudWatch API Client
    
    Client for querying CloudWatch metrics for EBS volumes.
    
    Attributes:
        region: AWS region (uses default region if None)
        _client: boto3 CloudWatch client
    
    Example:
        >>> client = CloudWatchClient(region="us-east-1")
        >>> result = await client.get_metric_statistics(
        ...     volume_id="vol-1234567890abcdef0",
        ...     metric_name="VolumeReadOps",
        ...     start_time=datetime(2024, 1, 1),
        ...     end_time=datetime(2024, 1, 2),
        ...     period=300,
        ...     statistics=["Average", "Maximum"]
        ... )
    """
    
    def __init__(self, region: Optional[str] = None):
        """Initialize boto3 CloudWatch client
        
        Args:
            region: AWS region. Loads from environment variables or AWS profile if None
        """
        self.region = region
        if region:
            self._client = boto3.client("cloudwatch", region_name=region)
        else:
            self._client = boto3.client("cloudwatch")
    
    async def get_metric_statistics(
        self,
        volume_id: str,
        metric_name: str,
        start_time: datetime,
        end_time: datetime,
        period: int = 300,
        statistics: Optional[list[str]] = None
    ) -> MetricResult:
        """Query CloudWatch metric statistics
        
        Retrieves CloudWatch metric statistics for the specified EBS volume.
        
        Args:
            volume_id: EBS volume ID (e.g., vol-1234567890abcdef0)
            metric_name: CloudWatch metric name (e.g., VolumeReadOps)
            start_time: Query start time
            end_time: Query end time
            period: Metric collection interval in seconds (default: 300)
            statistics: List of statistic types to query (default: ["Average"])
        
        Returns:
            MetricResult: Metric query result
        
        Raises:
            ValueError: If unsupported metric name or statistic type
            ClientError: If AWS API call fails
        """
        if statistics is None:
            statistics = ["Average"]
        
        # Validate metric name
        if metric_name not in SUPPORTED_EBS_METRICS:
            raise ValueError(
                f"Unsupported metric name: {metric_name}. "
                f"Supported metrics: {', '.join(SUPPORTED_EBS_METRICS)}"
            )
        
        # Validate statistic types
        for stat in statistics:
            if stat not in SUPPORTED_STATISTICS:
                raise ValueError(
                    f"Unsupported statistic type: {stat}. "
                    f"Supported statistics: {', '.join(SUPPORTED_STATISTICS)}"
                )
        
        # CloudWatch API call (wrap synchronous call as async)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.get_metric_statistics(
                Namespace=EBS_NAMESPACE,
                MetricName=metric_name,
                Dimensions=[
                    {
                        "Name": "VolumeId",
                        "Value": volume_id
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=statistics
            )
        )
        
        # Convert data points
        datapoints = []
        for dp in response.get("Datapoints", []):
            # Use first statistic value
            value = None
            for stat in statistics:
                if stat in dp:
                    value = dp[stat]
                    break
            
            if value is not None:
                datapoints.append(
                    MetricDataPoint(
                        timestamp=dp["Timestamp"],
                        value=value,
                        unit=dp.get("Unit", "None")
                    )
                )
        
        # Sort by timestamp
        datapoints.sort(key=lambda x: x.timestamp)
        
        # Calculate statistics
        average = None
        maximum = None
        minimum = None
        total_sum = None
        
        if datapoints:
            values = [dp.value for dp in datapoints]
            if "Average" in statistics:
                average = sum(values) / len(values)
            if "Maximum" in statistics:
                maximum = max(values)
            if "Minimum" in statistics:
                minimum = min(values)
            if "Sum" in statistics:
                total_sum = sum(values)
        
        return MetricResult(
            metric_name=metric_name,
            volume_id=volume_id,
            datapoints=datapoints,
            average=average,
            maximum=maximum,
            minimum=minimum,
            sum=total_sum
        )
    
    def list_available_metrics(self) -> list[str]:
        """Return list of available EBS metrics
        
        Returns a list of all EBS metric names supported by CloudWatch.
        
        Returns:
            list[str]: List of supported EBS metric names
        """
        return SUPPORTED_EBS_METRICS.copy()
