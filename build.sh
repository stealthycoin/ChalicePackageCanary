#!/bin/bash
pip install --upgrade awscli
aws --version
pip install virtualenv
virtualenv /tmp/venv
. /tmp/venv/bin/activate
pip install -r requirements.txt

cd canary
pip install -r requirements.txt
chalice package /tmp/packaged || exit 1
cd ..

python pipeline/inject-dashboard.py /tmp/packaged/sam.json \
       --packages canary/chalicelib/packages.json || exit 1

cat /tmp/packaged/sam.json
aws cloudformation package \
    --template-file /tmp/packaged/sam.json \
    --s3-bucket "${APP_S3_BUCKET}" \
    --output-template-file /tmp/packaged/transformed.yaml
