import os
import json
import codecs
import logging
import tempfile
from subprocess import run
from subprocess import PIPE
from threading import Thread

import boto3
import virtualenv

from chalice import Chalice

app = Chalice(app_name='canary')
app.debug = True
app.log.setLevel(logging.INFO)


_ROOT = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_FILE = os.path.join(_ROOT, 'chalicelib', 'packages.json')
_PACKAGE_LIST = json.loads(codecs.open(_PACKAGE_FILE, 'r',
                                       encoding='utf-8').read())


@app.schedule('rate(1 hour)')
def canary(event):
    _check_installability()


def _check_installability():
    with tempfile.TemporaryDirectory() as tempdir:
        venv_dir = _create_and_activate_venv(tempdir)
        py_exe = os.path.join(venv_dir, 'bin', 'python')
        chalice_exe = _install_chalice(py_exe)
        threads = [Thread(target=_check_can_package,
                          args=(chalice_exe, package, tempdir))
                   for package in _PACKAGE_LIST]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()


def _create_and_activate_venv(tempdir):
    venv_dir = os.path.join(tempdir, 'venv')
    virtualenv.create_environment(venv_dir)
    exec(open(os.path.join(venv_dir, "bin", "activate_this.py")).read())
    return venv_dir


def _install_chalice(py_exe):
    run([py_exe, '-m', 'pip', 'install', '--upgrade', 'chalice', '--no-cache'])
    chalice_exe = os.path.join(os.path.dirname(py_exe), 'chalice')
    return chalice_exe


def _check_can_package(chalice_exe, package_name, tempdir):
    project_name = 'package-%s' % package_name
    run([chalice_exe, 'new-project', project_name], cwd=tempdir)
    project_dir = os.path.join(tempdir, project_name)
    requirements_file = os.path.join(project_dir, 'requirements.txt')
    open(requirements_file, 'w').write('%s\n' % package_name)
    p = run([chalice_exe, 'package', 'out'], cwd=project_dir, encoding='utf-8',
            stdout=PIPE)

    if 'Could not install dependencies:' in p.stdout:
        app.log.error('Could not package %s', package_name)
        _send_metric(package_name, 0)
    else:
        app.log.info('Packaged %s', package_name)
        _send_metric(package_name, 1)


def _send_metric(package_name, success):
    boto3.client('cloudwatch').put_metric_data(
        Namespace='ChalicePackageCanary',
        MetricData=[
            {
                'MetricName': 'package',
                'Dimensions': [
                    {
                        'Name': 'Name',
                        'Value': package_name
                    },
                ],
                'Value': success,
            }
        ]
    )
