"""EBS Volume Information Client

Retrieves EBS volume configuration information through AWS EC2 API.
Allows checking provisioned IOPS, throughput, volume type, etc.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError


@dataclass
class VolumeConfig:
    """EBS Volume Configuration
    
    Attributes:
        volume_id: Volume ID
        volume_type: Volume type (gp2, gp3, io1, io2, st1, sc1, standard)
        size_gb: Volume size in GB
        iops: Provisioned IOPS (io1, io2, gp3 only)
        throughput_mib_s: Provisioned throughput in MiB/s (gp3 only)
        state: Volume state
        availability_zone: Availability zone
        encrypted: Encryption status
        multi_attach_enabled: Multi-attach enabled status
    """
    volume_id: str
    volume_type: str
    size_gb: int
    iops: Optional[int]
    throughput_mib_s: Optional[int]
    state: str
    availability_zone: str
    encrypted: bool
    multi_attach_enabled: bool
    
    @property
    def baseline_iops(self) -> int:
        """Return baseline IOPS by volume type"""
        if self.volume_type == "gp2":
            # gp2: 3 IOPS/GB, min 100, max 16,000
            return min(max(self.size_gb * 3, 100), 16000)
        elif self.volume_type == "gp3":
            # gp3: default 3,000 IOPS, can be provisioned
            return self.iops or 3000
        elif self.volume_type in ("io1", "io2"):
            # io1/io2: provisioned IOPS
            return self.iops or 0
        elif self.volume_type == "st1":
            # st1: based on 500 MiB/s, IOPS varies by volume size
            return min(self.size_gb * 500 // 1024, 500)
        elif self.volume_type == "sc1":
            # sc1: based on 250 MiB/s
            return min(self.size_gb * 250 // 1024, 250)
        else:
            return 0
    
    @property
    def baseline_throughput_mib_s(self) -> float:
        """Return baseline throughput by volume type (MiB/s)"""
        if self.volume_type == "gp2":
            # gp2: 128-250 MiB/s (varies by volume size)
            if self.size_gb <= 170:
                return 128.0
            else:
                return min(250.0, 128.0 + (self.size_gb - 170) * 0.25)
        elif self.volume_type == "gp3":
            # gp3: default 125 MiB/s, can be provisioned
            return float(self.throughput_mib_s or 125)
        elif self.volume_type == "io1":
            # io1: max 1,000 MiB/s
            return min(1000.0, self.baseline_iops * 0.256)
        elif self.volume_type == "io2":
            # io2: max 4,000 MiB/s (io2 Block Express)
            return min(4000.0, self.baseline_iops * 0.256)
        elif self.volume_type == "st1":
            # st1: max 500 MiB/s
            return min(500.0, self.size_gb * 40 / 1024)
        elif self.volume_type == "sc1":
            # sc1: max 250 MiB/s
            return min(250.0, self.size_gb * 12 / 1024)
        else:
            return 0.0


class VolumeClient:
    """EBS Volume Information Client"""
    
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
    
    async def get_volume_config(self, volume_id: str) -> VolumeConfig:
        """Get volume configuration
        
        Args:
            volume_id: EBS volume ID
            
        Returns:
            VolumeConfig: Volume configuration
            
        Raises:
            ValueError: If volume not found
        """
        loop = asyncio.get_event_loop()
        
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.describe_volumes(VolumeIds=[volume_id])
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":
                raise ValueError(f"Volume not found: {volume_id}")
            raise
        
        volumes = response.get("Volumes", [])
        if not volumes:
            raise ValueError(f"Volume not found: {volume_id}")
        
        vol = volumes[0]
        
        return VolumeConfig(
            volume_id=vol["VolumeId"],
            volume_type=vol["VolumeType"],
            size_gb=vol["Size"],
            iops=vol.get("Iops"),
            throughput_mib_s=vol.get("Throughput"),
            state=vol["State"],
            availability_zone=vol["AvailabilityZone"],
            encrypted=vol.get("Encrypted", False),
            multi_attach_enabled=vol.get("MultiAttachEnabled", False)
        )
    
    async def get_multiple_volume_configs(
        self, 
        volume_ids: list[str]
    ) -> dict[str, VolumeConfig]:
        """Get configuration for multiple volumes
        
        Args:
            volume_ids: List of EBS volume IDs
            
        Returns:
            dict[str, VolumeConfig]: Dictionary of volume configurations keyed by volume ID
        """
        loop = asyncio.get_event_loop()
        
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.describe_volumes(VolumeIds=volume_ids)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidVolume.NotFound":
                # Fallback to individual queries
                results = {}
                for vid in volume_ids:
                    try:
                        results[vid] = await self.get_volume_config(vid)
                    except ValueError:
                        pass
                return results
            raise
        
        results = {}
        for vol in response.get("Volumes", []):
            config = VolumeConfig(
                volume_id=vol["VolumeId"],
                volume_type=vol["VolumeType"],
                size_gb=vol["Size"],
                iops=vol.get("Iops"),
                throughput_mib_s=vol.get("Throughput"),
                state=vol["State"],
                availability_zone=vol["AvailabilityZone"],
                encrypted=vol.get("Encrypted", False),
                multi_attach_enabled=vol.get("MultiAttachEnabled", False)
            )
            results[vol["VolumeId"]] = config
        
        return results
