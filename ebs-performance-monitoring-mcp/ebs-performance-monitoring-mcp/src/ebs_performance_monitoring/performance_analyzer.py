"""Performance Analyzer

Comprehensively analyzes and summarizes EBS volume performance.
Calculates actual usage compared to provisioned performance.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from .cloudwatch_client import CloudWatchClient
from .volume_client import VolumeClient, VolumeConfig
from .models import PerformanceSummary, MultiVolumeResult


BYTES_PER_MIB = 1024 * 1024


class PerformanceAnalyzer:
    """EBS Volume Performance Analyzer"""
    
    def __init__(self, region: Optional[str] = None):
        """Initialize analyzer
        
        Args:
            region: AWS region (uses default region if None)
        """
        self.region = region
        self.cloudwatch = CloudWatchClient(region=region)
        self.volume_client = VolumeClient(region=region)
    
    async def analyze_volume(
        self,
        volume_id: str,
        hours: int = 24,
        period: int = 300
    ) -> PerformanceSummary:
        """Analyze single volume performance
        
        Args:
            volume_id: EBS volume ID
            hours: Analysis period in hours (default: 24)
            period: Metric collection interval in seconds (default: 300)
            
        Returns:
            PerformanceSummary: Performance summary information
        """
        # Set time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)
        
        # Get volume configuration
        volume_config = await self.volume_client.get_volume_config(volume_id)
        
        # Fetch CloudWatch metrics
        metrics = await self._fetch_metrics(volume_id, start_time, end_time, period)
        
        # Calculate performance summary
        return self._calculate_summary(volume_config, metrics, hours, period)
    
    async def analyze_multiple_volumes(
        self,
        volume_ids: list[str],
        hours: int = 24,
        period: int = 300
    ) -> MultiVolumeResult:
        """Analyze multiple volumes performance
        
        Args:
            volume_ids: List of EBS volume IDs
            hours: Analysis period in hours (default: 24)
            period: Metric collection interval in seconds (default: 300)
            
        Returns:
            MultiVolumeResult: Multi-volume analysis result
        """
        # Analyze all volumes in parallel
        tasks = [
            self.analyze_volume(vid, hours, period) 
            for vid in volume_ids
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results only
        summaries = []
        errors = []
        for vid, result in zip(volume_ids, results):
            if isinstance(result, Exception):
                errors.append({"volume_id": vid, "error": str(result)})
            else:
                summaries.append(result)
        
        # Calculate overall summary statistics
        summary = self._calculate_multi_volume_summary(summaries, errors)
        
        return MultiVolumeResult(
            volumes=summaries,
            total_volumes=len(volume_ids),
            analysis_period_hours=hours,
            summary=summary
        )
    
    async def _fetch_metrics(
        self,
        volume_id: str,
        start_time: datetime,
        end_time: datetime,
        period: int
    ) -> dict:
        """Fetch CloudWatch metrics
        
        Args:
            volume_id: EBS volume ID
            start_time: Start time
            end_time: End time
            period: Collection interval in seconds
            
        Returns:
            dict: Dictionary of metric names and values
        """
        metric_names = [
            "VolumeReadOps",
            "VolumeWriteOps",
            "VolumeReadBytes",
            "VolumeWriteBytes",
            "VolumeTotalReadTime",
            "VolumeTotalWriteTime",
            "VolumeIdleTime",
            "BurstBalance",
        ]
        
        metrics = {}
        for metric_name in metric_names:
            try:
                result = await self.cloudwatch.get_metric_statistics(
                    volume_id=volume_id,
                    metric_name=metric_name,
                    start_time=start_time,
                    end_time=end_time,
                    period=period,
                    statistics=["Sum", "Average"]
                )
                
                metrics[metric_name] = {
                    "sum": result.sum or 0,
                    "average": result.average,
                    "datapoints": len(result.datapoints)
                }
            except Exception:
                if metric_name != "BurstBalance":
                    metrics[metric_name] = {"sum": 0, "average": None, "datapoints": 0}
        
        return metrics
    
    def _calculate_summary(
        self,
        config: VolumeConfig,
        metrics: dict,
        hours: int,
        period: int
    ) -> PerformanceSummary:
        """Calculate performance summary
        
        Args:
            config: Volume configuration
            metrics: CloudWatch metric data
            hours: Analysis period in hours
            period: Collection interval in seconds
            
        Returns:
            PerformanceSummary: Performance summary
        """
        total_seconds = hours * 3600
        
        # Extract metric values
        read_ops = metrics.get("VolumeReadOps", {}).get("sum", 0)
        write_ops = metrics.get("VolumeWriteOps", {}).get("sum", 0)
        read_bytes = metrics.get("VolumeReadBytes", {}).get("sum", 0)
        write_bytes = metrics.get("VolumeWriteBytes", {}).get("sum", 0)
        total_read_time = metrics.get("VolumeTotalReadTime", {}).get("sum", 0)
        total_write_time = metrics.get("VolumeTotalWriteTime", {}).get("sum", 0)
        idle_time = metrics.get("VolumeIdleTime", {}).get("sum", 0)
        burst_balance = metrics.get("BurstBalance", {}).get("average")
        
        # Calculate average IOPS
        avg_read_iops = read_ops / total_seconds if total_seconds > 0 else 0
        avg_write_iops = write_ops / total_seconds if total_seconds > 0 else 0
        avg_total_iops = avg_read_iops + avg_write_iops
        
        # Calculate average throughput (MiB/s)
        avg_read_throughput = (read_bytes / total_seconds) / BYTES_PER_MIB if total_seconds > 0 else 0
        avg_write_throughput = (write_bytes / total_seconds) / BYTES_PER_MIB if total_seconds > 0 else 0
        avg_total_throughput = avg_read_throughput + avg_write_throughput
        
        # Calculate bursting performance (based on active time)
        active_time = total_seconds - idle_time
        if active_time > 0:
            bursting_read_iops = read_ops / active_time
            bursting_write_iops = write_ops / active_time
            bursting_read_throughput = (read_bytes / active_time) / BYTES_PER_MIB
            bursting_write_throughput = (write_bytes / active_time) / BYTES_PER_MIB
        else:
            bursting_read_iops = 0
            bursting_write_iops = 0
            bursting_read_throughput = 0
            bursting_write_throughput = 0
        
        bursting_total_iops = bursting_read_iops + bursting_write_iops
        bursting_total_throughput = bursting_read_throughput + bursting_write_throughput
        
        # Calculate latency (ms)
        avg_read_latency = (total_read_time / read_ops * 1000) if read_ops > 0 else 0
        avg_write_latency = (total_write_time / write_ops * 1000) if write_ops > 0 else 0
        
        # Calculate I/O utilization
        io_utilization = ((total_seconds - idle_time) / total_seconds * 100) if total_seconds > 0 else 0
        io_utilization = max(0, min(100, io_utilization))
        
        # Calculate utilization compared to provisioned performance
        provisioned_iops = config.baseline_iops
        provisioned_throughput = config.baseline_throughput_mib_s
        
        iops_utilization = (avg_total_iops / provisioned_iops * 100) if provisioned_iops > 0 else 0
        throughput_utilization = (avg_total_throughput / provisioned_throughput * 100) if provisioned_throughput > 0 else 0
        
        return PerformanceSummary(
            volume_id=config.volume_id,
            volume_type=config.volume_type,
            size_gb=config.size_gb,
            period_hours=hours,
            provisioned_iops=provisioned_iops,
            provisioned_throughput_mib_s=provisioned_throughput,
            avg_read_iops=round(avg_read_iops, 2),
            avg_write_iops=round(avg_write_iops, 2),
            avg_total_iops=round(avg_total_iops, 2),
            avg_read_throughput_mib_s=round(avg_read_throughput, 3),
            avg_write_throughput_mib_s=round(avg_write_throughput, 3),
            avg_total_throughput_mib_s=round(avg_total_throughput, 3),
            bursting_read_iops=round(bursting_read_iops, 2),
            bursting_write_iops=round(bursting_write_iops, 2),
            bursting_total_iops=round(bursting_total_iops, 2),
            bursting_read_throughput_mib_s=round(bursting_read_throughput, 3),
            bursting_write_throughput_mib_s=round(bursting_write_throughput, 3),
            bursting_total_throughput_mib_s=round(bursting_total_throughput, 3),
            avg_read_latency_ms=round(avg_read_latency, 3),
            avg_write_latency_ms=round(avg_write_latency, 3),
            total_read_ops=int(read_ops),
            total_write_ops=int(write_ops),
            total_read_bytes=int(read_bytes),
            total_write_bytes=int(write_bytes),
            io_utilization_percent=round(io_utilization, 2),
            iops_utilization_percent=round(iops_utilization, 2),
            throughput_utilization_percent=round(throughput_utilization, 2),
            burst_balance=round(burst_balance, 2) if burst_balance is not None else None
        )
    
    def _calculate_multi_volume_summary(
        self,
        summaries: list[PerformanceSummary],
        errors: list[dict]
    ) -> dict:
        """Calculate multi-volume overall summary
        
        Args:
            summaries: List of successful volume summaries
            errors: List of failed volume information
            
        Returns:
            dict: Overall summary statistics
        """
        if not summaries:
            return {
                "successful_volumes": 0,
                "failed_volumes": len(errors),
                "errors": errors
            }
        
        # Aggregate statistics
        total_iops = sum(s.avg_total_iops for s in summaries)
        total_throughput = sum(s.avg_total_throughput_mib_s for s in summaries)
        avg_io_utilization = sum(s.io_utilization_percent for s in summaries) / len(summaries)
        avg_iops_utilization = sum(s.iops_utilization_percent for s in summaries) / len(summaries)
        avg_throughput_utilization = sum(s.throughput_utilization_percent for s in summaries) / len(summaries)
        
        # Highest/lowest utilization volumes
        highest_util = max(summaries, key=lambda s: s.iops_utilization_percent)
        lowest_util = min(summaries, key=lambda s: s.iops_utilization_percent)
        
        return {
            "successful_volumes": len(summaries),
            "failed_volumes": len(errors),
            "total_avg_iops": round(total_iops, 2),
            "total_avg_throughput_mib_s": round(total_throughput, 3),
            "avg_io_utilization_percent": round(avg_io_utilization, 2),
            "avg_iops_utilization_percent": round(avg_iops_utilization, 2),
            "avg_throughput_utilization_percent": round(avg_throughput_utilization, 2),
            "highest_utilization_volume": {
                "volume_id": highest_util.volume_id,
                "iops_utilization_percent": highest_util.iops_utilization_percent
            },
            "lowest_utilization_volume": {
                "volume_id": lowest_util.volume_id,
                "iops_utilization_percent": lowest_util.iops_utilization_percent
            },
            "errors": errors if errors else None
        }
