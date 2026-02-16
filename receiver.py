import cv2
import numpy as np
import os
import sys
import struct
import time
import argparse
import zlib
from common import *

def sample_frame(frame):
    """Samples the center pixel of each block in the frame."""
    # Resize down to the grid size using nearest neighbor (effectively sampling)
    # Alternatively, we could manually sample the center pixels for more precision
    # if the alignment isn't perfect.
    # For this prototype, we'll try simple resizing first.
    
    # Note: cv2.resize with INTER_NEAREST on a downscale acts like sampling
    # but we need to be careful about alignment. 
    # A safer way for "capture card" footage (which might have borders or slight shifts)
    # is to sample the specific center coordinates of expected blocks.
    
    # Let's do center sampling:
    sampled_grid = np.zeros((ROWS, COLS, 3), dtype=np.uint8)
    
    half_block = BLOCK_SIZE // 2
    
    # This loop is slow in Python, but for a prototype it's explicit.
    # Optimization: Use array slicing if alignment is perfect.
    # sampled_grid = frame[half_block::BLOCK_SIZE, half_block::BLOCK_SIZE]
    
    # Using slicing for speed (assumes perfect alignment/crop)
    sampled_grid = frame[half_block::BLOCK_SIZE, half_block::BLOCK_SIZE]
    
    # Ensure we got the right shape (handle edge cases in resizing/cropping)
    sampled_grid = sampled_grid[:ROWS, :COLS]
    
    return sampled_grid

def decode_frame(frame_grid):
    """Extracts data from the sampled grid using robust 3-bit decoding.

    Verifies magic number (0xDA7A) and CRC32 integrity.
    Returns (frame_index, total_frames, data, data_len) or (None, None, None, None).
    """
    # Flatten the grid to (Total_Blocks, 3)
    flat_pixels = frame_grid.reshape(-1, 3)

    # Thresholding: > 128 is 1, else 0
    bits = (flat_pixels > 128).astype(np.uint8)

    # Flatten bits to 1D array
    flat_bits = bits.reshape(-1)

    # Pack bits into bytes
    packed_bytes = np.packbits(flat_bits)

    # Convert to bytes object
    frame_bytes = packed_bytes.tobytes()

    # Need at least full header (17 bytes)
    if len(frame_bytes) < HEADER_SIZE:
        return None, None, None, None

    # Parse pre-CRC header fields
    try:
        magic, frame_type, frame_index, total_frames, data_len = struct.unpack(
            SEQ_HEADER_FMT, frame_bytes[:SEQ_HEADER_PRE_CRC])
    except struct.error:
        return None, None, None, None

    # Magic number check
    if magic != SEQ_MAGIC:
        return None, None, None, None

    # Extract stored CRC
    stored_crc = struct.unpack('>I',
        frame_bytes[SEQ_HEADER_PRE_CRC:HEADER_SIZE])[0]

    # Sanity check on data_len
    if data_len > BYTES_PER_FRAME or data_len == 0:
        return None, None, None, None

    # Extract payload
    payload = frame_bytes[HEADER_SIZE:HEADER_SIZE + data_len]

    # Verify CRC32 (over pre-CRC header + payload)
    computed_crc = zlib.crc32(
        frame_bytes[:SEQ_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
    if computed_crc != stored_crc:
        return None, None, None, None

    return frame_index, total_frames, payload, data_len

def main():
    parser = argparse.ArgumentParser(description="HDMI Exfiltration Receiver")
    parser.add_argument("source", help="Video source (Camera index e.g. '0', '1' or file path)")
    parser.add_argument("--output", default="received_files", help="Directory to save received files (default: 'received_files')")
    
    args = parser.parse_args()
    
    source = args.source
    output_path = args.output

    if not os.path.exists(output_path):
        os.makedirs(output_path)
        print(f"Created output directory: {output_path}")
    
    # Handle numeric camera index
    if source.isdigit():
        source = int(source)
        
    cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return

    # Force resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    
    # Try to force high FPS
    cap.set(cv2.CAP_PROP_FPS, 240)
    
    # Check what we actually got
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Camera resolution: {actual_w}x{actual_h} @ {actual_fps} FPS")
        
    print(f"Listening for data on {source}...")
    
    received_chunks = {}
    max_frame_index = -1
    total_frames_expected = None
    start_time = None
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # Resize to expected resolution (handles scaling/stretching)
        if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))
            
        # VISUAL DEBUG: Draw the grid
        debug_frame = frame.copy()
        for r in range(0, ROWS, 5):
            y = r * BLOCK_SIZE
            cv2.line(debug_frame, (0, y), (WIDTH, y), (0, 255, 255), 1)
        for c in range(0, COLS, 5):
            x = c * BLOCK_SIZE
            cv2.line(debug_frame, (x, 0), (x, HEIGHT), (0, 255, 255), 1)
            
        sampled = sample_frame(frame)
        idx, total, data, length = decode_frame(sampled)
        
        if idx is not None:
            # Valid frame found
            if idx not in received_chunks:
                if start_time is None:
                    start_time = time.time()
                    print("First frame received. Timer started.")
                    
                print(f"Received Frame {idx}/{total} ({length} bytes)")
                received_chunks[idx] = data
                if idx > max_frame_index:
                    max_frame_index = idx
                
                # Update expected total
                if total_frames_expected is None:
                    total_frames_expected = total
                    print(f"Expecting {total_frames_expected} frames total.")
            
            # Visual feedback for success
            cv2.rectangle(debug_frame, (0,0), (WIDTH, 20), (0, 255, 0), -1)
            
            # Check for completion
            if total_frames_expected is not None:
                if len(received_chunks) >= total_frames_expected:
                    end_time = time.time()
                    duration = end_time - start_time
                    total_bytes = sum(len(chunk) for chunk in received_chunks.values())
                    speed_mbps = (total_bytes * 8) / duration / 1_000_000 if duration > 0 else 0
                    
                    print("\n" + "="*40)
                    print(f"TRANSFER COMPLETE")
                    print(f"Total Time: {duration:.2f} seconds")
                    print(f"Average Speed: {speed_mbps:.2f} Mbps")
                    print("="*40 + "\n")
                    print("All frames received! Stopping...")
                    break
            
        cv2.imshow('Receiver View', debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break
            
    cap.release()
    cv2.destroyAllWindows()
    
    # Reassemble
    if not received_chunks:
        print("No data received.")
        return

    print(f"Reassembling {len(received_chunks)} chunks...")
    
    # Check for missing frames
    missing = []
    for i in range(max_frame_index + 1):
        if i not in received_chunks:
            missing.append(i)
            
    if missing:
        print(f"WARNING: Missing frames: {missing}")
        print("File will be corrupted.")
    
    # Concatenate all data
    full_data = bytearray()
    for i in range(max_frame_index + 1):
        if i in received_chunks:
            full_data.extend(received_chunks[i])
        else:
            print(f"Filling missing frame {i} with zeros.")
            full_data.extend(b'\x00' * BYTES_PER_FRAME)
            
    # Parse Metadata
    # Format: [4 bytes name_len][name_bytes][file_content]
    try:
        name_len = struct.unpack('>I', full_data[:4])[0]
        filename = full_data[4 : 4 + name_len].decode('utf-8')
        file_content = full_data[4 + name_len:]
        
        print(f"Detected Filename: {filename}")
        
        if not os.path.isdir(output_path):
            if output_path != '.':
                 print(f"Warning: '{output_path}' is not a directory. Saving to current directory.")
            save_path = filename
        else:
            save_path = os.path.join(output_path, filename)
            
        with open(save_path, 'wb') as f:
            f.write(file_content)
            
        print(f"Saved to {save_path}")
        
    except Exception as e:
        print(f"Error parsing metadata: {e}")
        print("Saving raw data to 'dump.bin'...")
        with open('dump.bin', 'wb') as f:
            f.write(full_data)

if __name__ == "__main__":
    main()
