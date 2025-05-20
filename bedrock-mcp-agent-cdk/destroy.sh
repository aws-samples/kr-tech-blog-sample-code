#!/bin/bash
. ./conf/vpc-info
cdk destroy -c region=$AWS_REGION -c vpcId=$VPC_ID -c subnetIds=$SUBNET_IDS
