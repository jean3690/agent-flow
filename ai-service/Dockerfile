FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app ./app
RUN pip install . && pip install "gunicorn>=22"

EXPOSE 8000
# 单 worker：运行中任务注册表（取消执行）保存在进程内存里，多 worker 会导致取消请求落错实例
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "-b", "0.0.0.0:8000"]
