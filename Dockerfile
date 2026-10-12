# Build for arm64, as the Lambdas run on Graviton: docker build --platform linux/arm64 --target jobs .

FROM public.ecr.aws/lambda/python:3.13@sha256:c3543ac595429c4bb204e868a5e806f9d46d66dbd8479f5a8911ed9cbc5606ee AS jobs
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
COPY pyproject.toml uv.lock ${LAMBDA_TASK_ROOT}/
RUN uv export --frozen --no-dev --no-emit-project --directory ${LAMBDA_TASK_ROOT} -o /tmp/requirements.txt \
    && uv pip install --no-cache --python /var/lang/bin/python --target ${LAMBDA_TASK_ROOT} -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt /bin/uv
# Same layout as the repo, so pegel.config finds config/pegel.json next to src/.
COPY config/ ${LAMBDA_TASK_ROOT}/config/
COPY src/ ${LAMBDA_TASK_ROOT}/src/
ENV PYTHONPATH=${LAMBDA_TASK_ROOT}/src
CMD ["pegel.jobs.lambda_handler.handler"]
