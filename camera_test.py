from picamera2 import Picamera2
import io
import time
import os
import boto3
import glob
import requests
import json
from datetime import datetime
from botocore.exceptions import ClientError # Import ClientError for specific AWS exceptions

# --- Global Configuration ---
picam2 = None
AWS_REGION = "ap-southeast-2" # _MODIFY_
COLLECTION_ID = "FacesCollection" # _MODIFY_IF_NEEDED_ (Must exist in Rekognition)
IMAGES_DIR = "./testImages" # Indexing is a setup step
FACE_MATCH_THRESHOLD = 85.0
CAPTURE_INTERVAL = 2
SERVER_URL = "http://10.243.109.158:6969/http_message" # _MODIFY_

# --- Camera Functions ---
def initialize_camera():
    global picam2
    try:
        print("Initializing camera...")
        picam2 = Picamera2()
        config = picam2.create_still_configuration(main={"size": (640, 480)})
        picam2.configure(config)
        picam2.start()
        time.sleep(1)
        print("Camera initialized.")
        return picam2
    except Exception as e:
        print(f"CAMERA INIT ERROR: {e}")
        if picam2:
            try: picam2.close()
            except: pass
        return None


def capture_image_bytes():
    global picam2
    if not picam2 or not picam2.started:
        # print("DEBUG: Camera not ready for capture.") # Can be noisy
        return None
    try:
        stream = io.BytesIO()
        picam2.capture_file(stream, format='jpeg')
        stream.seek(0)
        return stream.getvalue()
    except Exception as e:
        print(f"CAPTURE ERROR: {e}")
        return None

# --- AWS Rekognition Functions ---
def get_rekognition_client(region_name):
    try:
        return boto3.client('rekognition', region_name=region_name)
    except Exception as e:
        print(f"REKOGNITION CLIENT ERROR: {e}")
        return None

def search_faces_in_image(client, image_bytes_to_search, collection_id, threshold):
    if not client or not image_bytes_to_search:
        # print("DEBUG: No client or no image bytes for search.") # Can be noisy
        return set() # Return an empty set if no image or client

    try:
        response = client.search_faces_by_image(
            CollectionId=collection_id,
            Image={'Bytes': image_bytes_to_search},
            FaceMatchThreshold=threshold,
            MaxFaces=5
        )
        recognized_userids = set()
        if response['FaceMatches']:
            for match in response['FaceMatches']:
                recognized_userids.add(match['Face'].get('ExternalImageId', 'UnknownFace'))
        # If no FaceMatches, recognized_userids remains empty, which is correct.
        return recognized_userids
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidParameterException':
            # This specific error often means no faces were detected in the input image
            # print(f"REKOGNITION INFO: No faces detected in the current image to search against collection. {e.response['Error']['Message']}")
            return set() # Return an empty set, as no faces were found to search
        else:
            # Handle other AWS client errors
            print(f"AWS REKOGNITION SEARCH ERROR: {e}")
            return set() # Return an empty set on other errors too
    except Exception as e:
        # Catch any other unexpected errors during the search
        print(f"UNEXPECTED SEARCH ERROR: {e}")
        return set()


# --- HTTP Notification Function ---
def send_notification(current_faces_set, previous_faces_set):
    message = ""

    if current_faces_set == set(): # no face
        message = "在電腦桌前面的人剛剛起身離開了。"
    else :
        current_faces = list(current_faces_set)
        message = f"剛剛{current_faces[0]}坐在了電腦桌前，他正在聽你講話。"

    payload = {
        'text': message
    }
    try:
        print(f"Sending message: {message}")
        requests.post(SERVER_URL, data=payload, timeout=5)
        # print("Notification attempt finished.")
    except requests.exceptions.RequestException as e:
        print(f"HTTP POST ERROR to {SERVER_URL}: {e}")
    except Exception as e:
        print(f"UNEXPECTED HTTP NOTIFICATION ERROR: {e}")


def index_faces_from_local_directory(client, directory_path, collection_id):
    """
    Indexes faces from a local directory into the AWS Rekognition collection.
    Assumes image files are named {userid}.jpg, {userid}.jpeg, or {userid}.png.
    NO ERROR HANDLING.
    """
    print(f"Starting face indexing from: {directory_path} into collection: {collection_id}")
    indexed_count = 0
    image_patterns = [
        os.path.join(directory_path, '*.jpg'),
        os.path.join(directory_path, '*.jpeg'),
        os.path.join(directory_path, '*.png')
    ]

    for pattern in image_patterns:
        for image_file_path in glob.glob(pattern):
            userid = os.path.splitext(os.path.basename(image_file_path))[0]
            print(f"  Processing: {image_file_path} for UserID: {userid}")

            with open(image_file_path, 'rb') as image_file:
                image_bytes_to_index = image_file.read()

            # This is the core AWS Rekognition call
            response = client.index_faces(
                CollectionId=collection_id,
                Image={'Bytes': image_bytes_to_index},
                ExternalImageId=userid,
                MaxFaces=1,  # Assuming one primary face per image for indexing
                QualityFilter="AUTO",
                DetectionAttributes=['DEFAULT'] # Can be 'NONE' if you don't need attributes during indexing
            )

            # Basic check if any face was actually indexed from the image
            if response['FaceRecords']:
                # print(f"    Successfully indexed FaceID: {response['FaceRecords'][0]['Face']['FaceId']} for UserID: {userid}")
                indexed_count += 1
            # else:
                # This part would normally indicate an issue (e.g., no face found in the image by Rekognition)
                # print(f"    Warning: No face records returned by Rekognition for {image_file_path}. Unindexed faces: {response.get('UnindexedFaces')}")


    print(f"Finished indexing. Total faces processed for indexing: {indexed_count}")
    # The function doesn't explicitly return a success/failure status in this minimal version

# --- Main Program ---
if __name__ == '__main__':
    rek_client = get_rekognition_client(AWS_REGION)

    index_faces_from_local_directory(rek_client, IMAGES_DIR, COLLECTION_ID)
    print(f"Using Rekognition Collection ID: {COLLECTION_ID}")

    picam2 = initialize_camera()
    if not picam2:
        print("Exiting: Failed to initialize camera.")
        exit()

    previous_recognized_userids = set()
    print(f"Starting continuous capture (every {CAPTURE_INTERVAL}s). Press Ctrl+C to exit.")

    try:
        while True:
            current_image_bytes = capture_image_bytes()

            if current_image_bytes:
                current_recognized_userids = search_faces_in_image(
                    rek_client, current_image_bytes, COLLECTION_ID, FACE_MATCH_THRESHOLD
                )
                # The print statement you had for debugging `current_recognized_userids`
                print(current_recognized_userids) # You can uncomment this to see the set of recognized faces

                if current_recognized_userids != previous_recognized_userids:
                    send_notification(current_recognized_userids, previous_recognized_userids)
                    previous_recognized_userids = current_recognized_userids.copy()
            # else:
                # print("DEBUG: No image captured in this cycle.") # Can be noisy

            time.sleep(CAPTURE_INTERVAL)
    except KeyboardInterrupt:
        print("\nExiting program on user request (Ctrl+C).")
    except Exception as e:
        print(f"UNEXPECTED ERROR IN MAIN LOOP: {e}")
    finally:
        if picam2:
            print("Stopping camera...")
            try:
                if picam2.started: picam2.stop()
                picam2.close()
                print("Camera stopped and closed.")
            except Exception as e:
                print(f"CAMERA CLOSE ERROR: {e}")