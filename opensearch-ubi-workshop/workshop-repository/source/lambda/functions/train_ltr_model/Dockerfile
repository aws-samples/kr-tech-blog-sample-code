FROM public.ecr.aws/lambda/python:3.12

RUN pip install --no-cache-dir \
    xgboost==2.1.4 \
    numpy==2.1.3 \
    opensearch-py==2.8.0 \
    requests-aws4auth==1.3.1 \
    requests==2.32.4

COPY train_ltr_model.py oscommon.py ${LAMBDA_TASK_ROOT}/

CMD ["train_ltr_model.handler"]
