import sys
import json
import logging
from google.cloud import pubsub_v1
from google.cloud import bigquery

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RMI_PubSub_Consumer")

PROJECT_ID = "my-project-id"
SUBSCRIPTION_ID = "rmi-realtime-sub"
BQ_DATASET = "rmi_realtime"
BQ_TABLE = "recent_roads_live"

# Initialize Clients
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
bq_client = bigquery.Client(project=PROJECT_ID)

# In-memory de-duplication cache (sliding window of recently seen composite keys)
processed_cache = set()

def insert_to_bigquery(rows):
    """Inserts raw JSON rows into BigQuery streamingly."""
    table_ref = bq_client.dataset(BQ_DATASET).table(BQ_TABLE)
    errors = bq_client.insert_rows_json(table_ref, rows)
    if errors:
        logger.error(f"BigQuery write errors encountered: {errors}")
    else:
        logger.info(f"Streamed {len(rows)} records to BigQuery.")

def callback(message):
    """Asynchronous subscriber callback handling incoming payloads."""
    try:
        # 1. Parse the incoming payload (supports both JSON and Binary Protobuf)
        try:
            # Try JSON parsing first
            payload = json.loads(message.data.decode("utf-8"))
            route_id = payload.get("selected_route_id")
            display_name = payload.get("display_name")
            
            # Parse travel_duration
            travel_duration_payload = payload.get("travel_duration", {})
            duration_in_seconds = travel_duration_payload.get("duration_in_seconds")
            static_duration_in_seconds = travel_duration_payload.get("static_duration_in_seconds")
            
            # Parse retrieval_time (can be a nested object with seconds/nanos, or a string, or integer seconds)
            retrieval_time_payload = payload.get("retrieval_time", {})
            if isinstance(retrieval_time_payload, dict):
                retrieval_time_seconds = retrieval_time_payload.get("seconds")
                retrieval_time_nanos = retrieval_time_payload.get("nanos", 0)
            elif isinstance(retrieval_time_payload, (int, float)):
                retrieval_time_seconds = int(retrieval_time_payload)
                retrieval_time_nanos = int((retrieval_time_payload - retrieval_time_seconds) * 1e9)
            else:
                retrieval_time_seconds = None
                retrieval_time_nanos = None

            route_geometry = payload.get("route_geometry")
            speed_reading_intervals = payload.get("speed_reading_intervals", [])
            road_segment_ids = payload.get("road_segment_ids", [])
            
        except (unicode if sys.version_info[0] < 3 else str, ValueError, AttributeError, TypeError, KeyError):
            # Fallback to Protobuf deserialization if payload is binary
            from google.maps.roadsmanagement.insights.v1 import rmi_pb2
            proto_msg = rmi_pb2.RoadsInformation()
            proto_msg.ParseFromString(message.data)
            route_id = proto_msg.selected_route_id
            display_name = proto_msg.display_name
            duration_in_seconds = proto_msg.travel_duration.duration_in_seconds
            static_duration_in_seconds = proto_msg.travel_duration.static_duration_in_seconds
            retrieval_time_seconds = proto_msg.retrieval_time.seconds
            retrieval_time_nanos = proto_msg.retrieval_time.nanos
            route_geometry = proto_msg.route_geometry
            road_segment_ids = list(proto_msg.road_segment_ids)
            speed_reading_intervals = []
            for interval in proto_msg.speed_reading_intervals:
                coords = [{"latitude": c.latitude, "longitude": c.longitude} for c in interval.interval_coordinates]
                speed_reading_intervals.append({
                    "speed": interval.speed,
                    "interval_coordinates": coords
                })
        
        # 2. De-duplication check
        dedup_key = f"{route_id}_{retrieval_time_seconds}"
        if dedup_key in processed_cache:
            logger.info(f"Duplicate event detected for key: {dedup_key}. Skipping.")
            message.ack()
            return
            
        # 3. Process the message
        logger.info(f"Processing route_id={route_id} computed at ts={retrieval_time_seconds}")
        
        # Prepare BQ row matching roads_information_landing.json
        bq_row = {
            "selected_route_id": route_id,
            "display_name": display_name,
            "speed_reading_intervals": speed_reading_intervals,
            "travel_duration": {
                "duration_in_seconds": duration_in_seconds,
                "static_duration_in_seconds": static_duration_in_seconds
            },
            "retrieval_time": {
                "seconds": retrieval_time_seconds,
                "nanos": retrieval_time_nanos
            },
            "route_geometry": route_geometry,
            "road_segment_ids": road_segment_ids
        }
        
        # 4. Stream to BigQuery
        insert_to_bigquery([bq_row])
        
        # 5. Cache de-duplication key
        processed_cache.add(dedup_key)
        # Keep cache bounded
        if len(processed_cache) > 10000:
            processed_cache.pop()
            
        # 6. Acknowledge message delivery
        message.ack()
        
    except Exception as e:
        logger.error(f"Error handling message payload: {e}")
        # Nack message to trigger redelivery
        message.nack()

# Configure Flow Control (Backpressure Management)
flow_control = pubsub_v1.types.FlowControl(
    max_outstanding_messages=100,  # Limits memory overhead
    max_outstanding_bytes=50 * 1024 * 1024  # 50MB Max in-flight
)

# Start Subscription Stream
streaming_pull_future = subscriber.subscribe(
    subscription_path,
    callback=callback,
    flow_control=flow_control
)

logger.info(f"Active. Listening for RMI stream events on {subscription_path}...")

# Keep thread running
try:
    streaming_pull_future.result()
except KeyboardInterrupt:
    streaming_pull_future.cancel()
    logger.info("Subscription listener terminated by operator.")
