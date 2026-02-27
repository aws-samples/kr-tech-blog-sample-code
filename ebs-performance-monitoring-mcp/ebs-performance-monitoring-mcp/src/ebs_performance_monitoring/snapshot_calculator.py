"""Snapshot Size Calculator

Retrieves EBS volume snapshot information and calculates sizes.

Features:
- Query snapshot size by snapshot ID
- List snapshots by volume ID
- Calculate total snapshot size
- Error handling
"""

import asyncio
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from .models import SnapshotInfo


class SnapshotCalculator:
    """Snapshot Calculator
    
    Uses EC2 API to retrieve EBS snapshot information.
    
    Attributes:
        region: AWS region
        _client: boto3 EC2 client
    """
    
    def __init__(self, region: Optional[str] = None):
        """Initialize snapshot calculator
        
        Args:
            region: AWS region (uses default region if None)
        """
        self.region = region
        if region:
            self._client = boto3.client("ec2", region_name=region)
        else:
            self._client = boto3.client("ec2")
    
    async def get_snapshot_size(self, snapshot_id: str) -> SnapshotInfo:
        """Get snapshot size
        
        Retrieves size information for the specified snapshot ID.
        
        Args:
            snapshot_id: EBS snapshot ID (e.g., snap-1234567890abcdef0)
        
        Returns:
            SnapshotInfo: Snapshot information
        
        Raises:
            ValueError: If snapshot not found
            ClientError: If AWS API call fails
        """
        loop = asyncio.get_event_loop()
        
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._client.describe_snapshots(
                    SnapshotIds=[snapshot_id]
                )
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidSnapshot.NotFound":
                raise ValueError(f"Snapshot not found: {snapshot_id}")
            raise
        
        snapshots = response.get("Snapshots", [])
        if not snapshots:
            raise ValueError(f"Snapshot not found: {snapshot_id}")
        
        snapshot = snapshots[0]
        return SnapshotInfo(
            snapshot_id=snapshot["SnapshotId"],
            volume_id=snapshot.get("VolumeId", ""),
            size_gb=snapshot["VolumeSize"],
            start_time=snapshot["StartTime"],
            state=snapshot["State"],
            description=snapshot.get("Description")
        )
    
    async def list_volume_snapshots(
        self, 
        volume_id: str,
        max_results: int = 100
    ) -> list[SnapshotInfo]:
        """List snapshots for a volume
        
        Retrieves all snapshots for the specified volume ID.
        
        Args:
            volume_id: EBS volume ID (e.g., vol-1234567890abcdef0)
            max_results: Maximum number of results (default: 100)
        
        Returns:
            list[SnapshotInfo]: List of snapshot information
        """
        loop = asyncio.get_event_loop()
        
        response = await loop.run_in_executor(
            None,
            lambda: self._client.describe_snapshots(
                Filters=[
                    {
                        "Name": "volume-id",
                        "Values": [volume_id]
                    }
                ],
                MaxResults=max_results
            )
        )
        
        snapshots = []
        for snapshot in response.get("Snapshots", []):
            snapshots.append(
                SnapshotInfo(
                    snapshot_id=snapshot["SnapshotId"],
                    volume_id=snapshot.get("VolumeId", ""),
                    size_gb=snapshot["VolumeSize"],
                    start_time=snapshot["StartTime"],
                    state=snapshot["State"],
                    description=snapshot.get("Description")
                )
            )
        
        # Sort by start time (newest first)
        snapshots.sort(key=lambda x: x.start_time, reverse=True)
        
        return snapshots
    
    async def calculate_total_snapshot_size(self, volume_id: str) -> int:
        """Calculate total snapshot size for a volume
        
        Calculates the sum of all snapshot sizes for the specified volume.
        
        Args:
            volume_id: EBS volume ID
        
        Returns:
            int: Total snapshot size in GB
        """
        snapshots = await self.list_volume_snapshots(volume_id)
        return sum(s.size_gb for s in snapshots)
