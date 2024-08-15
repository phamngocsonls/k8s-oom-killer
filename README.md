# K8S OOM Killer

## Overview
K8S OOM Killer delete the specified pod before it is OOMKilled. With Java Spring Boot, K8S OOM Killer using Actuator metrics to delete pod before it is out of heap memory  (java.lang.OutOfMemoryError: Java heap space)
K8S OOM Killed is inspired from pre-oom-killer by syossan27
ref: https://github.com/syossan27/pre-oom-killer

## Why?
While operating K8s service, OOMKilled event is a common issue when container memory usage reaches its limit.
By setting resource.memory.limit to avoid containers consuming more memory than necessary or memory leaks,... but it will cause your application downtime.

With ```k8s-oom-killer```, K8s pod will be deleted when container memory limit utilization reaches the threshold. Support Spring Boot heap memory via actuator metrics.
## How it work?
```k8s-oom-killer``` watches (once every ```60s``` by default) memory usage metrics for all pods matching label selector ```k8s-oom-killer=enabled``` Pods can specify a memory usage threshold by percent via an annotation ```k8s-oom-killer.v1alpha1.k8s.io/memory-usage-threshold``` and container target to watches via annotation ```k8s-oom-killer.v1alpha1.k8s.io/target-container-name```. When ```k8s-oom-killer``` finds that the container memory usage has crossed the specified threshold, it starts trying to delete the pod.

For Spring Boot application, ```k8s-oom-killer``` watch 2 metrics ```jvm.memory.max``` and ```jvm.memory.used``` using actuator metrics and delete when heap memory crossed the specified threshold

## Getting started
Install with kustomize
```
kustomize build ./deploy  | kubectl apply -f -
```
## Set Label and Annotation
The "k8s-oom-killer" is executed based on the labels and annotations described in the pod's metadata.
The following is an example using yaml to deploy nginx.

- Deployment
```
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    metadata:
      labels:
        app: nginx
        k8s-oom-killer: enabled
      annotations:
        k8s-oom-killer.v1alpha1.k8s.io/target-container-name: "nginx"
        k8s-oom-killer.v1alpha1.k8s.io/memory-usage-threshold: "95"
```

- Deployment for Spring Boot (Enable [spring-boot-actuator](https://docs.spring.io/spring-boot/docs/current/reference/html/actuator.html?query=health%27%20target=_blank%3E%3Cb%3Ehealth%3C/b%3E%3C/a%3E-groups#actuator.enabling))
```
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    metadata:
      labels:
        app: spring-boot
        k8s-oom-killer: enabled
      annotations:
        k8s-oom-killer.v1alpha1.k8s.io/target-container-name: "spring-boot"
        k8s-oom-killer.v1alpha1.k8s.io/memory-usage-threshold: "95"
        k8s-oom-killer.v1alpha1.k8s.io/memory-heap-usage-threshold: "90"
        k8s-oom-killer.v1alpha1.k8s.io/target-actuator-port: "8080"
```

The labels and annotations should include the following three fields.

- labels.k8s-oom-killer : Enable k8s-oom-killer, which is enabled if enabled and disabled otherwise or if there are no labels
- annotations:
    - k8s-oom-killer.v1alpha1.k8s.io/target-container-name : Specify the name of the container to be monitored for memory usage
    - k8s-oom-killer.v1alpha1.k8s.io/memory-usage-threshold : Memory usage threshold to delete pods
    - k8s-oom-killer.v1alpha1.k8s.io/memory-heap-usage-threshold: Heap memory usage threshold to delete pods
    - k8s-oom-killer.v1alpha1.k8s.io/target-actuator-port: Container port for actuator metrics

## OS Env
Some default environment variables can be overridden
```
grace_period_seconds = 300   #k8s delete grace period seconds
min_container_free_mem = 30  #if free memory below 30M -> Container will be deleted
min_heap_free_mem = 30       #if free heap memory below 30M -> Container will be deleted
dryRun = False               #Change to True for dry run
interval = 60
max_pod_rep_delete_batch = 1 #prevent tool delete all pod in replicaset at one time                
```
