import os
import random
import string
import cv2
import numpy as np
from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import *

def generate_random_file(filename, size_kb):
    size = size_kb * 1024
    with open(filename, 'wb') as f:
        f.write(os.urandom(size))

def test_loopback():
    test_file = "test_data.bin"
    output_file = "test_output.bin"
    
    # Generate 100KB random file
    print("Generating test file...")
    generate_random_file(test_file, 100)
    
    # Read file
    with open(test_file, 'rb') as f:
        file_data = f.read()
        
    file_size = len(file_data)
    total_frames = (file_size + BYTES_PER_FRAME - 1) // BYTES_PER_FRAME
    
    print(f"Encoding {file_size} bytes into {total_frames} frames...")
    
    decoded_data = bytearray()
    
    for i in range(total_frames):
        start = i * BYTES_PER_FRAME
        end = min((i + 1) * BYTES_PER_FRAME, file_size)
        chunk = file_data[start:end]
        
        # Encode
        frame_img = encode_frame(chunk, i)
        
        # Simulate transmission (perfect quality)
        # In real life, we'd add noise or compression artifacts here to test robustness
        received_frame = frame_img
        
        # Decode
        sampled = sample_frame(received_frame)
        idx, data, length = decode_frame(sampled)
        
        if idx != i:
            print(f"ERROR: Frame index mismatch! Expected {i}, got {idx}")
            return
            
        decoded_data.extend(data)
        
    # Verify
    if decoded_data == file_data:
        print("SUCCESS: Decoded data matches original file!")
    else:
        print("FAILURE: Decoded data does not match.")
        print(f"Original len: {len(file_data)}, Decoded len: {len(decoded_data)}")
        
    # Clean up
    if os.path.exists(test_file):
        os.remove(test_file)
    if os.path.exists(output_file):
        os.remove(output_file)

if __name__ == "__main__":
    test_loopback()
