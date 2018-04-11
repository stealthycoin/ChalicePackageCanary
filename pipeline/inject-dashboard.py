import json
import codecs
import argparse

from troposphere import Sub
from troposphere import cloudwatch
from troposphere.template_generator import TemplateGenerator


DASHBOARD = {
    "widgets": [
        {
            "type": "metric",
            "x": 0,
            "y": 0,
            "width": 15,
            "height": 6,
            "properties": {
                "view": "timeSeries",
                "stacked": False,
                "metrics": [],
                "region": "${AWS::Region}",
                "period": 300,
                "annotations": {
                    "horizontal": [
                        {
                            "color": "#2ca02c",
                            "label": "Successfully Packaged",
                            "value": 1
                        },
                        {
                            "color": "#d62728",
                            "label": "Failed to Package",
                            "value": 0
                        }
                    ]
                },
                "title": "Chalice Packaging",
                "yAxis": {
                    "left": {
                        "min": 0,
                        "max": 1
                    }
                }
            }
        },
        {
            "type": "metric",
            "x": 0,
            "y": 12,
            "width": 15,
            "height": 6,
            "properties": {
                "view": "timeSeries",
                "stacked": False,
                "metrics": [
                    ["AWS/Lambda", "Duration", "FunctionName",
                     "${CanaryFunctionName}",
                     {"period": 3600}]
                ],
                "region": "${AWS::Region}",
                "title": "Lambda Duration",
                "period": 300,
                "annotations": {
                    "horizontal": [
                        {
                            "label": "Timeout",
                            "value": 300000
                        }
                    ]
                },
                "yAxis": {
                    "left": {
                        "min": 0,
                        "max": 300000
                    }
                }
            }
        },
        {
            "type": "metric",
            "x": 0,
            "y": 18,
            "width": 15,
            "height": 6,
            "properties": {
                "view": "timeSeries",
                "stacked": False,
                "metrics": [
                    ["AWS/Lambda", "Invocations", "FunctionName",
                     "${CanaryFunctionName}",
                     {"color": "#2ca02c", "period": 3600, "stat": "Sum"}]
                ],
                "region": "${AWS::Region}",
                "title": "Lambda Invocations",
                "period": 300
            }
        },
        {
            "type": "metric",
            "x": 0,
            "y": 6,
            "width": 15,
            "height": 6,
            "properties": {
                "view": "timeSeries",
                "stacked": False,
                "metrics": [
                    ["AWS/Lambda", "Errors", "FunctionName",
                     "${CanaryFunctionName}",
                     {"color": "#d62728", "stat": "Maximum", "period": 3600}]
                ],
                "region": "${AWS::Region}",
                "title": "Lambda Errors",
                "period": 300
            }
        }
    ]
}


def inject_dashboard(args):
    template = _load_template(args.template_path)
    canary_lambda = template.resources['Canary']
    dashboard_body = _build_dashboard_body(canary_lambda, args.packages)
    dashboard = cloudwatch.Dashboard(
        'ChalicePackaging',
        DashboardName='ChalicePackaging',
        DashboardBody=dashboard_body,
    )
    template.add_resource(dashboard)
    new_template_content = template.to_json()
    _overwrite_template(args.template_path, new_template_content)


def _load_template(template_path):
    raw_json = json.loads(open(template_path, 'r').read())
    template = TemplateGenerator(raw_json)
    return template


def _build_dashboard_body(canary_lambda, packages_file):
    raw_packages = codecs.open(packages_file, 'r', encoding='utf-8').read()
    packages = json.loads(raw_packages)
    metrics = []
    prefix = ["ChalicePackageCanary", "package", "Name"]
    for package in packages:
        metric = [*prefix, package,
                  {"period": 3600}],
        metrics.extend(metric)
        prefix = ["..."]
    dashboard = DASHBOARD.copy()
    dashboard['widgets'][0]['properties']['metrics'] = metrics
    dashboard_body = json.dumps(dashboard)
    return Sub(dashboard_body, CanaryFunctionName=canary_lambda.Ref())


def _overwrite_template(template_path, new_template_content):
    with open(template_path, 'w') as f:
        f.write(new_template_content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('template_path')
    parser.add_argument('-p', '--packages',
                        help=(
                            'Path to a JSON file that contains a list of '
                            'packages to check.'
                        ), required=True)
    args = parser.parse_args()
    inject_dashboard(args)


if __name__ == '__main__':
    main()
