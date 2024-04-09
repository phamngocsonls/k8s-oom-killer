from kubernetes import client, config
import requests
import time
import threading
import os

config.load_incluster_config() # for local environment
#config.load_kube_config()

v1 = client.CoreV1Api()
metrics_api = client.CustomObjectsApi()
# Get all pods in all namespaces (adjust as needed)

#Default config
grace_period_seconds = 300
min_container_free_mem = 30
min_heap_free_mem = 30
dryRun = False
interval = 60

if 'grace_period_seconds' in os.environ:
    grace_period_seconds = int(os.environ['grace_period_seconds'])
if 'min_container_free_mem' in os.environ:
    min_container_free_mem = float(os.environ['min_container_free_mem'])
if 'min_heap_free_mem' in os.environ:
    min_heap_free_mem = float(os.environ['min_heap_free_mem'])
if 'interval' in os.environ:
    interval = int(os.environ['interval'])
if 'dryRun' in os.environ:
    if os.environ['dryRun'] == "True":
        dryRun = True

def delete_pod(api_client, pod_name, namespace, grace_period_seconds=300):
    try:
        # Create deletion propagation V1DeleteOptions object
        delete_options = client.V1DeleteOptions(grace_period_seconds=grace_period_seconds)
        api_client.delete_namespaced_pod(pod_name, namespace,body=delete_options)
        print(f"Pod '{pod_name}' deleted with grace period of {grace_period_seconds} seconds.")
    except client.ApiException as e:
        print(f"Error deleting pod: {e}")

def get_memory_info(container_data):
    #convert memory limit from M,Mi,G,Gi to M)
    config_limit = container_data['limits']['memory']
    config_mem_m = 0
    if config_limit[-1] == "G":
        config_mem_m = int(float(config_limit[:-1])*1000)
    elif config_limit[-2:] == "Mi":
        config_mem_m = int(float(config_limit[:-2])*1024*1024/1000/1000)
    elif config_limit[-2:] == "Gi":
        config_mem_m = int(float(config_limit[:-2])*1024*1024*1024/1000/1000/1000)
    elif config_limit[-1] == "M":
        config_mem_m = int(float(config_limit[:-1]))
    
    memory_usage = float(container_data['usage']['memory'][:-2])*1024/1000/1000
    memory_utilz = round(memory_usage/config_mem_m*100,2)
    memory_free = round(config_mem_m - memory_usage,2)
    return memory_free,memory_utilz

def get_heap_meminfo(pod_ip,service_port):
    try:
        rq = requests.get(f'http://{pod_ip}:{service_port}/actuator/metrics/jvm.memory.max?tag=area:heap',timeout=1)
    except:
        return None,None
    max_heap = rq.json()['measurements'][0]['value']
    try:
        rq = requests.get(f'http://{pod_ip}:{service_port}/actuator/metrics/jvm.memory.used?tag=area:heap',timeout=1)
    except:
        return None,None
    usage_heap = rq.json()['measurements'][0]['value']
    return (max_heap-usage_heap)/1000000,(usage_heap/max_heap)*100

def oom_killer():
    pod_data = {}
    all_namespace = []
    try:
        pod_list = v1.list_pod_for_all_namespaces(watch=False)
    except client.ApiException as e:
        print("Error getting pods:", e)
        exit(1)

    # Convert V1PodList object to JSON string
    json_data = pod_list.to_dict()
    for i in json_data['items']:
        if i['metadata']['labels'] == None:
            continue
        if 'k8s-oom-killer' not in i['metadata']['labels']:
            continue
        if i['status']['phase'] == 'Running' and i['metadata']['namespace'] != 'kube-system' and i['metadata']['labels']['k8s-oom-killer'] == 'enabled':
            container_data = {}
            limits = {}
            for c in i['spec']['containers']:
                if "limits" in c['resources']:
                    limits = c['resources']['limits']
                if limits == None:
                    continue
                container_data[c['name']] = {'limits':limits}

            if i['metadata']['namespace'] not in all_namespace:
                all_namespace.append(i['metadata']['namespace'])
            pod_data[i['metadata']['name']] = {'annotations':i['metadata']['annotations'],'namespace':i['metadata']['namespace'],'pod_ip':i['status']['pod_ip'],"container_data":container_data}

    ## metrics server
    for i in all_namespace:
        try:
            resource = metrics_api.list_namespaced_custom_object(group="metrics.k8s.io",version="v1beta1", namespace=i, plural="pods")
            time.sleep(1)
        except: #metrics_server return 503, retry 1 time
            resource = metrics_api.list_namespaced_custom_object(group="metrics.k8s.io",version="v1beta1", namespace=i, plural="pods")
            time.sleep(1)

        for pod in resource["items"]:
            #print(pod)
            if pod['metadata']['name'] in pod_data:
                if pod_data[pod['metadata']['name']]['namespace'] == i:
                    for c_metrics in pod['containers']:
                        if c_metrics['name'] in pod_data[pod['metadata']['name']]['container_data']:
                            pod_data[pod['metadata']['name']]['container_data'][c_metrics['name']]['usage'] = c_metrics['usage']
                            if pod_data[pod['metadata']['name']]['container_data'][c_metrics['name']]['limits'] != None:
                                if 'memory' in pod_data[pod['metadata']['name']]['container_data'][c_metrics['name']]['limits']:
                                    memory_free,memory_utilz = get_memory_info(pod_data[pod['metadata']['name']]['container_data'][c_metrics['name']])
                                    pod_data[pod['metadata']['name']]['container_data'][c_metrics['name']]['memory_free'] = memory_free
                                    pod_data[pod['metadata']['name']]['container_data'][c_metrics['name']]['memory_utilz'] = memory_utilz

    for i in pod_data:
        #print(i,pod_data[i])
        if "k8s-oom-killer.v1alpha1.k8s.io/memory-heap-usage-threshold" in pod_data[i]['annotations'] and "k8s-oom-killer.v1alpha1.k8s.io/target-actuator-port" in pod_data[i]['annotations']:
            #kill heap
            heap_free, heap_usage_utilz = get_heap_meminfo(pod_data[i]["pod_ip"],pod_data[i]['annotations']["k8s-oom-killer.v1alpha1.k8s.io/target-actuator-port"])
            if heap_free == None and heap_usage_utilz == None:
                continue
            if heap_free < min_heap_free_mem or heap_usage_utilz > float(pod_data[i]['annotations']["k8s-oom-killer.v1alpha1.k8s.io/memory-heap-usage-threshold"]):
                print(f'Heap: Deleted pod {i}, namespace: {pod_data[i]["namespace"]}')
                if dryRun == False:
                    delete_pod(v1, i, pod_data[i]['namespace'],grace_period_seconds)
                continue

        if "k8s-oom-killer.v1alpha1.k8s.io/memory-usage-threshold" in pod_data[i]['annotations'] and "k8s-oom-killer.v1alpha1.k8s.io/target-container-name" in pod_data[i]['annotations']:
            if pod_data[i]["container_data"][pod_data[i]['annotations']["k8s-oom-killer.v1alpha1.k8s.io/target-container-name"]]['memory_free'] < min_container_free_mem or pod_data[i]["container_data"][pod_data[i]['annotations']["k8s-oom-killer.v1alpha1.k8s.io/target-container-name"]]['memory_utilz'] > float(pod_data[i]['annotations']["k8s-oom-killer.v1alpha1.k8s.io/memory-usage-threshold"]):
                print(f'Container: Deleted pod {i}, namespace: {pod_data[i]["namespace"]}')
                if dryRun == False:
                    delete_pod(v1, i, pod_data[i]['namespace'],grace_period_seconds)

if __name__ == "__main__":
    print("Hello, checking job...")
    while True:
        threading.Thread(target=oom_killer).start()
        time.sleep(interval)