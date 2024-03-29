#!/bin/sh
docker build -f os-base/kytos-base/Dockerfile -t kytos-base .
docker build --no-cache -f os-base/rabbit-base/Dockerfile -t rabbit-mq .
docker build --no-cache -f os-base/mongo-base/Dockerfile -t mongo-db .
docker build --no-cache -f os-base/mongo-replicas/mongo1t/Dockerfile -t mongo1t .
docker build --no-cache -f os-base/mongo-replicas/mongo2t/Dockerfile -t mongo2t .
docker build --no-cache -f os-base/mongo-replicas/mongo3t/Dockerfile -t mongo3t .
