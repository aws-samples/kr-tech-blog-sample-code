const Config = {
    aws: {
        account: "1234567890",
        region: "ap-northeast-2",
    },
    app: {
        service: 'cdk-test',
        application: 'iot',
        environment: 'dev'
      },
    s3BucketName : "cdk-s3-test-bucket",

    // Assume that you have created a VPC with two subnets and a security group
    vpc: {
        securityGroup: "vpc-security-group",
        subnetId: ["vpc-subnet-id1", "vpc-subnet-id2"],
        vpcId: "vpc-id"
    },
    msk: {
        bootstrapServers: "<b-1.msk-bootstrap-servers:9096>, <b-2.msk-bootstrap-servers:9096>",
        securityProtocol: "SASL_SSL",
        saslMechanism: "SCRAM-SHA-512",
    }
};
export { Config };
