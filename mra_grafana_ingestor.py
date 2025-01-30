import datetime
import time
import json
import os
import logging
from typing import Dict, Any
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from lookout_mra_client.lookout_logger import init_lookout_logger
from lookout_mra_client.event_forwarders.event_forwarder import EventForwarder
from lookout_mra_client.mra_v2_stream_thread import MRAv2StreamThread

class InfluxDBForwarder(EventForwarder):
    def __init__(self, influx_url: str, token: str, org: str, bucket: str):
        """Initialize InfluxDB connection for storing MRA events."""
        self.client = InfluxDBClient(url=influx_url, token=token, org=org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = bucket
        self.org = org
        logging.info(f"Initialized InfluxDB connection to {influx_url}")

    def _convert_to_point(self, event: Dict[str, Any], ent_name: str) -> Point:
        """Convert MRA event to InfluxDB point format."""
        # Extract timestamp or use current time
        timestamp = event.get('timestamp', datetime.datetime.utcnow().isoformat())
        
        # Create base point with common fields
        point = Point("mra_events")\
            .tag("event_type", event.get('type', 'unknown'))\
            .tag("enterprise", ent_name)\
            .time(timestamp)
        
        # Add relevant fields based on event type
        if event.get('type') == 'THREAT':
            point.field("severity", event.get('severity', 0))
            point.field("threat_type", event.get('threatType', 'unknown'))
            point.tag("device_id", event.get('targetGuid', 'unknown'))
            
        elif event.get('type') == 'DEVICE':
            point.field("os_version", event.get('osVersion', 'unknown'))
            point.field("risk_score", event.get('riskScore', 0))
            point.tag("device_id", event.get('deviceGuid', 'unknown'))
            
        elif event.get('type') == 'AUDIT':
            point.field("action", event.get('action', 'unknown'))
            point.tag("user", event.get('userId', 'unknown'))
        
        return point

    def write(self, event: Dict[str, Any], ent_name: str = ""):
        """Write event to InfluxDB."""
        try:
            point = self._convert_to_point(event, ent_name)
            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            logging.debug(f"Successfully wrote event to InfluxDB: {event.get('type')}")
        except Exception as e:
            logging.error(f"Failed to write event to InfluxDB: {e}")
            logging.debug(f"Failed event: {event}")

def main():
    # Initialize logging
    init_lookout_logger("./mra_grafana_ingestor.log")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Get configuration from environment variables
    influx_config = {
        'url': os.getenv('INFLUX_URL', 'http://localhost:8086'),
        'token': os.getenv('INFLUX_TOKEN', 'your-secret-token'),
        'org': os.getenv('INFLUX_ORG', 'lookout'),
        'bucket': os.getenv('INFLUX_BUCKET', 'mra_events')
    }
    
    mra_config = {
        'api_key': os.getenv('MRA_API_KEY'),
        'enterprise_name': os.getenv('ENTERPRISE_NAME')
    }

    if not mra_config['api_key'] or not mra_config['enterprise_name']:
        raise ValueError("MRA_API_KEY and ENTERPRISE_NAME environment variables are required")

    # Initialize forwarder
    forwarder = InfluxDBForwarder(
        influx_url=influx_config['url'],
        token=influx_config['token'],
        org=influx_config['org'],
        bucket=influx_config['bucket']
    )

    # Configure MRA stream
    start_time = datetime.datetime.now() - datetime.timedelta(days=1)
    start_time = start_time.replace(tzinfo=datetime.timezone.utc)
    event_types = ["THREAT", "DEVICE", "AUDIT"]
    
    stream_args = {
        "api_domain": "https://api.lookout.com",
        "api_key": mra_config['api_key'],
        "start_time": start_time,
        "event_type": ",".join(event_types),
    }

    # Initialize and start MRA stream
    mra = MRAv2StreamThread(mra_config['enterprise_name'], forwarder, **stream_args)

    try:
        logging.info("Starting MRA event ingestion...")
        mra.start()
        while True:
            time.sleep(100)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        mra.shutdown_flag.set()
        mra.join()
        logging.info("Shutdown complete")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise

if __name__ == "__main__":
    main()