import cv2
import numpy as np
import os
import sys
import struct
import time
import argparse
import zlib
import hashlib
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


def decode_frame_full(frame_grid):
    """Decode frame returning all protocol fields including frame_type.

    Returns (frame_type, frame_index, total_frames, data, data_len)
    or (None, None, None, None, None) on failure.
    """
    flat_pixels = frame_grid.reshape(-1, 3)
    bits = (flat_pixels > 128).astype(np.uint8)
    flat_bits = bits.reshape(-1)
    packed_bytes = np.packbits(flat_bits)
    frame_bytes = packed_bytes.tobytes()

    if len(frame_bytes) < HEADER_SIZE:
        return None, None, None, None, None

    try:
        magic, frame_type, frame_index, total_frames, data_len = struct.unpack(
            SEQ_HEADER_FMT, frame_bytes[:SEQ_HEADER_PRE_CRC])
    except struct.error:
        return None, None, None, None, None

    if magic != SEQ_MAGIC:
        return None, None, None, None, None

    stored_crc = struct.unpack('>I',
        frame_bytes[SEQ_HEADER_PRE_CRC:HEADER_SIZE])[0]

    if data_len > BYTES_PER_FRAME or data_len == 0:
        return None, None, None, None, None

    payload = frame_bytes[HEADER_SIZE:HEADER_SIZE + data_len]

    computed_crc = zlib.crc32(
        frame_bytes[:SEQ_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
    if computed_crc != stored_crc:
        return None, None, None, None, None

    return frame_type, frame_index, total_frames, payload, data_len


def parse_start_metadata(payload):
    """Parse START frame payload. Returns (file_size, sha256_hash, filename)."""
    if len(payload) < 38:  # 4 + 32 + 2 minimum
        return None, None, None
    file_size = struct.unpack('>I', payload[0:4])[0]
    sha256_hash = payload[4:36]
    filename_len = struct.unpack('>H', payload[36:38])[0]
    filename = payload[38:38 + filename_len].decode('utf-8')
    return file_size, sha256_hash, filename


class TransferState:
    """Transfer lifecycle states."""
    IDLE = 'idle'
    RECEIVING = 'receiving'
    COMPLETE = 'complete'
    ERROR = 'error'


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

    # Transfer state
    transfer_state = TransferState.IDLE
    expected_sha256 = None
    expected_file_size = None
    expected_filename = None
    received_chunks = {}
    total_frames_expected = None
    start_time = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))

        # Visual debug (grid drawing)
        debug_frame = frame.copy()
        for r in range(0, ROWS, 5):
            y = r * BLOCK_SIZE
            cv2.line(debug_frame, (0, y), (WIDTH, y), (0, 255, 255), 1)
        for c in range(0, COLS, 5):
            x = c * BLOCK_SIZE
            cv2.line(debug_frame, (x, 0), (x, HEIGHT), (0, 255, 255), 1)

        sampled = sample_frame(frame)
        ftype, idx, total, data, length = decode_frame_full(sampled)

        if ftype is not None:
            if ftype == FRAME_TYPE_START and transfer_state == TransferState.IDLE:
                # Parse START metadata
                file_size, sha256_hash, filename = parse_start_metadata(data[:length])
                if file_size is not None:
                    expected_sha256 = sha256_hash
                    expected_file_size = file_size
                    expected_filename = filename
                    total_frames_expected = total
                    transfer_state = TransferState.RECEIVING
                    start_time = time.time()
                    print(f"START received: '{filename}' ({file_size} bytes)")
                    print(f"Expected SHA-256: {sha256_hash.hex()}")
                    print(f"Expecting {total_frames_expected} DATA frames.")

            elif ftype == FRAME_TYPE_DATA and transfer_state == TransferState.RECEIVING:
                if idx not in received_chunks:
                    received_chunks[idx] = data[:length]
                    progress = len(received_chunks) / total_frames_expected if total_frames_expected else 0
                    sys.stdout.write(f"\rReceiving: {progress:.1%} ({len(received_chunks)}/{total_frames_expected})")
                    sys.stdout.flush()

                # Visual feedback
                cv2.rectangle(debug_frame, (0,0), (WIDTH, 20), (0, 255, 0), -1)

            elif ftype == FRAME_TYPE_END and transfer_state == TransferState.RECEIVING:
                print("\nEND frame received. Reassembling...")

                # Reassemble
                full_data = bytearray()
                missing = []
                for i in range(total_frames_expected):
                    if i in received_chunks:
                        full_data.extend(received_chunks[i])
                    else:
                        missing.append(i)
                        full_data.extend(b'\x00' * BYTES_PER_FRAME)

                if missing:
                    print(f"WARNING: Missing frames: {missing}")

                # Trim to expected file size
                file_content = bytes(full_data[:expected_file_size])

                # SHA-256 verification
                actual_sha256 = hashlib.sha256(file_content).digest()
                if actual_sha256 != expected_sha256:
                    print("ERROR: SHA-256 MISMATCH -- file corrupted!")
                    print(f"  Expected: {expected_sha256.hex()}")
                    print(f"  Actual:   {actual_sha256.hex()}")
                    transfer_state = TransferState.ERROR
                else:
                    print("SHA-256 verified OK.")
                    transfer_state = TransferState.COMPLETE

                    # Save file
                    if not os.path.isdir(output_path):
                        os.makedirs(output_path)
                    save_path = os.path.join(output_path, expected_filename)
                    with open(save_path, 'wb') as f:
                        f.write(file_content)
                    print(f"Saved to {save_path}")

                # Timing stats
                end_time = time.time()
                duration = end_time - start_time
                total_bytes = len(file_content)
                speed_mbps = (total_bytes * 8) / duration / 1_000_000 if duration > 0 else 0
                print(f"Time: {duration:.2f}s, Speed: {speed_mbps:.2f} Mbps")
                break

        cv2.imshow('Receiver View', debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
