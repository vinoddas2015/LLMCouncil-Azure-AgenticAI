const appName = `${process.env.APP_NAME}-${process.env.ENVIRONMENT}`;
const region = "us-east-1";
const accountId = process.env.AWS_ACCOUNT;

module.exports = {
  name: appName,
  fargateParameters: {
    cpu: "4096",
    memory: "10GB",
    instanceCount: 1,
    healthCheckPath: "/health",
    healthCheckGracePeriod: 60,
    timeoutInSeconds: 1200,
    port: 80,
    taskRoleName: "LLMCouncilExecutionRole",
  },
  aws: {
    accountId,
    fargateStackName: process.env.FARGATE_STACK_NAME,
    region,
  },
  docker: {
    ecrLifecyclePolicyFile: "infrastructure/fg-config/ecr-lifecycle-policy.json",
    buildArgs: {
      OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY,
      API_BASE_URL: process.env.API_BASE_URL,
      S3_BUCKET_NAME: `${process.env.APP_NAME}-conversations-${process.env.ENVIRONMENT}`,
    },
  },
};
