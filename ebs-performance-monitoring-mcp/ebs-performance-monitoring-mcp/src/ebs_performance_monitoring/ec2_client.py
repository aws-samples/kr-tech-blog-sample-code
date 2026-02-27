"""EC2 Instance Information and EBS Bandwidth Client

Retrieves instance type-specific EBS bandwidth information through AWS EC2 DescribeInstanceTypes API.
Allows checking EBS dedicated bandwidth limits for EC2 instances attached to EBS volumes.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError


@dataclass
class EC2EbsBandwidth:
    """EC2 Instance EBS Bandwidth Information
    
    Attributes:
        instance_id: EC2 instance ID
        instance_type: Instance type (e.g., m5.xlarge)
        ebs_optimized: EBS optimized status
        baseline_bandwidth_mbps: Baseline bandwidth in Mbps
        maximum_bandwidth_mbps: Maximum bandwidth in Mbps
        baseline_throughput_mib_s: Baseline throughput in MiB/s
        maximum_throughput_mib_s: Maximum throughput in MiB/s
        baseline_iops: Baseline IOPS
        maximum_iops: Maximum IOPS
    """
    instance_id: str
    instance_type: str
    ebs_optimized: bool
    baseline_bandwidth_mbps: int
    maximum_bandwidth_mbps: int
    baseline_throughput_mib_s: float
    maximum_throughput_mib_s: float
    baseline_iops: int
    maximum_iops: int


@dataclass 
class VolumeAttachment:
    """EBS Volume and EC2 Instance Attachment Information
    
    Attributes:
        volume_id: EBS volume ID
        instance_id: Attached EC2 instance ID
        device: Device name (e.g., /dev/xvda)
        state: Attachment state
    """
    volume_id: str
    instance_id: str
    device: str
    state: str


class EC2Client:
    """EC2 Instance Information Client"""
    
    # Mbps to MiB/s conversion constant (1 Mbps = 0.125 MB/s = 0.119209 MiB/s)
    MBPS_TO_MIB_S = 1 / 8 / 1.048576
    
    def __init__(self, region: Optional[str] = None):
        """Initialize client
        
        Args:
            region: AWS region (uses default region if None)
        """
        self.region = region
        if region:
            self._client = boto3.client("ec2", region_name=region)
        else:
            self._client = boto3.client("ec2")
    
    async def get_volume_attachment(self, volume_id: str) -> Optional[VolumeAttachment]:
        """Get EC2 instance attachment information for EBS volume
        
        Args:
            volume_id: EBS volume ID
            
        Returns:
            VolumeAttachment: Attachment information (None if not attached)
        """
        loop = asyncio.get_event_loop()
        
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.describe_volumes(VolumeIds=[volume_id])
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":
                return None
            raise
        
        volumes = response.get("Volumes", [])
        if not volumes:
            return None
        
        attachments = volumes[0].get("Attachments", [])
        if not attachments:
            return None
        
        # Return first attachment (may have multiple for Multi-Attach)
        att = attachments[0]
        return VolumeAttachment(
            volume_id=volume_id,
            instance_id=att["InstanceId"],
            device=att["Device"],
            state=att["State"]
        )
    
    async def get_instance_type(self, instance_id: str) -> Optional[str]:
        """Get instance type for EC2 instance
        
        Args:
            instance_id: EC2 instance ID
            
        Returns:
            str: Instance type (e.g., m5.xlarge)
        """
        loop = asyncio.get_event_loop()
        
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.describe_instances(InstanceIds=[instance_id])
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidInstanceID.NotFound":
                return None
            raise
        
        reservations = response.get("Reservations", [])
        if not reservations:
            return None
        
        instances = reservations[0].get("Instances", [])
        if not instances:
            return None
        
        return instances[0].get("InstanceType")
    
    async def get_instance_ebs_bandwidth(
        self, 
        instance_type: str
    ) -> Optional[dict]:
        """Get EBS bandwidth information for instance type
        
        Uses DescribeInstanceTypes API for real-time query.
        
        Args:
            instance_type: Instance type (e.g., m5.xlarge)
            
        Returns:
            dict: EBS bandwidth information
                - baseline_bandwidth_mbps: Baseline bandwidth in Mbps
                - maximum_bandwidth_mbps: Maximum bandwidth in Mbps
                - baseline_iops: Baseline IOPS
                - maximum_iops: Maximum IOPS
                - ebs_optimized_support: EBS optimized support status
        """
        loop = asyncio.get_event_loop()
        
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.describe_instance_types(
                    InstanceTypes=[instance_type]
                )
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidInstanceType":
                return None
            raise
        
        instance_types = response.get("InstanceTypes", [])
        if not instance_types:
            return None
        
        info = instance_types[0]
        ebs_info = info.get("EbsInfo", {})
        
        # EBS optimized support status
        ebs_optimized_support = ebs_info.get("EbsOptimizedSupport", "unsupported")
        
        # EBS bandwidth information
        ebs_bandwidth = ebs_info.get("EbsOptimizedInfo", {})
        
        return {
            "baseline_bandwidth_mbps": ebs_bandwidth.get("BaselineBandwidthInMbps", 0),
            "maximum_bandwidth_mbps": ebs_bandwidth.get("MaximumBandwidthInMbps", 0),
            "baseline_iops": ebs_bandwidth.get("BaselineIops", 0),
            "maximum_iops": ebs_bandwidth.get("MaximumIops", 0),
            "baseline_throughput_mib_s": ebs_bandwidth.get("BaselineThroughputInMBps", 0),
            "maximum_throughput_mib_s": ebs_bandwidth.get("MaximumThroughputInMBps", 0),
            "ebs_optimized_support": ebs_optimized_support,
        }
    
    async def get_ebs_bandwidth_for_volume(
        self, 
        volume_id: str
    ) -> Optional[EC2EbsBandwidth]:
        """Get EBS bandwidth information for EC2 instance attached to volume
        
        Queries in order: Volume -> Instance -> Instance Type -> EBS Bandwidth
        
        Args:
            volume_id: EBS volume ID
            
        Returns:
            EC2EbsBandwidth: EBS bandwidth information (None if not attached)
        """
        # 1. Get volume attachment information
        attachment = await self.get_volume_attachment(volume_id)
        if not attachment:
            return None
        
        # 2. Get instance type
        instance_type = await self.get_instance_type(attachment.instance_id)
        if not instance_type:
            return None
        
        # 3. Get EBS bandwidth information for instance type
        bandwidth_info = await self.get_instance_ebs_bandwidth(instance_type)
        if not bandwidth_info:
            return None
        
        # MiB/s conversion (API may return MB/s in some cases)
        baseline_throughput = bandwidth_info.get("baseline_throughput_mib_s", 0)
        maximum_throughput = bandwidth_info.get("maximum_throughput_mib_s", 0)
        
        # Convert from Mbps if API only returns Mbps
        if baseline_throughput == 0 and bandwidth_info["baseline_bandwidth_mbps"] > 0:
            baseline_throughput = bandwidth_info["baseline_bandwidth_mbps"] * self.MBPS_TO_MIB_S
        if maximum_throughput == 0 and bandwidth_info["maximum_bandwidth_mbps"] > 0:
            maximum_throughput = bandwidth_info["maximum_bandwidth_mbps"] * self.MBPS_TO_MIB_S
        
        return EC2EbsBandwidth(
            instance_id=attachment.instance_id,
            instance_type=instance_type,
            ebs_optimized=bandwidth_info["ebs_optimized_support"] in ("default", "supported"),
            baseline_bandwidth_mbps=bandwidth_info["baseline_bandwidth_mbps"],
            maximum_bandwidth_mbps=bandwidth_info["maximum_bandwidth_mbps"],
            baseline_throughput_mib_s=round(baseline_throughput, 2),
            maximum_throughput_mib_s=round(maximum_throughput, 2),
            baseline_iops=bandwidth_info["baseline_iops"],
            maximum_iops=bandwidth_info["maximum_iops"],
        )
    
    async def get_ebs_bandwidth_for_instance(
        self,
        instance_id: str
    ) -> Optional[EC2EbsBandwidth]:
        """Get EBS bandwidth information by EC2 instance ID
        
        Args:
            instance_id: EC2 instance ID
            
        Returns:
            EC2EbsBandwidth: EBS bandwidth information
        """
        # Get instance type
        instance_type = await self.get_instance_type(instance_id)
        if not instance_type:
            return None
        
        # Get EBS bandwidth information for instance type
        bandwidth_info = await self.get_instance_ebs_bandwidth(instance_type)
        if not bandwidth_info:
            return None
        
        baseline_throughput = bandwidth_info.get("baseline_throughput_mib_s", 0)
        maximum_throughput = bandwidth_info.get("maximum_throughput_mib_s", 0)
        
        if baseline_throughput == 0 and bandwidth_info["baseline_bandwidth_mbps"] > 0:
            baseline_throughput = bandwidth_info["baseline_bandwidth_mbps"] * self.MBPS_TO_MIB_S
        if maximum_throughput == 0 and bandwidth_info["maximum_bandwidth_mbps"] > 0:
            maximum_throughput = bandwidth_info["maximum_bandwidth_mbps"] * self.MBPS_TO_MIB_S
        
        return EC2EbsBandwidth(
            instance_id=instance_id,
            instance_type=instance_type,
            ebs_optimized=bandwidth_info["ebs_optimized_support"] in ("default", "supported"),
            baseline_bandwidth_mbps=bandwidth_info["baseline_bandwidth_mbps"],
            maximum_bandwidth_mbps=bandwidth_info["maximum_bandwidth_mbps"],
            baseline_throughput_mib_s=round(baseline_throughput, 2),
            maximum_throughput_mib_s=round(maximum_throughput, 2),
            baseline_iops=bandwidth_info["baseline_iops"],
            maximum_iops=bandwidth_info["maximum_iops"],
        )
