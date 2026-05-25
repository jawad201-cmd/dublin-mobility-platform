from google.transit import gtfs_realtime_pb2
import requests
import sys

# CONSTANTS
# Replace with your actual Primary Key
API_KEY = "4727f35e110c46d2ba4196542ac5fb67"
FEED_URL = "https://api.nationaltransport.ie/gtfsr/v2/gtfsr?format=pb"

def check_pulse():
    print("Connecting to Smart Dublin API...")
    
    headers = {
        "x-api-key": API_KEY,
        "Cache-Control": "no-cache"
    }
    
    try:
        # FETCH
        response = requests.get(FEED_URL, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("Connection Successful (200 OK)")
            print(f"Payload Size: {len(response.content) / 1024:.2f} KB")
        else:
            print(f"Failed: {response.status_code}")
            print(response.text)
            return

        # DECODE
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        # INSPECT
        entity_count = len(feed.entity)
        print(f"Vehicles Tracked: {entity_count}")
        
        if entity_count > 0:
            # Sample Data Inspection
            first_bus = feed.entity[0]
            print("\n--- SAMPLE DATA (First Bus) ---")
            print(f"ID: {first_bus.id}")
            if first_bus.HasField('vehicle'):
                pos = first_bus.vehicle.position
                print(f"Lat/Lon: {pos.latitude}, {pos.longitude}")
                if first_bus.vehicle.trip:
                    print(f"Route ID: {first_bus.vehicle.trip.route_id}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_pulse()