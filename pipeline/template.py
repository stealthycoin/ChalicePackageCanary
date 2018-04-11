from troposphere import Ref, Template, Parameter, Output, Sub
from troposphere import codebuild, s3, iam, codepipeline, sns, events
from awacs.aws import Policy, Statement, Allow, Action, Principal

from awacs.helpers.trust import make_simple_assume_policy
from awacs import sts as _sts
from awacs import logs as _logs
from awacs import s3 as _s3
from awacs import sns as _sns
from awacs import cloudformation as _cfn


class PipelineTemplate(object):

    PARAMS = {
        'ApplicationName': Parameter(
            'ApplicationName',
            Default='chalice-package-canaries',
            Type='String',
            Description='Enter the name of your application.'
        ),
        'CodeBuildImage': Parameter(
            'CodeBuildImage',
            Default='python:3.6.1',
            Type='String',
            Description='Name of codebuild image to use.'
        ),
        'GithubPersonalToken': Parameter(
            'GithubPersonalToken',
            Type='String',
            Description='Personal access token for github repo access'
        ),
        'GithubSourceOwner': Parameter(
            'GithubSourceOwner',
            Type='String',
            Description='Owner of the github repo to use as a source'
        ),
        'GithubSourceRepo': Parameter(
            'GithubSourceRepo',
            Type='String',
            Description='Repo name of the github repo to use as a source'
        ),
    }

    def __init__(self):
        self._t = Template()
        self._t.version = '2010-09-09'

    def generate_template(self):
        self._add_parameters()
        artifact_bucket_store = self._create_artifact_bucket_store()
        app_bucket = self._create_app_bucket()

        cfn_deploy_role = self._create_cfn_deploy_role()
        code_build_role = self._create_code_build_role()
        app_package_build = self._create_codebuild_project(code_build_role)
        pipeline_role = self._create_pipeline_role()

        stages = self._create_pipeline_stages(app_package_build,
                                              cfn_deploy_role)
        self._create_code_pipeline(
            pipeline_role, artifact_bucket_store, stages)

        self._t.add_output([
            Output('S3PipelineBucket', Value=Ref(artifact_bucket_store)),
            Output('CodePipelineRoleArn', Value=pipeline_role.GetAtt('Arn')),
            Output('CodeBuildRoleArn', Value=code_build_role.GetAtt('Arn')),
            Output('CFNDeployRoleArn', Value=cfn_deploy_role.GetAtt('Arn')),
            Output('S3ApplicationBucket', Value=Ref(app_bucket)),
        ])
        return self._t

    def _add_parameters(self):
        self._t.add_parameter(list(self.PARAMS.values()))

    def _create_cfn_deploy_role(self):
        cfn_deploy_role = iam.Role(
            'CFNDeployRole',
            AssumeRolePolicyDocument=self._allow_assume_role_service(
                'cloudformation'
            ),
            Policies=[
                iam.PolicyProperty(
                    PolicyName='DeployAccess',
                    PolicyDocument=Policy(
                        Version='2012-10-17',
                        Statement=[
                            Statement(
                                Action=[Action('*')],
                                Resource=['*'],
                                Effect=Allow,
                            )
                        ]
                    )
                )
            ]
        )
        self._t.add_resource(cfn_deploy_role)
        return cfn_deploy_role

    def _create_code_build_role(self):
        code_build_role = iam.Role(
            'CodeBuildRole',
            AssumeRolePolicyDocument=Policy(
                Version='2012-10-17',
                Statement=[
                    Statement(
                        Effect=Allow,
                        Action=[
                            _sts.AssumeRole,
                        ],
                        Principal=Principal(
                            'Service', 'codebuild.amazonaws.com'
                        )
                    )
                ]
            )
        )
        self._t.add_resource(code_build_role)
        code_build_policy = iam.PolicyType(
            'CodeBuildPolicy',
            PolicyName='CodeBuildPolicy',
            PolicyDocument=Policy(
                Version='2012-10-17',
                Statement=[
                    Statement(
                        Action=[
                            _logs.CreateLogGroup,
                            _logs.CreateLogStream,
                            _logs.PutLogEvents,
                        ],
                        Effect=Allow,
                        Resource=['*'],
                    ),
                    Statement(
                        Effect=Allow,
                        Action=[
                            _s3.GetObject,
                            _s3.GetObjectVersion,
                            _s3.PutObject,
                        ],
                        Resource=[_s3.ARN('*')],
                    ),
                ]
            ),
            Roles=[Ref(code_build_role)],
        )
        self._t.add_resource(code_build_policy)
        return code_build_role

    def _create_app_bucket(self):
        # This is where the s3 deployment packages
        # from the 'aws cloudformation package' command
        # are uploaded.  We should investigate just using
        # the artifact_bucket_store with a different prefix
        # instead of requiring two buckets.
        app_bucket = s3.Bucket('ApplicationBucket')
        self._t.add_resource(app_bucket)
        return app_bucket

    def _create_pipeline_role(self):
        pipeline_role = iam.Role(
            'CodePipelineRole',
            AssumeRolePolicyDocument=self._allow_assume_role_service(
                'codepipeline',
            ),
            Policies=[
                iam.PolicyProperty(
                    PolicyName='DefaultPolicy',
                    PolicyDocument=Policy(
                        Version='2012-10-17',
                        Statement=[
                            Statement(
                                Action=[
                                    _s3.GetObject,
                                    _s3.GetObjectVersion,
                                    _s3.GetBucketVersioning,
                                    _s3.CreateBucket,
                                    _s3.PutObject,
                                    _s3.PutBucketVersioning,
                                ],
                                Resource=['*'],
                                Effect=Allow,
                            ),
                            Statement(
                                Action=[
                                    Action('cloudwatch', '*'),
                                    Action('iam', 'PassRole'),
                                    Action('iam', 'ListRoles'),
                                    Action('iam', 'GetRole'),
                                    _sts.AssumeRole,
                                ],
                                Resource=['*'],
                                Effect=Allow,
                            ),
                            Statement(
                                Action=[
                                    Action('lambda', 'InvokeFunction'),
                                    Action('lambda', 'ListFunctions'),
                                ],
                                Resource=['*'],
                                Effect=Allow,
                            ),
                            Statement(
                                Action=[
                                    _cfn.CreateStack,
                                    _cfn.DeleteStack,
                                    _cfn.DescribeStacks,
                                    _cfn.UpdateStack,
                                    _cfn.CreateChangeSet,
                                    _cfn.DeleteChangeSet,
                                    _cfn.DescribeChangeSet,
                                    _cfn.ExecuteChangeSet,
                                    _cfn.SetStackPolicy,
                                    _cfn.ValidateTemplate,
                                    Action('iam', 'PassRole'),
                                ],
                                Resource=['*'],
                                Effect=Allow,
                            ),
                            Statement(
                                Action=[
                                    Action('codebuild', 'BatchGetBuilds'),
                                    Action('codebuild', 'StartBuild'),
                                ],
                                Resource=['*'],
                                Effect=Allow,
                            ),
                        ]
                    )
                )
            ]
        )
        self._t.add_resource(pipeline_role)
        return pipeline_role

    def _create_code_pipeline(self, pipeline_role, artifact_bucket_store,
                              stages):
        pipeline = codepipeline.Pipeline(
            'AppPipeline',
            Name=Sub('${ApplicationName}-pipeline'),
            RoleArn=pipeline_role.GetAtt('Arn'),
            Stages=stages,
            ArtifactStore=codepipeline.ArtifactStore(
                Type='S3',
                Location=artifact_bucket_store.Ref(),
            )
        )
        self._t.add_resource(pipeline)
        return pipeline

    def _create_pipeline_stages(self, app_package_build, cfn_deploy_role):
        stages = [
            codepipeline.Stages(
                Name='Source',
                Actions=[
                    codepipeline.Actions(
                        Name='Source',
                        RunOrder=1,
                        ActionTypeId=codepipeline.ActionTypeID(
                            Category='Source',
                            Owner='ThirdParty',
                            Version='1',
                            Provider='GitHub',
                        ),
                        Configuration={
                            'Owner': self.PARAMS['GithubSourceOwner'].Ref(),
                            'Repo': self.PARAMS['GithubSourceRepo'].Ref(),
                            'PollForSourceChanges': False,
                            'OAuthToken': self.PARAMS[
                                'GithubPersonalToken'].Ref(),
                            'Branch': 'master',
                        },
                        OutputArtifacts=[
                            codepipeline.OutputArtifacts(
                                Name='SourceRepo',
                            )
                        ]
                    )
                ]
            ),
            codepipeline.Stages(
                Name='Build',
                Actions=[
                    codepipeline.Actions(
                        Name='CodeBuild',
                        RunOrder=1,
                        ActionTypeId=codepipeline.ActionTypeID(
                            Category='Build',
                            Owner='AWS',
                            Version='1',
                            Provider='CodeBuild',
                        ),
                        Configuration={
                            'ProjectName': app_package_build.Ref(),
                        },
                        InputArtifacts=[
                            codepipeline.InputArtifacts(
                                Name='SourceRepo',
                            )
                        ],
                        OutputArtifacts=[
                            codepipeline.OutputArtifacts(
                                Name='CompiledCFNTemplate',
                            )
                        ]
                    )
                ]
            ),
            codepipeline.Stages(
                Name='Beta',
                Actions=[
                    codepipeline.Actions(
                        Name='CreateBetaChangeSet',
                        RunOrder=1,
                        InputArtifacts=[
                            codepipeline.InputArtifacts(
                                Name='CompiledCFNTemplate',
                            )
                        ],
                        ActionTypeId=codepipeline.ActionTypeID(
                            Category='Deploy',
                            Owner='AWS',
                            Version='1',
                            Provider='CloudFormation',
                        ),
                        Configuration={
                            'ActionMode': 'CHANGE_SET_REPLACE',
                            'ChangeSetName': Sub(
                                '${ApplicationName}-change-set'),
                            'RoleArn': cfn_deploy_role.GetAtt('Arn'),
                            'Capabilities': 'CAPABILITY_IAM',
                            'StackName': Sub('${ApplicationName}-beta-stack'),
                            'TemplatePath': (
                                'CompiledCFNTemplate::transformed.yaml'),
                        }
                    ),
                    codepipeline.Actions(
                        Name='ExecuteChangeSet',
                        RunOrder=2,
                        ActionTypeId=codepipeline.ActionTypeID(
                            Category='Deploy',
                            Owner='AWS',
                            Version='1',
                            Provider='CloudFormation',
                        ),
                        OutputArtifacts=[
                            codepipeline.OutputArtifacts(
                                Name='AppDeploymentValues',
                            )
                        ],
                        Configuration={
                            "StackName": Sub("${ApplicationName}-beta-stack"),
                            "ActionMode": "CHANGE_SET_EXECUTE",
                            "ChangeSetName": Sub(
                                "${ApplicationName}-change-set"),
                            "OutputFileName": "StackOutputs.json"
                        }
                    ),
                ]
            )
        ]
        return stages

    def _create_codebuild_project(self, code_build_role):
        app_package_build = codebuild.Project(
            'AppPackageBuild',
            Artifacts=codebuild.Artifacts(
                Type='CODEPIPELINE'
            ),
            Name=Sub('${ApplicationName}-build'),
            Environment=codebuild.Environment(
                ComputeType='BUILD_GENERAL1_LARGE',
                Image=Ref('CodeBuildImage'),
                Type='LINUX_CONTAINER',
                EnvironmentVariables=[
                    codebuild.EnvironmentVariable(
                        Name='APP_S3_BUCKET',
                        Value=Ref('ApplicationBucket'),
                    ),
                ]
            ),
            ServiceRole=code_build_role.GetAtt('Arn'),
            Source=codebuild.Source(
                Type='CODEPIPELINE',
                BuildSpec='pipeline/buildspec.yml',
            ),
        )
        self._t.add_resource(app_package_build)
        return app_package_build

    def _create_artifact_bucket_store(self):
        artifact_bucket_store = s3.Bucket('ArtifactBucketStore')
        self._t.add_resource(artifact_bucket_store)
        return artifact_bucket_store

    def _allow_assume_role_service(self, service_name):
        # make_simple_assume_policy does not add a version number,
        # so this is a wrapper that injects the version string.
        policy = make_simple_assume_policy(
            '%s.amazonaws.com' % service_name,
        )
        policy.Version = '2012-10-17'
        return policy

    def _add_pipeline_notifications(self, pipeline):
        subscriptions = self._create_sns_subscriptions()
        topic = sns.Topic(
            'AppPipelineDeployments',
            DisplayName='AppPipelineDeployments',
            Subscription=subscriptions,
        )
        self._t.add_resource(topic)

        topic_policy = sns.TopicPolicy(
            'AllowCloudWatchEventsPublish',
            PolicyDocument=Policy(
                Version='2012-10-17',
                Statement=[
                    Statement(
                        Sid='AllowCloudWatchEventsToPublish',
                        Effect=Allow,
                        Action=[_sns.Publish],
                        Principal=Principal('Service', 'events.amazonaws.com'),
                        Resource=[topic.Ref()],
                    )
                ]
            ),
            Topics=[topic.Ref()],
        )
        self._t.add_resource(topic_policy)

        sns_target = [events.Target(Id='1', Arn=topic.Ref())]
        cw_event = events.Rule(
            'PipelineEvents',
            Description='CloudWatch Events Rule for app pipeline.',
            EventPattern={
                "source": [
                    "aws.codepipeline"
                ],
                "detail-type": [
                    'CodePipeline Action Execution State Change',
                ],
                'detail': {
                    'type': {
                        # Notify when a deploy fails/succeeds
                        # or when an approval is needed.
                        # We could also add something when any
                        # part of the pipeline fails.
                        'category': ['Deploy', 'Approval'],
                    },
                    'pipeline': [pipeline.Ref()],
                }
            },
            Targets=sns_target,
        )
        self._t.add_resource(cw_event)
        return topic

    def _create_sns_subscriptions(self):
        protocol = Parameter(
            'SNSProtocol',
            Type='String',
            Description=('The protocol type for the SNS subscription used '
                         'for pipeline event notifications (e.g "email")')
        )
        endpoint = Parameter(
            'SNSEndpoint',
            Type='String',
            Description=('The endpoint value for the SNS subscription used '
                         'for pipeline event notifications.  If the protocol '
                         'type is "email" then this value is the email '
                         'address.')
        )
        self._t.add_parameter([protocol, endpoint])
        return [
            sns.Subscription(
                Protocol=protocol.Ref(),
                Endpoint=endpoint.Ref(),
            )
        ]


def generate_template():
    return PipelineTemplate().generate_template()


def main():
    t = generate_template()
    print(t.to_json(indent=2))


if __name__ == '__main__':
    main()
