# K-BeautyGate 샌드박스 이미지. 저장소 루트에서 빌드한다.
#   docker build -f openshell/Dockerfile -t kbg-sandbox:v2 .
# [실측] OpenShell 0.1.2 는 이미지의 WORKDIR 이 샌드박스 사용자 쓰기 가능해야 시작한다.
#        WORKDIR 을 /app 으로 두면 "workspace path component '/app' is not writable" 로 실패한다.
#        그래서 WORKDIR 은 /sandbox, 코드는 root 소유 /app 에 읽기 전용으로 둔다.
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl iproute2 python3 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1500 sandbox && useradd --uid 1500 --gid sandbox --create-home sandbox
COPY . /app/
COPY hackathon/ /hackathon/
RUN rm -rf /app/.git && install -d -o sandbox -g sandbox /hackathon/output /sandbox
WORKDIR /sandbox
USER sandbox
CMD ["sleep", "infinity"]
