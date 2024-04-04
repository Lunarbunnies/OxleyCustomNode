import sys
import os

# Get the directory of the current script
current_script_dir = os.path.dirname(os.path.abspath(__file__))

# Construct the path to the external_packages directory
external_packages_path = os.path.join(current_script_dir, 'external_packages')

# Add this path to sys.path
sys.path.append(external_packages_path)

import requests
from io import BytesIO
from PIL import Image
import numpy as np
import torch  # Import torch
import websocket
from websocket import WebSocketTimeoutException
import json
from json.decoder import JSONDecodeError
import base64
from datetime import datetime, timedelta

def get_latest_message(ws):
    latest_message = None
    try:
        # Loop to drain any queued messages, keeping the last one
        while True:
            message = ws.recv()
            latest_message = message
    except WebSocketTimeoutException:
        pass  # No more messages in the queue
    except Exception as e:
        # General exception handling (optional, based on your error handling strategy)
        print(f"An error occurred while receiving WebSocket messages: {e}")
        latest_message = None        
    return latest_message


class OxleyWebsocketDownloadImageNode:
    ws_connections = {}  # Class-level dictionary to store WebSocket connections by URL

    last_execution_time = None
    execution_interval = timedelta(milliseconds=50)  # Targeting 20 FPS
    
    @classmethod
    def get_connection(cls, ws_url):
        """Get an existing WebSocket connection or create a new one."""
        if ws_url not in cls.ws_connections:
            cls.ws_connections[ws_url] = websocket.create_connection(ws_url)
        return cls.ws_connections[ws_url]

    @classmethod
    def close_connection(cls, ws_url):
        """Close and remove a WebSocket connection."""
        if ws_url in cls.ws_connections:
            cls.ws_connections[ws_url].close()
            del cls.ws_connections[ws_url]
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"ws_url": ("STRING", {})},  # WebSocket URL to connect to
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_out",)
    FUNCTION = "download_image_ws"
    CATEGORY = "oxley"

    def download_image_ws(self, ws_url):
       
        # Initialize or get an existing WebSocket client connection
        ws = self.get_connection(ws_url)
        
        # Receive a message
        # message = ws.recv()
        
        # Set the WebSocket to non-blocking or with a very short timeout
        ws.settimeout(0.01)  # Example, adjust based on your library's capabilities
        
        try:
            message = get_latest_message(ws)  # Use your custom method for receiving the latest message
            if message is None:
                # No new message to process, return a placeholder to maintain a consistent return type
                return (torch.tensor([]),)  # Returning an empty tensor in a tuple
        except Exception as e:
            print(f"Error receiving message: {e}")
            # On error, also return an empty tensor to maintain consistency
            return (torch.tensor([]),)  # Returning an empty tensor in a tuple

        try:
            # Process the message assuming it's valid JSON
            data = json.loads(message)
        except JSONDecodeError:
            print(f"Received non-JSON message: {message}")
            # If the message isn't valid JSON, return an empty tensor
            return (torch.tensor([]),)  # Returning an empty tensor in a tuple

        if "image" in data:
            try:
                # Assuming 'image' data is properly formatted
                image_data = base64.b64decode(data["image"].split(",")[1])
                image = Image.open(BytesIO(image_data))

                 # Convert the image to RGB format
                image = image.convert("RGB")
        
                # Convert the image to a NumPy array and normalize it
                image_array = np.array(image).astype(np.float32) / 255.0
        
                # Convert the NumPy array to a PyTorch tensor
                image_tensor = torch.from_numpy(image_array)
        
                # Add a new batch dimension at the beginning
                image_tensor = image_tensor[None,]
        
                # Return the PyTorch tensor with the batch dimension added
                return (image_tensor,)
        
            except Exception as e:
                print(f"Error processing image data: {e}")
                # On error in processing the image, return an empty tensor
                return (torch.tensor([]),)  # Returning an empty tensor in a tuple
        else:
            print("No image data found in the received message")
            # If there's no image data in the message, return an empty tensor
            return (torch.tensor([]),)  # Returning an empty tensor in a tuple

    @classmethod
    def IS_CHANGED(cls, ws_url):
        current_time = datetime.now()
        if cls.last_execution_time is None:
            # Always trigger on the first check
            cls.last_execution_time = current_time
            return current_time.isoformat()
        elif (current_time - cls.last_execution_time) >= cls.execution_interval:
            cls.last_execution_time = current_time
            return current_time.isoformat()
        else:
            return None

class OxleyWebsocketPushImageNode:
    ws_connections = {}  # Class-level dictionary to store WebSocket connections by URL

    @classmethod
    def get_connection(cls, ws_url):
        """Get an existing WebSocket connection or create a new one."""
        try:
            if ws_url not in cls.ws_connections or not cls.ws_connections[ws_url].connected:
                cls.ws_connections[ws_url] = websocket.create_connection(ws_url)
        except Exception as e:
            logging.error(f"Error connecting to WebSocket {ws_url}: {e}")
            # Here, decide whether to retry, raise an exception, or handle the error differently.
            raise
        return cls.ws_connections[ws_url]

    @classmethod
    def close_connection(cls, ws_url):
        """Close and remove a WebSocket connection."""
        if ws_url in cls.ws_connections:
            cls.ws_connections[ws_url].close()
            del cls.ws_connections[ws_url]
            
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_in": ("IMAGE", {}),  # Input image
                "ws_url": ("STRING", {})    # WebSocket URL to push the image to
            },
        }

    RETURN_TYPES = ("STRING",)  # Possible return type for confirmation/message
    RETURN_NAMES = ("status_message",)
    FUNCTION = "push_image_ws"
    CATEGORY = "oxley"

    def push_image_ws(self, image_in, ws_url):
        # Assuming image_in is a PyTorch tensor with shape [1, C, H, W] or similar
        
        # Remove unnecessary dimensions and ensure the tensor is CPU-bound
        image_np = image_in.squeeze().cpu().numpy()
        
        # If your tensor has a shape [C, H, W] (common in PyTorch), convert it to [H, W, C]
        if image_np.ndim == 3 and image_np.shape[0] in {1, 3}:
            # This assumes a 3-channel (RGB) or 1-channel (grayscale) image.
            # Adjust the transpose for different formats if necessary.
            image_np = image_np.transpose(1, 2, 0)
        
        # The tensor should now be in a shape compatible with PIL (H, W, C)
        # For grayscale images (with no color channel), this step isn't necessary.
        
        # Convert numpy array to uint8 if not already
        image_np = np.clip(image_np * 255, 0, 255).astype(np.uint8)
        
        try:
            img = Image.fromarray(image_np)
        except TypeError as e:
            raise ValueError(f"Failed to convert array to image: {e}")

        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        jpeg_bytes = buffer.getvalue()
        base64_bytes = base64.b64encode(jpeg_bytes)
        base64_string = base64_bytes.decode('utf-8')

        try:
            # Initialize or get an existing WebSocket client connection
            ws = self.get_connection(ws_url)
    
            # Prepare the message
            message = json.dumps({"image": base64_string})
    
            # Send the message
            ws.send(message)
            
            return ("Image sent successfully",)
        except ssl.SSLError as ssl_error:
            logging.error(f"SSL error when sending image to {ws_url}: {ssl_error}")
            self.close_connection(ws_url)  # Close the problematic connection
            # Handle the error further or retry as needed.
        except Exception as ex:
            logging.error(f"An error occurred when sending image to {ws_url}: {ex}")
            self.close_connection(ws_url)  # Close the problematic connection
            # Decide how to handle unexpected errors: retry, raise, etc.
        
        return ("Image sent successfully",)

class OxleyWebsocketReceiveJsonNode:
    ws_connections = {}  # Class-level dictionary to store WebSocket connections by URL

    @classmethod
    def get_connection(cls, ws_url):
        """Get an existing WebSocket connection or create a new one."""
        if ws_url not in cls.ws_connections:
            cls.ws_connections[ws_url] = websocket.create_connection(ws_url)
        return cls.ws_connections[ws_url]

    @classmethod
    def close_connection(cls, ws_url):
        """Close and remove a WebSocket connection."""
        if ws_url in cls.ws_connections:
            cls.ws_connections[ws_url].close()
            del cls.ws_connections[ws_url]
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ws_url": ("STRING", {}),  # WebSocket URL to connect to
                "first_field_name": ("STRING", {}),  # Name of the first field to extract
                "second_field_name": ("STRING", {}),  # Name of the second field to extract
                "third_field_name": ("STRING", {})   # Name of the third field to extract
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("first_field_value", "second_field_value", "third_field_value")
    FUNCTION = "receive_json_ws"
    CATEGORY = "oxley"

    def receive_json_ws(self, ws_url, first_field_name, second_field_name, third_field_name):
        # Initialize or get an existing WebSocket client connection
        ws = self.get_connection(ws_url)
        
        # Receive a message
        message = ws.recv()

        try:
            # Attempt to parse the message as JSON
            data = json.loads(message)
        except JSONDecodeError:
            # Handle cases where the message is not valid JSON
            print(f"Received non-JSON message: {message}")
            return ("Error: Non-JSON message received", "", "")

        # Extract specified fields from the JSON data
        first_field_value = data.get(first_field_name, "N/A")
        second_field_value = data.get(second_field_name, "N/A")
        third_field_value = data.get(third_field_name, "N/A")

        # Return the extracted data
        return (first_field_value, second_field_value, third_field_value)

    @classmethod
    def IS_CHANGED(cls, ws_url, first_field_name, second_field_name, third_field_name):
        # Logic to determine if the node should re-execute, potentially based on input changes
        from datetime import datetime
        return datetime.now().isoformat()

class OxleyCustomNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": { "image_in" : ("IMAGE", {}) },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_out",)
    FUNCTION = "invert"
    CATEGORY = "oxley"

    def invert(self, image_in):
        image_out = 1 - image_in
        return (image_out,)

class OxleyDownloadImageNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": { "url" : ("STRING", {}) },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_out",)

    FUNCTION = "download_image"
    CATEGORY = "oxley"

    def download_image(self, url):
        # Send a GET request to the URL
        response = requests.get(url)
        
        # Raise an exception if the request was unsuccessful
        response.raise_for_status()

        # Open the image using Pillow
        image = Image.open(BytesIO(response.content))
        
        # Convert the image to RGB format
        image = image.convert("RGB")

        # Convert the image to a NumPy array and normalize it
        image_array = np.array(image).astype(np.float32) / 255.0

        # Convert the NumPy array to a PyTorch tensor
        image_tensor = torch.from_numpy(image_array)

        # Add a new batch dimension at the beginning
        image_tensor = image_tensor[None,]

        # Return the PyTorch tensor with the batch dimension added
        return (image_tensor,)

    @classmethod
    def IS_CHANGED(cls, url):
        # Always returns a unique value to force the node to be re-executed, e.g. returning a timestamp
        from datetime import datetime
        return datetime.now().isoformat()
