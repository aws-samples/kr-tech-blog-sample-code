#!/bin/bash
. ./conf/vpc-info
cdk deploy -c region=$AWS_REGION -c vpcId=$VPC_ID -c subnetIds=$SUBNET_IDS
