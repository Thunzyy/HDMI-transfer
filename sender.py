import cv2
import numpy as np
import os
import shutil
import time
import math
import struct
import sys
import argparse
from common import *

def create_calibration_frame():
    """Creates a frame to help the receiver calibrate/align."""
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    # White border
    cv2.rectangle(img, (0, 0), (WIDTH-1, HEIGHT-1), (255, 255, 255), 20)
    # Center cross
    cv2.line(img, (WIDTH//2, 0), (WIDTH//2, HEIGHT), (255, 255, 255), 5)
    cv2.line(img, (0, HEIGHT//2), (WIDTH, HEIGHT//2), (255, 255, 255), 5)
    # Red/Green/Blue corners for color check
    cv2.rectangle(img, (0, 0), (100, 100), (0, 0, 255), -1) # Red (BGR)
    cv2.rectangle(img, (WIDTH-100, 0), (WIDTH, 100), (0, 255, 0), -1) # Green
    cv2.rectangle(img, (0, HEIGHT-100), (100, HEIGHT), (255, 0, 0), -1) # Blue
    return img

def encode_frame(data_chunk, frame_index, total_frames):
    """Encodes a chunk of bytes into a frame image using robust 3-bit encoding."""
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    
    # Create header: Frame Index (4 bytes) + Total Frames (4 bytes) + Data Length (4 bytes)
    header = struct.pack('>III', frame_index, total_frames, len(data_chunk))
    full_data = header + data_chunk
    
    # Convert bytes to bits
    # We need a fast way to do this.
    # np.unpackbits works on uint8 arrays
    byte_arr = np.frombuffer(full_data, dtype=np.uint8)
    bits = np.unpackbits(byte_arr)
    
    # Pad bits to match the frame capacity (BLOCKS_PER_FRAME * 3)
    total_bits_needed = BLOCKS_PER_FRAME * 3
    padding_needed = total_bits_needed - len(bits)
    if padding_needed > 0:
        bits = np.pad(bits, (0, padding_needed), 'constant')
        
    # Reshape bits into (Blocks, 3) to get RGB values
    # We have BLOCKS_PER_FRAME blocks.
    # Each block needs 3 bits.
    pixel_bits = bits.reshape((BLOCKS_PER_FRAME, 3))
    
    # Map 0 -> 0, 1 -> 255
    pixel_values = pixel_bits * 255
    
    # Reshape to (ROWS, COLS, 3)
    blocks_grid = pixel_values.reshape((ROWS, COLS, 3)).astype(np.uint8)
    
    # Scale up to full resolution
    img = cv2.resize(blocks_grid, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST)
    
    # Terminal Progress (overwrite line)
    progress = (frame_index + 1) / total_frames
    sys.stdout.write(f"\rProgress: {progress:.1%} ({frame_index + 1}/{total_frames})")
    sys.stdout.flush()
    
    return img

def main():
    parser = argparse.ArgumentParser(description="HDMI Exfiltration Sender")
    parser.add_argument("input_path", help="File or directory to send")
    parser.add_argument("--fps", type=int, default=240, help="Target frames per second (default: 240)")
    parser.add_argument("--redundancy", type=int, default=1, help="Number of times to send each frame (default: 1)")
    
    args = parser.parse_args()

    filepath = args.input_path
    fps = args.fps
    redundancy = args.redundancy
    
    # Handle directory input
    if os.path.isdir(filepath):
        print(f"Directory detected. Zipping '{filepath}'...")
        base_name = os.path.basename(os.path.normpath(filepath))
        archive_path = shutil.make_archive(base_name, 'zip', filepath)
        print(f"Zipped to: {archive_path}")
        filepath = archive_path

    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        return

    # Read file
    with open(filepath, 'rb') as f:
        file_data = f.read()

    # Prepend filename metadata
    # Format: [4 bytes name_len][name_bytes][file_content]
    filename = os.path.basename(filepath)
    filename_bytes = filename.encode('utf-8')
    metadata_header = struct.pack('>I', len(filename_bytes)) + filename_bytes
    
    file_data = metadata_header + file_data
    file_size = len(file_data)
    
    print(f"Sending {filepath} as '{filename}'")
    print(f"Total Data Size: {file_size} bytes")
    print(f"Resolution: {WIDTH}x{HEIGHT}, Block Size: {BLOCK_SIZE}")
    print(f"Bytes per frame: {BYTES_PER_FRAME}")
    
    total_frames = math.ceil(file_size / BYTES_PER_FRAME)
    print(f"Total frames needed: {total_frames}")

    delay = int(1000 / fps)
    print(f"Target FPS: {fps} (Delay: {delay}ms)")
    print(f"Redundancy: {redundancy}x (Each frame sent {redundancy} times)")

    cv2.namedWindow('HDMI Exfil Sender', cv2.WINDOW_NORMAL)
    cv2.setWindowProperty('HDMI Exfil Sender', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    print("Press any key to start transmission...")
    cv2.imshow('HDMI Exfil Sender', create_calibration_frame())
    cv2.waitKey(0)

    # Transmission loop
    start_time = time.time()
    interrupted = False
    paused = False
    
    i = 0
    while i < total_frames:
        if paused:
            # Show Pause Screen
            pause_img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            cv2.putText(pause_img, "PAUSED", (WIDTH//2 - 200, HEIGHT//2), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 165, 255), 4) # Orange
            cv2.putText(pause_img, "Press 'r' to RESUME, 'q' or ESC to QUIT", (WIDTH//2 - 400, HEIGHT//2 + 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.imshow('HDMI Exfil Sender', pause_img)
            
            key = cv2.waitKey(100) & 0xFF
            if key == ord('r'):
                paused = False
                print("\nResuming transmission...")
            elif key == 27 or key == ord('q'): # ESC or q
                interrupted = True
                break
            continue

        # Normal Transmission
        start_byte = i * BYTES_PER_FRAME
        end_byte = min((i + 1) * BYTES_PER_FRAME, file_size)
        chunk = file_data[start_byte:end_byte]
        
        frame = encode_frame(chunk, i, total_frames)
        
        # Redundancy loop
        for _ in range(redundancy):
            cv2.imshow('HDMI Exfil Sender', frame)
            
            # Wait to match target FPS
            key = cv2.waitKey(delay) & 0xFF
            if key == 27: # ESC to PAUSE
                paused = True
                print(f"\nPaused at frame {i}/{total_frames}")
                break # Break redundancy loop to handle pause
        
        if paused:
            continue
            
        i += 1
            
    end_time = time.time()
    duration = end_time - start_time
    if duration > 0:
        speed = (file_size * 8) / duration / 1000000 # Mbps
    else:
        speed = 0
    
    if interrupted:
        print("\n!!! Transmission INTERRUPTED by user !!!")
        print(f"Stopped at frame {i}/{total_frames}")
        
        # Show interruption screen
        end_img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        # Red background or text
        cv2.putText(end_img, "INTERRUPTED", (WIDTH//2 - 400, HEIGHT//2), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 0, 255), 4)
        cv2.putText(end_img, "Press any key to exit", (WIDTH//2 - 300, HEIGHT//2 + 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.imshow('HDMI Exfil Sender', end_img)
        cv2.waitKey(0)
        
    else:
        print(f"Transmission complete.")
        print(f"Time: {duration:.2f}s")
        print(f"Average Speed: {speed:.2f} Mbps")
        
        # Show end screen
        end_img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        cv2.putText(end_img, "DONE", (WIDTH//2 - 100, HEIGHT//2), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 255, 0), 4)
        cv2.imshow('HDMI Exfil Sender', end_img)
        
        print("Closing in 5 seconds...")
        cv2.waitKey(5000)

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
