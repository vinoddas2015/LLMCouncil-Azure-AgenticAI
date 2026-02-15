module.exports = {
    name: `${process.env.APP_NAME}-${process.env.ENVIRONMENT}`,
    fargateParameters: {
      cpu: '1024',
      memory: '3GB',
      instanceCount: 1,
      healthCheckPath: '/health',
      taskRoleName: 'LLMCouncilExecutionRole'
    },
    aws: {
      accountId: process.env.AWS_ACCOUNT,
      fargateStackName: process.env.FARGATE_STACK_NAME,
      region: 'us-east-1',
    },
    docker: {
      ecrLifecyclePolicyFile: 'infrastructure/fg-config/ecr-lifecycle-policy.json',
      buildArgs: {
      }
    },
  };