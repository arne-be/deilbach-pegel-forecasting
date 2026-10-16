# Build for arm64, as the Lambdas run on Graviton: docker build --platform linux/arm64 --target jobs .
# The API image: the same with --target api.

FROM public.ecr.aws/lambda/python:3.13@sha256:c3543ac595429c4bb204e868a5e806f9d46d66dbd8479f5a8911ed9cbc5606ee AS jobs
# lightgbm needs the GNU OpenMP runtime, which the Lambda base image lacks.
RUN dnf install -y libgomp && dnf clean all
COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /bin/uv
COPY pyproject.toml uv.lock ${LAMBDA_TASK_ROOT}/
RUN uv export --frozen --no-dev --no-emit-project --directory ${LAMBDA_TASK_ROOT} -o /tmp/requirements.txt \
    && uv pip install --no-cache --python /var/lang/bin/python --target ${LAMBDA_TASK_ROOT} -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt /bin/uv
# Same layout as the repo, so pegel.config finds config/pegel.json next to src/.
COPY config/ ${LAMBDA_TASK_ROOT}/config/
COPY src/ ${LAMBDA_TASK_ROOT}/src/
ENV PYTHONPATH=${LAMBDA_TASK_ROOT}/src
CMD ["pegel.jobs.lambda_handler.handler"]

# The API: uvicorn behind the Lambda Web Adapter, which turns Lambda events into HTTP requests
# on port 8080. Its readiness check asks "/"; the 404 counts as ready (only 5xx doesn't).
# shortcut: the API image carries the jobs' ML dependencies; give it a slim install if cold
# starts hurt.
FROM jobs AS api
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0@sha256:17cfd08eff1dfea3f6a9a1e9c65fdac80aa4919b6085e746615530f43f57d2f1 /lambda-adapter /opt/extensions/lambda-adapter
# The Lambda runtime adds the task root to the path for handlers; uvicorn needs it set.
ENV PYTHONPATH=${LAMBDA_TASK_ROOT}:${LAMBDA_TASK_ROOT}/src
# Replaces the base image's entry point and resets the inherited CMD.
ENTRYPOINT ["/var/lang/bin/python", "-m", "uvicorn", "pegel.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
