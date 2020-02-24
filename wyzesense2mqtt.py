import paho.mqtt.client as mqtt
import json
import socket
import sys
import os
import logging
from retrying import retry
from wyzesense_custom import *

if not os.path.exists("logs"):
    os.makedirs("logs")
log = logging.getLogger("wyzesense2mqtt")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%a, %d %b %Y %H:%M:%S", filename="logs/wyzesense2mqtt.log", filemode="w")

diff = lambda l1, l2: [x for x in l1 if x not in l2]

def on_connect(client, userdata, flags, rc):
    log.debug("Connected with result code " + str(rc))
    client.message_callback_add(config["subscribeScanTopic"], on_message_scan)
    client.message_callback_add(config["subscribeRemoveTopic"], on_message_remove)
    log.debug("Handlers Added")

def on_disconnect(client, userdata, rc):
    log.debug("Disconnected with result code " + str(rc))
    client.message_callback_remove(config["subscribeScanTopic"])
    client.message_callback_remove(config["subscribeRemoveTopic"])
    log.debug("Handlers Removed")

def on_message(client, userdata, msg):
    log.debug(msg.topic+" " + str(msg.payload))  

def on_message_scan(client, userdata, msg):
    log.debug("In on_message_scan: {0}".format(msg.payload.decode()))
    prescan_result = ws.List()
    log.debug("Result of prescan {0}".format(prescan_result))   

    ws.Scan()

    postscan_result = ws.List()
    log.debug("Result of postscan {0}".format(postscan_result))  

    s = diff(postscan_result, prescan_result)  
    log.debug("Diff is {0}".format(s))  

    if s != []:
        jsonData = json.dumps({"macs": s})
        topic = config["publishScanResult"]
        log.debug(jsonData)
        client.publish(topic, payload = jsonData)
    else:
        log.debug("Empty Scan")

def on_message_remove(client, userdata, msg):
    log.debug(msg.topic+" " + str(msg.payload))          

def read_config():
    with open("config/config.json") as config_file:
        data = json.load(config_file)
    return data

# Send HASS discovery topics to MQTT
def send_discovery_topics(sensor_mac, sensor_type):
    device_data = {
        "identifiers": ["wyzesense_{0}".format(sensor_mac)],
        "manufacturer": "Wyze",
        "name": "Wyze Sense Motion Sensor" if sensor_type == "motion" else "Wyze Sense Contact Sensor"
    }

    state_data = {
        "device": device_data,
        "name": "Wyze Sense {0} State".format(sensor_mac),
        "unique_id": "wyzesense_{0}_state".format(sensor_mac),
        "device_class": "motion" if sensor_type == "motion" else "door",
        "state_topic": config["publishTopic"]+sensor_mac,
        "value_template": "{{ value_json.state }}",
        "payload_off": "0",
        "payload_on": "1"
    }
    state_topic = config["discoveryTopic"]+"binary_sensor/wyzesense_{0}_state/config".format(sensor_mac)
    client.publish(state_topic , payload = json.dumps(state_data), qos = config["mqtt"]["qos"], retain = config["mqtt"]["retain"])

    rssi_data = {
        "device": device_data,
        "name": "Wyze Sense {0} Signal Strength".format(sensor_mac),
        "unique_id": "wyzesense_{0}_signal_strength".format(sensor_mac),
        "device_class": "signal_strength",
        "state_topic": config["publishTopic"]+sensor_mac,
        "value_template": "{{ value_json.rssi }}",
        "unit_of_measurement": "dBm"
    }
    rssi_topic = config["discoveryTopic"]+"sensor/wyzesense_{0}_signal_strength/config".format(sensor_mac)
    client.publish(rssi_topic , payload = json.dumps(rssi_data), qos = config["mqtt"]["qos"], retain = config["mqtt"]["retain"])

    battery_data = {
        "device": device_data,
        "name": "Wyze Sense {0} Battery".format(sensor_mac),
        "unique_id": "wyzesense_{0}_battery".format(sensor_mac),
        "device_class": "battery",
        "state_topic": config["publishTopic"]+sensor_mac,
        "value_template": "{{ value_json.battery_level }}",
        "unit_of_measurement": "%"
    }
    battery_topic = config["discoveryTopic"]+"sensor/wyzesense_{0}_battery/config".format(sensor_mac)
    client.publish(battery_topic , payload = json.dumps(battery_data), qos = config["mqtt"]["qos"], retain = config["mqtt"]["retain"])

config = read_config()
client = mqtt.Client(client_id = config["mqtt"]["client"], clean_session = config["mqtt"]["clean_session"])
client.username_pw_set(username = config["mqtt"]["user"], password = config["mqtt"]["password"])
client.connect(config["mqtt"]["host"], port = config["mqtt"]["port"], keepalive = config["mqtt"]["keepalive"])

client.subscribe([(config["subscribeScanTopic"], 1), (config["subscribeRemoveTopic"], 1)])
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

def on_event(ws, event):
    log.debug("In Event")
    if event.Type == 'state':
        try:
            (sensor_type, sensor_state, sensor_battery, sensor_signal) = event.Data
            data = {
                "available": True,
                "mac": event.MAC,
                "state": 1 if sensor_state == "open" or sensor_state == "active" else 0,
                "device_class": "device motion" if sensor_type == "motion" else "device door",
                "device_class_timestamp": event.Timestamp.isoformat(),
                "rssi": sensor_signal * -1,
                "battery_level": sensor_battery
            }

            log.debug(data)

            jsonData = json.dumps(data)
            topic = config["publishTopic"]+"{0}".format(event.MAC)
            client.publish(topic , payload = jsonData, qos = config["mqtt"]["qos"], retain = config["mqtt"]["retain"])

            if config["performDiscovery"] == True:
                send_discovery_topics(event.MAC, sensor_type)

        except TimeoutError as err:
            log.debug(err)
        except socket.timeout as err:            
            log.debug(err)
        except: # catch *all* exceptions
            e = sys.exc_info()[0]
            log.debug("Error: {0}".format(e))

@retry(wait_exponential_multiplier=1000, wait_exponential_max=10000)
def beginConn():
    log.debug("In beginConn")
    return Open(config["usb"], on_event)

#Connect to USB
ws = beginConn()

# Message Loop
log.debug("Loop Forever")
client.loop_forever(retry_first_connection = True)